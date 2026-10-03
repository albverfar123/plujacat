"""
Extreu la sèrie HORÀRIA de pluja radar al píxel de cada estació XEMA, llegint els
fitxers de 6 min de dades_radar/ de l'historial de git.

Serveix per comprovar a quina franja horària correspon el "dia" de la XEMA
(00-24 UTC, 07-07, etc.) comparant-la amb acumulats de radar desplaçats.

Ús (des de l'arrel del repo, amb historial complet):
    python eines/extreure_horari.py validacio/estacions_xema.json 20260305 20261002 analisi/dades/radar_horari_estacions.csv.gz

Sortida: CSV amb columnes hora_utc, codi, radar_mm, n_imatges (només hores amb radar > 0
o amb alguna imatge; les hores sense dades no apareixen).
"""
import os
import sys
import json
from collections import defaultdict

import numpy as np
import pandas as pd
import netCDF4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validacio  # noqa: E402
from backfill_recomptes import blobs_radar, LectorBlobs  # noqa: E402

FACTOR = 0.1  # mm/h -> mm per imatge de 6 min


def main(path_estacions, desde, fins, sortida):
    with open(path_estacions, encoding="utf-8") as f:
        estacions = json.load(f)
    dies = blobs_radar(desde, fins)
    lector = LectorBlobs()
    codis = fi = cj = None

    suma = defaultdict(float)       # (hora, idx_estacio) -> mm
    n_hora = defaultdict(int)       # hora -> nº imatges
    for dia, fitxers in dies.items():
        for nom, sha in fitxers:
            hora = pd.Timestamp(f"{nom[6:10]}-{nom[10:12]}-{nom[12:14]} {nom[15:17]}:00")
            try:
                ds = netCDF4.Dataset("mem", memory=lector.llegir(sha))
                if codis is None:
                    lats, lons = ds["lat"][:].data, ds["lon"][:].data
                    punts = {c: validacio.pixel(lats, lons, e["lat"], e["lon"]) for c, e in estacions.items()}
                    codis = [c for c, ij in punts.items() if ij is not None]
                    fi = np.array([punts[c][0] for c in codis])
                    cj = np.array([punts[c][1] for c in codis])
                v = np.ma.filled(ds["precipitacio"][:].astype("f8"), np.nan)[fi, cj]
                ds.close()
            except Exception as e:
                print(f"⚠️ {nom}: {e}")
                continue
            n_hora[hora] += 1
            for k in np.where(np.nan_to_num(v) > 0)[0]:
                suma[(hora, k)] += v[k] * FACTOR
        print(dia, flush=True)

    files = [(h, codis[k], round(mm, 3), n_hora[h]) for (h, k), mm in suma.items()]
    df = pd.DataFrame(files, columns=["hora_utc", "codi", "radar_mm", "n_imatges"]).sort_values(["hora_utc", "codi"])
    hores = pd.DataFrame(sorted(n_hora.items()), columns=["hora_utc", "n_imatges"])
    os.makedirs(os.path.dirname(sortida), exist_ok=True)
    df.to_csv(sortida, index=False)
    hores.to_csv(sortida.replace(".csv", "_imatges.csv"), index=False)
    print(f"✅ {len(df)} files, {len(hores)} hores -> {sortida}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
