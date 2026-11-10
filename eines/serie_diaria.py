"""
Sèrie diària completa en un sol NetCDF, recalculada amb la calibració actual.

Recalcula TOTS els dies des de l'inici del projecte (25/02/2026) amb el mateix mètode que el
pipeline actual (calibracio_radar.py + config_calibracio.json), perquè la sèrie sigui homogènia:
  1. imatges de 6 min → taula de colors ajustada, normalitzada per les imatges disponibles;
  2. correcció local diària amb les estacions XEMA del dia (validacio/parelles/).

Fonts de les imatges de 6 min:
  - fins al 03/10/2026: historial de git (dades_radar/);
  - des del 03/10/2026: paquets diaris arxiu_radar (Releases radar-arxiu-AAAAMM), que el workflow
    descarrega a la carpeta indicada amb --paquets. Si un dia és a tots dos llocs, es fa servir
    el paquet (té totes les imatges del dia).

Abans del 04/03/2026 12:39 UTC la llegenda de colors de radar_to_nc.py era diferent: els valors
desats es tornen a convertir a la classe de color corresponent. A més, dos colors (pluja moderada)
no es detectaven i aquells píxels van quedar com a "sense eco": aquests dies es marquen a `qualitat`.

Ús (des de l'arrel del repo, amb l'historial complet):
    python eines/serie_diaria.py serie_diaria_plujacat.nc [--paquets DIR] [--des AAAAMMDD] [--fins AAAAMMDD]
"""
import os
import re
import sys
import ast
import csv
import glob
import argparse
import subprocess
from datetime import datetime, date, timezone

import numpy as np
import netCDF4

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ARREL)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ARREL)

import calibracio_radar  # noqa: E402
import arxiu_radar  # noqa: E402
from backfill_recomptes import blobs_radar, LectorBlobs  # noqa: E402

INICI_LLEGENDA_ACTUAL = datetime(2026, 3, 4, 12, 39, 13, tzinfo=timezone.utc)
MIN_IMATGES_CALCUL = 120     # < 50 % del dia: no es calcula (la normalització no té sentit)
MIN_IMATGES_COMPLET = 216    # < 90 % del dia: es marca

# Bits de la variable `qualitat`
Q_LLEGENDA = 1      # llegenda antiga: falten dos colors (pluja moderada) a part de les imatges
Q_POQUES = 2        # menys del 90 % de les imatges del dia
Q_NO_CALCULAT = 4   # menys del 50 % de les imatges: valors no calculats (NaN)
Q_SENSE_CORR = 8    # sense correcció amb estacions (cap estació amb pluja, o sense dades XEMA)


# ------------------------------------------------------------------ llegendes antigues

