"""
Torna a generar els acumulats diaris amb la calibració actual (config_calibracio.json),
llegint els fitxers de radar de 6 min de l'historial de git i les estacions XEMA desades
a acumulats_diaris/estacions_AAAAMMDD.json.

Ús (des de l'arrel del repo, amb historial complet):
    python eines/reprocessar_diaris.py 20260801 20261002
"""
import os
import sys
import json

import numpy as np
import netCDF4

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ARREL)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ARREL)

import calibracio_radar  # noqa: E402
import daily_accumulation as D  # noqa: E402
from backfill_recomptes import blobs_radar, LectorBlobs  # noqa: E402


def estacions_locals(dia):
    path = os.path.join(D.DAILY_DIR, f"estacions_{dia}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    return [{"codi": ft["properties"]["codi"], "nom": ft["properties"]["nom"],
             "lon": ft["geometry"]["coordinates"][0], "lat": ft["geometry"]["coordinates"][1],
             "pluja": ft["properties"]["pluja"]} for ft in feats]


def main(desde, fins):
    lector = LectorBlobs()
    for dia, fitxers in blobs_radar(desde, fins).items():
        acc = calibracio_radar.Acumulador(D.CFG_CALIBRACIO)
        lat = lon = None
        noms = []
        for nom, sha in fitxers:
            try:
                ds = netCDF4.Dataset("mem", memory=lector.llegir(sha))
                if lat is None:
                    lat, lon = ds["lat"][:].data, ds["lon"][:].data
                acc.afegir(np.ma.filled(ds["precipitacio"][:].astype("f8"), np.nan))
                ds.close()
                noms.append(nom)
            except Exception as e:
                print(f"⚠️ {nom}: {e}")
        if acc.n == 0:
            continue
        original, calibrat = acc.resultat()
        D.desar_acumulat(dia, lat, lon, original, calibrat, acc.n, noms, estacions_locals(dia))


if __name__ == "__main__":
    main(*sys.argv[1:3])
