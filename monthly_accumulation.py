"""
Acumulat mensual + neteja d'acumulats diaris antics.

1. Genera l'acumulat mensual de cada mes complet que encara no en tingui
   (normalment, el dia 1 genera el del mes anterior).
   Igual que el setmanal, només suma el radar dels dies en què alguna estació
   XEMA ha registrat >= 1 mm (validació d'anticicló).
2. Esborra els fitxers diaris (radar i estacions) dels mesos anteriors als
   dos últims mesos. Exemple: a l'octubre conserva agost, setembre i octubre.
   Mai esborra un mes que no tingui el seu acumulat mensual generat.

Ús:
    python monthly_accumulation.py            # mesos pendents + neteja
    python monthly_accumulation.py 2026-09    # força (re)generar un mes concret
"""
import os
import sys
import csv
import json
import calendar
import validacio
from datetime import datetime, date, timedelta

import requests
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as colors

API_KEY = os.environ.get("METEOCAT_API_KEY", "").strip()
BASE_URL = "https://api.meteo.cat/xema/v1"
CODI_PLUJA = "1300"
TIMEOUT = 30

DAILY_DIR = "acumulats_diaris"
MONTHLY_DIR = "acumulats_mensuals"
MESOS_A_CONSERVAR = 2   # mesos anteriors a l'actual que es conserven en diari
LLINDAR_PLUJA = 1.0     # mm: si cap estació arriba a aquest valor, el dia es considera sec

DAILY_PREFIXES = ("acumulat_", "fonts_acumulat_", "estacions_")