def _llegendes():
    """[(des_de_utc, {valor_desat: valor_classe_actual})] de totes les versions de radar_to_nc.py."""
    actual = ast.literal_eval(re.search(r"LLEGENDA_RADAR\s*=\s*(\{.*?\})",
                                        open("radar_to_nc.py", encoding="utf-8").read(), re.S).group(1))
    out, prev = [], None
    log = subprocess.run(["git", "log", "--reverse", "--format=%H %cI", "--", "radar_to_nc.py"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    for linia in filter(None, log):
        sha, quan = linia.split()
        try:
            src = subprocess.run(["git", "show", f"{sha}:radar_to_nc.py"],
                                 capture_output=True, text=True, check=True).stdout
            lleg = ast.literal_eval(re.search(r"LLEGENDA_RADAR\s*=\s*(\{.*?\})", src, re.S).group(1))
        except Exception:
            continue
        if lleg == prev:
            continue
        prev = lleg
        mapa = {}
        for rgb, val in lleg.items():
            if rgb in actual and round(float(val), 3) not in mapa:   # colors mal definits no van detectar res
                mapa[round(float(val), 3)] = float(actual[rgb])
        out.append((datetime.fromisoformat(quan).astimezone(timezone.utc), mapa))
    return out


LLEGENDES = None


def a_classes_actuals(valors, moment):
    """Converteix els valors desats amb una llegenda antiga als valors de la classe actual."""
    if moment >= INICI_LLEGENDA_ACTUAL:
        return valors
    candidates = [m for t, m in LLEGENDES if t <= moment] or [LLEGENDES[0][1]]
    vistos = set(np.round(np.unique(valors[~np.isnan(valors)]), 3))
    mapa = next((m for m in reversed(candidates) if vistos <= set(m)), None)
    if mapa is None:  # el workflow encara feia servir la versió anterior del codi
        mapa = next((m for _, m in LLEGENDES if vistos <= set(m)), candidates[-1])
    out = np.full_like(valors, np.nan)
    r = np.round(valors, 3)
    for v_ant, v_act in mapa.items():
        out[r == v_ant] = v_act
    return out


# ------------------------------------------------------------------ estacions

def estacions_xema():
    """{AAAA-MM-DD: [ {codi, nom, lat, lon, pluja} ]} de validacio/parelles/."""
    per_dia = {}
    for path in sorted(glob.glob(os.path.join("validacio", "parelles", "parelles_*.csv"))):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    pluja = float(r["pluja_estacio"])
                except ValueError:
                    continue
                per_dia.setdefault(r["data"], []).append(
                    {"codi": r["codi"], "nom": r["nom"], "lat": float(r["lat"]),
                     "lon": float(r["lon"]), "pluja": pluja})
    return per_dia


# ------------------------------------------------------------------ fonts d'imatges

def imatges_dia(dia, fonts_git, paquets, lector):
    """Generador de (moment_utc, camp_mm_h) del dia, en valors de les classes actuals."""
    paquet = paquets.get(dia)
    if paquet:
        for t, camp in arxiu_radar.llegir_paquet(paquet):
            yield datetime.strptime(t, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc), camp
        return
    for nom, sha in fonts_git.get(dia, []):
        try:
            ds = netCDF4.Dataset("mem", memory=lector.llegir(sha))
            camp = np.ma.filled(ds["precipitacio"][:].astype("f8"), np.nan)
            ds.close()
        except Exception as e:
            print(f"⚠️ {nom}: {e}")
            continue
        moment = datetime.strptime(nom[6:21], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        yield moment, a_classes_actuals(camp, moment)


def graella(fonts_git, paquets, lector):
    if paquets:
        with netCDF4.Dataset(next(iter(paquets.values()))) as ds:
            return ds["lat"][:].data, ds["lon"][:].data
    nom, sha = next(iter(fonts_git.values()))[0]
    ds = netCDF4.Dataset("mem", memory=lector.llegir(sha))
    lat, lon = ds["lat"][:].data, ds["lon"][:].data
    ds.close()
    return lat, lon


# ------------------------------------------------------------------ NetCDF de sortida

def crear_sortida(path, lat, lon, cfg):
    nc = netCDF4.Dataset(path, "w", format="NETCDF4")
    nc.createDimension("time", None)
    nc.createDimension("lat", len(lat))
    nc.createDimension("lon", len(lon))
    t = nc.createVariable("time", "i4", ("time",))
    t.units, t.calendar, t.standard_name = "days since 2026-01-01 00:00:00", "standard", "time"
    t.long_name = "inici del dia (00 UTC); l'acumulat cobreix 00–24 UTC"
    for nom, val, std in (("lat", lat, "latitude"), ("lon", lon, "longitude")):
        v = nc.createVariable(nom, "f8", (nom,))
        v[:] = val
        v.standard_name, v.units = std, "degrees_north" if nom == "lat" else "degrees_east"
    kw = dict(zlib=True, complevel=5, least_significant_digit=2, fill_value=np.float32(np.nan),
              chunksizes=(1, len(lat), len(lon)))
    for nom, desc in (
        ("precipitacio", "Pluja diària (producte final): taula de colors ajustada + correcció local amb les estacions XEMA del dia"),
        ("precipitacio_radar", "Pluja diària només amb la taula de colors ajustada (sense estacions)"),
        ("precipitacio_original", "Pluja diària amb la taula de colors manual (sense normalitzar ni corregir), com el producte abans de la calibració"),
    ):
        v = nc.createVariable(nom, "f4", ("time", "lat", "lon"), **kw)
        v.units, v.long_name = "mm", desc
    nc["precipitacio"].standard_name = "precipitation_amount"
    for nom, tipus, desc in (("n_imatges", "i2", "imatges de radar de 6 min disponibles (240 = dia complet)"),
                             ("n_estacions_correccio", "i2", "estacions XEMA amb pluja usades a la correcció"),
                             ("biaix_mitja", "f4", "biaix mitjà del dia: Σ XEMA / Σ radar (taula ajustada)")):
        v = nc.createVariable(nom, tipus, ("time",))
        v.long_name = desc
    q = nc.createVariable("qualitat", "u1", ("time",))
    q.long_name = "indicadors de qualitat (suma de bits)"
    q.flag_masks = np.array([Q_LLEGENDA, Q_POQUES, Q_NO_CALCULAT, Q_SENSE_CORR], dtype="u1")
    q.flag_meanings = ("llegenda_antiga_falten_dos_colors menys_del_90_per_cent_d_imatges "
                       "menys_del_50_per_cent_d_imatges_no_calculat sense_correccio_amb_estacions")
    nc.title = "PlujaCat – pluja diària a Catalunya (radar Meteocat + estacions XEMA)"
    nc.source = "https://github.com/albverfar123/plujacat"
    nc.institution = "Projecte independent. Dades de radar i estacions: Servei Meteorològic de Catalunya (Meteocat)"
    nc.calibracio_versio = cfg["versio"]
    nc.calibracio = ("taula v = a·v_original^b (config_calibracio.json) normalitzada per 240 imatges/dia + "
                     "correcció local IDW amb estacions XEMA (radi {radi_km} km, biaix mitjà com a pseudo-estació)"
                     .format(**cfg["correccio_estacions"]))
    nc.history = f"Generat {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC amb eines/serie_diaria.py"
    nc.Conventions = "CF-1.8"
    return nc


def main():
    global LLEGENDES
    ap = argparse.ArgumentParser()
    ap.add_argument("sortida")
    ap.add_argument("--paquets", default="")
    ap.add_argument("--des", default="20260101")
    ap.add_argument("--fins", default="29991231")
    a = ap.parse_args()

    LLEGENDES = _llegendes()
    cfg = calibracio_radar.carregar_config()
    fonts_git = blobs_radar(a.des, a.fins)
    paquets = {}
    if a.paquets:
        for p in glob.glob(os.path.join(a.paquets, "radar_*.nc")):
            dia = os.path.basename(p)[6:14]
            if a.des <= dia <= a.fins:
                paquets[dia] = p
    dies = sorted(set(fonts_git) | set(paquets))
    print(f"{len(dies)} dies ({dies[0]} → {dies[-1]}): {len(paquets)} de paquets, "
          f"{len(set(fonts_git) - set(paquets))} de l'historial de git")

    estacions = estacions_xema()
    lector = LectorBlobs()
    lat, lon = graella(fonts_git, paquets, lector)
    nc = crear_sortida(a.sortida, lat, lon, cfg)
    t0 = date(2026, 1, 1)
    buit = np.full((len(lat), len(lon)), np.nan, dtype="f4")

    for k, dia in enumerate(dies):
        acc = calibracio_radar.Acumulador(cfg)
        llegenda_antiga = False
        for moment, camp in imatges_dia(dia, fonts_git, paquets, lector):
            acc.afegir(camp)
            llegenda_antiga |= moment < INICI_LLEGENDA_ACTUAL
        q = Q_LLEGENDA if llegenda_antiga else 0
        data_iso = f"{dia[:4]}-{dia[4:6]}-{dia[6:]}"
        nc["time"][k] = (date(int(dia[:4]), int(dia[4:6]), int(dia[6:])) - t0).days
        nc["n_imatges"][k] = acc.n
        if acc.n < MIN_IMATGES_CALCUL:
            q |= Q_POQUES | Q_NO_CALCULAT | Q_SENSE_CORR
            for v in ("precipitacio", "precipitacio_radar", "precipitacio_original"):
                nc[v][k] = buit
            nc["n_estacions_correccio"][k], nc["biaix_mitja"][k] = 0, np.nan
            nc["qualitat"][k] = q
            print(f"{dia}: {acc.n} imatges → no calculat")
            continue
        if acc.n < MIN_IMATGES_COMPLET:
            q |= Q_POQUES
        original, calibrat = acc.resultat()
        est = estacions.get(data_iso)
        if est:
            final, info = calibracio_radar.corregir_amb_estacions(calibrat, lat, lon, est, cfg)
        else:
            final, info = calibrat.copy(), {"correccio": "sense_estacions"}
        if info.get("correccio") != "local":
            q |= Q_SENSE_CORR
        nc["precipitacio"][k] = final.astype("f4")
        nc["precipitacio_radar"][k] = calibrat.astype("f4")
        nc["precipitacio_original"][k] = original.astype("f4")
        nc["n_estacions_correccio"][k] = info.get("estacions_usades", 0)
        nc["biaix_mitja"][k] = info.get("biaix_mitja", np.nan) if info.get("correccio") == "local" else np.nan
        nc["qualitat"][k] = q
        print(f"{dia}: {acc.n} imatges, correcció {info.get('correccio')}"
              + (f" ({info.get('estacions_usades')} est., biaix {info.get('biaix_mitja')})" if info.get("correccio") == "local" else "")
              + (f", qualitat {q}" if q else ""))
        if k % 20 == 0:
            nc.sync()
    nc.close()
    print(f"✅ {a.sortida}: {len(dies)} dies, {os.path.getsize(a.sortida) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
