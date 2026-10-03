import os
import sys
import xarray as xr
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, date
import matplotlib.colors as colors
import json
import requests
import csv
import validacio
import calibracio_radar

# --- CONFIGURACIÓ API METEOCAT ---
# La clau es llegeix del secret del repositori (Settings > Secrets > Actions > METEOCAT_API_KEY)
API_KEY = os.environ.get("METEOCAT_API_KEY", "").strip()
BASE_URL = "https://api.meteo.cat/xema/v1"
CODI_PLUJA = "1300"
TIMEOUT = 30

OUTPUT_DIR = "dades_radar"
DAILY_DIR = "acumulats_diaris"
CFG_CALIBRACIO = calibracio_radar.carregar_config()

# Cache per no repetir crides a l'API quan es processen molts dies
_cache_metadades = None
_cache_mesos = {}


def api_get(path):
    if not API_KEY:
        raise RuntimeError("Falta la variable d'entorn METEOCAT_API_KEY")
    res = requests.get(f"{BASE_URL}{path}", headers={"X-Api-Key": API_KEY}, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def get_estacions_info():
    global _cache_metadades
    if _cache_metadades is None:
        info = {}
        for e in api_get("/estacions/metadades"):
            info[e['codi']] = {
                'nom': e['nom'],
                'lat': e['coordenades']['latitud'],
                'lon': e['coordenades']['longitud']
            }
        _cache_metadades = info
        validacio.desar_estacions(info)
    return _cache_metadades


def estacions_per_recomptes():
    """Metadades d'estacions: de l'API si es pot, si no de la còpia guardada."""
    try:
        return get_estacions_info()
    except Exception as e:
        print(f"⚠️ No s'han pogut obtenir les estacions de l'API ({e}); es fa servir la còpia local.")
        return validacio.carregar_estacions()


def get_dades_mes(year, month):
    key = (year, month)
    if key not in _cache_mesos:
        _cache_mesos[key] = api_get(f"/variables/estadistics/diaris/{CODI_PLUJA}?any={year}&mes={month:02d}")
    return _cache_mesos[key]


def get_stations_daily_data(date_obj):
    """Obté la pluja i coordenades de les estacions per a un dia concret"""
    date_api_str = date_obj.strftime("%Y-%m-%dZ")
    print(f"📡 Descarregant dades d'estacions per al {date_obj.strftime('%Y-%m-%d')}...")

    estacions_info = get_estacions_info()
    dades_completes = []
    for estacio in get_dades_mes(date_obj.year, date_obj.month):
        codi = estacio.get('codiEstacio')
        if codi in estacions_info:
            info = estacions_info[codi]
            for val in estacio.get('valors', []):
                if val['data'] == date_api_str:
                    dades_completes.append({
                        'codi': codi,
                        'nom': info['nom'],
                        'lat': info['lat'],
                        'lon': info['lon'],
                        'data': date_api_str.replace('Z', ''),
                        'pluja': float(val['valor'])
                    })
    return dades_completes


def correccio_pendent(path_nc):
    try:
        with xr.open_dataset(path_nc) as ds:
            return ds.attrs.get("correccio") == "pendent"
    except Exception:
        return False


def dies_pendents():
    """Retorna tots els dies anteriors a avui (UTC) que tenen fitxers de radar sense processar,
    més el dia d'ahir (per assegurar que sempre es descarreguen les estacions)."""
    avui = datetime.utcnow().date()
    dies = set()
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith("radar_") and f.endswith(".nc"):
                try:
                    d = datetime.strptime(f[6:14], "%Y%m%d").date()
                except ValueError:
                    continue
                if d < avui:
                    dies.add(d)
    ahir = avui - timedelta(days=1)
    dies.add(ahir)
    # Dies recents sense fitxer d'estacions (p. ex. si l'API va fallar)
    for i in range(1, 31):
        d = avui - timedelta(days=i)
        nc = os.path.join(DAILY_DIR, f"acumulat_{d:%Y%m%d}.nc")
        if os.path.exists(nc) and (
                not os.path.exists(os.path.join(DAILY_DIR, f"estacions_{d:%Y%m%d}.json"))
                or correccio_pendent(nc)):
            dies.add(d)
    return sorted(dies)


def desar_acumulat(dia_str, lat, lon, original, calibrat, n_imatges, fonts, estacions):
    """Desa l'acumulat diari (NetCDF + PNG + fonts) aplicant la calibració.

    Variables del NetCDF:
      - precipitacio_acumulada: producte final (taula calibrada + correcció amb estacions).
        És la que fan servir el mapa, el setmanal i el mensual.
      - precipitacio_radar: només taula calibrada (normalitzada per imatges), sense estacions.
        Permet aplicar la correcció més tard si les estacions encara no estan disponibles.
      - precipitacio_original: acumulat amb la taula original, igual que abans de la calibració.
        Es manté per a la validació (validacio/parelles), perquè no depengui de la calibració.
    """
    lat = np.asarray(lat)
    lon = np.asarray(lon)
    cfg = CFG_CALIBRACIO
    if estacions and cfg["correccio_estacions"].get("activa", True):
        final, info = calibracio_radar.corregir_amb_estacions(calibrat, lat, lon, estacions, cfg)
    else:
        final, info = calibrat.copy(), {"correccio": "pendent"}

    attrs = {
        "description": f"Acumulat diari {dia_str}", "units": "mm", "date": dia_str,
        "files_count": int(n_imatges), "resolution_min": 6,
        "calibracio_versio": cfg["versio"],
        "calibracio": "taula ajustada (config_calibracio.json) + correccio local amb estacions XEMA",
    }
    attrs.update({f"correccio_{k}" if not k.startswith("correccio") else k: v for k, v in info.items()})
    enc = {v: {"zlib": True, "complevel": 4} for v in
           ["precipitacio_acumulada", "precipitacio_radar", "precipitacio_original"]}
    ds = xr.Dataset(
        {"precipitacio_acumulada": (["lat", "lon"], final.astype("f4")),
         "precipitacio_radar": (["lat", "lon"], calibrat.astype("f4")),
         "precipitacio_original": (["lat", "lon"], original.astype("f4"))},
        coords={"lon": lon, "lat": lat}, attrs=attrs)
    nc_out_path = os.path.join(DAILY_DIR, f"acumulat_{dia_str}.nc")
    ds.to_netcdf(nc_out_path, encoding=enc)
    print(f"✅ NetCDF diari guardat: {nc_out_path} ({n_imatges} imatges, correcció: {info['correccio']}"
          + (f", {info.get('estacions_usades', 0)} estacions, biaix mitjà {info.get('biaix_mitja')}" if info['correccio'] == 'local' else "")
          + ")")

    if fonts is not None:
        with open(os.path.join(DAILY_DIR, f"fonts_acumulat_{dia_str}.txt"), "w") as f_txt:
            f_txt.write(f"Resum de l'acumulat del dia {dia_str}:\nTotal fitxers processats: {n_imatges}\n\n")
            f_txt.write("\n".join(fonts))

    generate_daily_png(xr.DataArray(final), xr.DataArray(lon), xr.DataArray(lat), dia_str)


def process_radar_day(dia_str, estacions):
    all_files_paths = sorted(
        os.path.join(OUTPUT_DIR, f) for f in os.listdir(OUTPUT_DIR)
        if f.startswith(f"radar_{dia_str}") and f.endswith(".nc")
    ) if os.path.exists(OUTPUT_DIR) else []

    if not all_files_paths:
        print(f"ℹ️ No hi ha fitxers de radar pendents per al dia {dia_str}.")
        return False

    acc = calibracio_radar.Acumulador(CFG_CALIBRACIO)
    lon, lat = None, None
    used_files = []
    for file_path in all_files_paths:
        try:
            with xr.open_dataset(file_path) as ds:
                acc.afegir(ds['precipitacio'].values)
                if lon is None:
                    lon, lat = ds['lon'].values, ds['lat'].values
                used_files.append(os.path.basename(file_path))
        except Exception as e:
            print(f"⚠️ Error obrint {file_path}: {e}")

    if acc.n == 0:
        print(f"⚠️ Cap fitxer de radar llegible per al dia {dia_str}.")
        return False

    original, calibrat = acc.resultat()
    desar_acumulat(dia_str, lat, lon, original, calibrat, acc.n, used_files, estacions)

    # Recompte de classes de color al píxel de cada estació (abans d'esborrar els fitxers de 6 min)
    try:
        validacio.recomptes_classes(all_files_paths, f"{dia_str[:4]}-{dia_str[4:6]}-{dia_str[6:]}",
                                    estacions_per_recomptes())
    except Exception as e:
        print(f"⚠️ Error calculant els recomptes de classes: {e}")

    print(f"🗑️ Netejant fitxers de radar del dia {dia_str}...")
    for f_path in all_files_paths:
        try:
            os.remove(f_path)
        except Exception as e:
            print(f"⚠️ No s'ha pogut eliminar {f_path}: {e}")
    return True


def corregir_pendent(dia_str, estacions):
    """Si l'acumulat d'un dia es va desar sense correcció (estacions no disponibles),
    l'aplica ara a partir de la variable precipitacio_radar."""
    path = os.path.join(DAILY_DIR, f"acumulat_{dia_str}.nc")
    if not estacions or not os.path.exists(path):
        return
    with xr.open_dataset(path) as ds:
        if ds.attrs.get("correccio") != "pendent" or "precipitacio_radar" not in ds:
            return
        ds = ds.load()
    print(f"🔁 Aplicant la correcció amb estacions pendent del {dia_str}")
    desar_acumulat(dia_str, ds.lat.values, ds.lon.values, ds.precipitacio_original.values,
                   ds.precipitacio_radar.values, ds.attrs.get("files_count", 0), None, estacions)


def process_stations_day(dia_obj):
    """Descarrega i desa les estacions del dia. Retorna la llista d'estacions o None si falla."""
    dia_str = dia_obj.strftime("%Y%m%d")
    try:
        estacions_data = get_stations_daily_data(dia_obj)
    except Exception as e:
        print(f"❌ Error obtenint dades d'estacions per al {dia_str}: {e}")
        return None
    if not estacions_data:
        print(f"⚠️ No s'han trobat dades d'estacions per al {dia_str}.")
        return []

    csv_path = os.path.join(DAILY_DIR, f"estacions_{dia_str}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Codi', 'Nom', 'Data', 'Precipitacio_mm'])
        for d in estacions_data:
            writer.writerow([d['codi'], d['nom'], d['data'], d['pluja']])
    save_stations_geojson(estacions_data, os.path.join(DAILY_DIR, f"estacions_{dia_str}.json"))
    print(f"📍 Estacions guardades: {len(estacions_data)} ({dia_str})")
    return estacions_data


def calculate_daily():
    os.makedirs(DAILY_DIR, exist_ok=True)
    dies = dies_pendents()
    print(f"📅 Dies a processar: {', '.join(d.strftime('%Y%m%d') for d in dies)}")

    errors_estacions = 0
    for dia_obj in dies:
        dia_str = dia_obj.strftime("%Y%m%d")
        print(f"\n===== {dia_str} =====")
        # Primer les estacions: calen per corregir el radar
        estacions = process_stations_day(dia_obj)
        if estacions is None:
            errors_estacions += 1
        if not process_radar_day(dia_str, estacions):
            corregir_pendent(dia_str, estacions)

    # Parelles radar-estació per a validació (dies amb acumulat i estacions)
    try:
        validacio.extreure_parelles(DAILY_DIR)
    except Exception as e:
        print(f"⚠️ Error extraient parelles radar-estació: {e}")

    if errors_estacions:
        print(f"\n⚠️ {errors_estacions} dia(es) sense dades d'estacions. Es reintentarà a la propera execució.")


def generate_daily_png(data, lon, lat, date_str):
    fig = plt.figure(frameon=False)
    fig.set_size_inches(data.shape[1] / 100, data.shape[0] / 100)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.set_axis_off()
    fig.add_axes(ax)
    norm = colors.LogNorm(vmin=0.1, vmax=200)
    cmap = plt.get_cmap('turbo').copy()
    cmap.set_under(alpha=0)
    ax.pcolormesh(lon.values, lat.values, data.values, cmap=cmap, norm=norm, shading='auto')
    png_out_path = os.path.join(DAILY_DIR, f"acumulat_{date_str}.png")
    fig.savefig(png_out_path, transparent=True, dpi=100)
    plt.close(fig)
    print(f"🎨 PNG guardat: {png_out_path}")

    bounds_data = {
        "lat_min": float(lat.min()), "lat_max": float(lat.max()),
        "lon_min": float(lon.min()), "lon_max": float(lon.max())
    }
    with open("bounds.json", "w") as f:
        json.dump(bounds_data, f)


def save_stations_geojson(dades, path):
    geojson = {"type": "FeatureCollection", "features": []}
    for d in dades:
        if d['pluja'] >= 0:
            geojson["features"].append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [d['lon'], d['lat']]},
                "properties": {
                    "codi": d['codi'], "nom": d['nom'],
                    "pluja": d['pluja'], "data": d['data']
                }
            })
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)


if __name__ == "__main__":
    if not API_KEY:
        print("⚠️ Falta METEOCAT_API_KEY (Settings > Secrets and variables > Actions). "
              "Es processarà el radar però no les estacions.")
    calculate_daily()