def api_get(path):
    res = requests.get(f"{BASE_URL}{path}", headers={"X-Api-Key": API_KEY}, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def mesos_amb_diaris():
    """Conjunt de (any, mes) que tenen algun acumulat diari NetCDF."""
    mesos = set()
    if os.path.exists(DAILY_DIR):
        for f in os.listdir(DAILY_DIR):
            if f.startswith("acumulat_") and f.endswith(".nc"):
                try:
                    d = datetime.strptime(f[9:17], "%Y%m%d").date()
                    mesos.add((d.year, d.month))
                except ValueError:
                    pass
    return mesos


def mensual_existeix(year, month):
    return os.path.exists(os.path.join(MONTHLY_DIR, f"mensual_{year}{month:02d}.nc"))


def mesos_pendents():
    """Mesos complets (anteriors a l'actual) amb diaris però sense mensual."""
    avui = datetime.utcnow().date()
    mes_actual = (avui.year, avui.month)
    pendents = []
    for (y, m) in sorted(mesos_amb_diaris()):
        if (y, m) >= mes_actual or mensual_existeix(y, m):
            continue
        # Si és el mes just anterior, esperem que existeixi l'acumulat de l'últim dia
        ultim_dia = date(y, m, calendar.monthrange(y, m)[1])
        es_mes_anterior = add_months(date(*mes_actual, 1), -1) == date(y, m, 1)
        if es_mes_anterior and not os.path.exists(os.path.join(DAILY_DIR, f"acumulat_{ultim_dia:%Y%m%d}.nc")):
            print(f"⏳ {y}-{m:02d}: encara falta l'acumulat diari del {ultim_dia}. Es deixa per més endavant.")
            continue
        pendents.append((y, m))
    return pendents


def dades_estacions_mes(year, month, metadades):
    """Retorna (validesa per dia, registres CSV, totals per estació)."""
    dades = api_get(f"/variables/estadistics/diaris/{CODI_PLUJA}?any={year}&mes={month:02d}")
    n_dies = calendar.monthrange(year, month)[1]

    stats = {codi: dict(info, total=0.0, dies=0) for codi, info in metadades.items()}
    validesa = {}
    registres = []
    for dia in range(1, n_dies + 1):
        d = date(year, month, dia)
        data_api = d.strftime("%Y-%m-%dZ")
        max_val, max_nom = -1.0, "Sense dades"
        for estacio in dades:
            codi = estacio.get("codiEstacio")
            for val in estacio.get("valors", []):
                if val["data"] != data_api:
                    continue
                v = float(val["valor"])
                nom = metadades.get(codi, {}).get("nom", codi)
                registres.append([codi, nom, data_api.replace("Z", ""), v])
                if codi in stats:
                    stats[codi]["total"] += v
                    stats[codi]["dies"] += 1
                if v > max_val:
                    max_val, max_nom = v, nom
        validesa[d.strftime("%Y%m%d")] = {"valid": max_val >= LLINDAR_PLUJA, "max_nom": max_nom, "max_val": max_val}
    return validesa, registres, stats


def generar_mes(year, month, metadades):
    mes_id = f"{year}{month:02d}"
    print(f"\n===== Mensual {year}-{month:02d} =====")
    validesa, registres, stats = dades_estacions_mes(year, month, metadades)
    if not registres:
        raise RuntimeError(f"L'API no ha retornat dades d'estacions per a {year}-{month:02d}")

    total, lon, lat = None, None, None
    resum = [f"RESUM MENSUAL: {year}-{month:02d}", "-" * 50]
    dies_sumats = dies_secs = dies_sense_radar = 0

    for dia_id, info in sorted(validesa.items()):
        path_nc = os.path.join(DAILY_DIR, f"acumulat_{dia_id}.nc")
        existeix = os.path.exists(path_nc)
        if info["valid"] and existeix:
            with xr.open_dataset(path_nc) as ds:
                dades = ds["precipitacio_acumulada"].load()
                if total is None:
                    total = dades.copy()
                    lon, lat = ds["lon"].load(), ds["lat"].load()
                else:
                    total += dades
            dies_sumats += 1
            resum.append(f"{dia_id}: PLUJA      -> {info['max_nom']} ({info['max_val']} mm)")
        elif info["valid"]:
            dies_sense_radar += 1
            resum.append(f"{dia_id}: ERROR      -> Fitxer NC no trobat")
        elif info["max_val"] < 0:
            resum.append(f"{dia_id}: SENSE DADES -> Cap estació amb dades aquest dia")
        else:
            dies_secs += 1
            avis = "" if existeix else " [sense NC]"
            resum.append(f"{dia_id}: ANTICICLÓ  -> Màxim: {info['max_nom']} ({info['max_val']} mm){avis}")

    if total is None:
        # Mes sense cap dia vàlid: fem servir qualsevol diari com a plantilla de malla
        plantilla = next((os.path.join(DAILY_DIR, f) for f in sorted(os.listdir(DAILY_DIR))
                          if f.startswith("acumulat_") and f.endswith(".nc")), None)
        if plantilla is None:
            raise RuntimeError("No hi ha cap NetCDF diari per fer de plantilla")
        with xr.open_dataset(plantilla) as ds:
            total = xr.zeros_like(ds["precipitacio_acumulada"]).load()
            lon, lat = ds["lon"].load(), ds["lat"].load()

    resum += ["-" * 50,
              f"Dies amb pluja sumats: {dies_sumats}",
              f"Dies secs (no sumats): {dies_secs}",
              f"Dies amb pluja però sense radar: {dies_sense_radar}"]

    os.makedirs(MONTHLY_DIR, exist_ok=True)

    # NetCDF
    xr.Dataset(
        {"precipitacio_mensual": (["lat", "lon"], total.values)},
        coords={"lon": lon, "lat": lat},
        attrs={"description": f"Acumulat mensual {year}-{month:02d}", "units": "mm",
               "dies_sumats": dies_sumats, "dies_secs": dies_secs},
    ).to_netcdf(os.path.join(MONTHLY_DIR, f"mensual_{mes_id}.nc"))

    # PNG
    fig = plt.figure(frameon=False)
    fig.set_size_inches(total.shape[1] / 100, total.shape[0] / 100)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.set_axis_off()
    fig.add_axes(ax)
    if float(np.nanmax(total.values)) > 0.1:
        cmap = plt.get_cmap("turbo").copy()
        cmap.set_under(alpha=0)
        ax.pcolormesh(lon.values, lat.values, total.values, cmap=cmap,
                      norm=colors.LogNorm(vmin=0.1, vmax=600), shading="auto")
    fig.savefig(os.path.join(MONTHLY_DIR, f"mensual_{mes_id}.png"), transparent=True, dpi=100)
    plt.close(fig)

    # Resum
    with open(os.path.join(MONTHLY_DIR, f"resum_{mes_id}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(resum))

    # CSV amb tots els valors diaris
    with open(os.path.join(MONTHLY_DIR, f"estacions_{mes_id}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Codi", "Nom", "Data", "Precipitacio_mm"])
        w.writerows(registres)

    # GeoJSON amb el total mensual per estació (només estacions amb dades)
    geojson = {"type": "FeatureCollection", "features": []}
    for codi, d in stats.items():
        if d["dies"] > 0:
            geojson["features"].append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
                "properties": {"nom": d["nom"], "codi": codi, "pluja": round(d["total"], 1), "dies": d["dies"]},
            })
    with open(os.path.join(MONTHLY_DIR, f"estacions_{mes_id}.json"), "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"✅ Mensual {year}-{month:02d}: {dies_sumats} dies sumats, {dies_secs} secs, "
          f"{len(geojson['features'])} estacions.")


def netejar_diaris():
    """Esborra els diaris dels mesos anteriors a (mes actual - MESOS_A_CONSERVAR)."""
    avui = datetime.utcnow().date()
    limit = add_months(date(avui.year, avui.month, 1), -MESOS_A_CONSERVAR)
    limit_id = limit.strftime("%Y%m")
    print(f"\n🧹 Netejant diaris anteriors a {limit:%Y-%m} (es conserven des de {limit:%Y-%m})")

    esborrats, protegits, sense_parelles = 0, set(), set()
    amb_parelles = validacio.dates_amb_parelles()
    for f in sorted(os.listdir(DAILY_DIR)):
        if not f.startswith(DAILY_PREFIXES):
            continue
        dia = f.rsplit("_", 1)[-1][:8]
        if not (dia.isdigit() and len(dia) == 8) or dia[:6] >= limit_id:
            continue
        y, m = int(dia[:4]), int(dia[4:6])
        if not mensual_existeix(y, m):
            protegits.add(f"{y}-{m:02d}")
            continue
        # No esborrem un dia si encara no s'han extret les parelles radar-estació
        if f.startswith("acumulat_") and dia not in amb_parelles and \
                os.path.exists(os.path.join(DAILY_DIR, f"estacions_{dia}.json")):
            sense_parelles.add(dia)
            continue
        os.remove(os.path.join(DAILY_DIR, f))
        esborrats += 1

    print(f"🗑️ Fitxers diaris esborrats: {esborrats}")
    if sense_parelles:
        print(f"⚠️ No s'han esborrat {len(sense_parelles)} dies perquè encara no tenen parelles radar-estació.")
    if protegits:
        print(f"⚠️ No s'han esborrat els diaris de {', '.join(sorted(protegits))} perquè no tenen mensual.")


def main():
    if not API_KEY:
        print("❌ Falta METEOCAT_API_KEY. Afegeix-la a Settings > Secrets and variables > Actions.")
        sys.exit(1)

    if len(sys.argv) > 1:
        d = datetime.strptime(sys.argv[1], "%Y-%m")
        mesos = [(d.year, d.month)]
    else:
        mesos = mesos_pendents()

    errors = 0
    if mesos:
        metadades = {
            e["codi"]: {"nom": e["nom"], "lat": e["coordenades"]["latitud"], "lon": e["coordenades"]["longitud"]}
            for e in api_get("/estacions/metadades")
        }
        for y, m in mesos:
            try:
                generar_mes(y, m, metadades)
            except Exception as e:
                errors += 1
                print(f"❌ Error generant {y}-{m:02d}: {e}")
    else:
        print("ℹ️ No hi ha cap mes pendent.")

    netejar_diaris()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
