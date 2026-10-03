"""
Backfill (una sola vegada) dels recomptes de classes de color per estació i dia,
llegint els fitxers de 6 min de dades_radar/ directament de l'historial de git.

Només es fan servir fitxers des del 2026-03-05: la taula LLEGENDA_RADAR de
radar_to_nc.py no ha canviat des del 2026-03-04 12:39 UTC, de manera que tots els
valors corresponen a les classes actuals.

Ús (des de l'arrel del repo, amb historial complet):
    python eines/backfill_recomptes.py estacions_xema.json 20260305 20261002
"""
import os
import sys
import json
import subprocess
from collections import defaultdict

import numpy as np
import netCDF4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import validacio  # noqa: E402


def blobs_radar(desde, fins):
    """{dia: [(nom_fitxer, blob_sha)]} dels fitxers de radar afegits a l'historial."""
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--raw", "--no-renames", "--no-abbrev",
         "--format=", "--", "dades_radar"],
        capture_output=True, text=True, check=True).stdout
    per_dia = defaultdict(dict)
    for linia in out.splitlines():
        if not linia.startswith(":"):
            continue
        meta, path = linia.split("\t")
        sha = meta.split()[3]
        nom = os.path.basename(path)
        if not (nom.startswith("radar_") and nom.endswith(".nc")):
            continue
        dia = nom[6:14]
        if desde <= dia <= fins:
            per_dia[dia][nom] = sha
    return {d: sorted(v.items()) for d, v in sorted(per_dia.items())}


class LectorBlobs:
    def __init__(self):
        self.p = subprocess.Popen(["git", "cat-file", "--batch"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def llegir(self, sha):
        self.p.stdin.write((sha + "\n").encode())
        self.p.stdin.flush()
        cap = self.p.stdout.readline().split()
        mida = int(cap[2])
        dades = self.p.stdout.read(mida)
        self.p.stdout.read(1)
        return dades


def main(path_estacions, desde, fins):
    with open(path_estacions, encoding="utf-8") as f:
        estacions = json.load(f)
    dies = blobs_radar(desde, fins)
    print(f"{len(dies)} dies, {sum(len(v) for v in dies.values())} fitxers")

    lector = LectorBlobs()
    classes = np.array(validacio.CLASSES)
    n_cls = len(classes)
    codis, fi, cj, grid = None, None, None, None

    for dia, fitxers in dies.items():
        recompte = None
        n_ok = 0
        for nom, sha in fitxers:
            try:
                ds = netCDF4.Dataset("mem", memory=lector.llegir(sha))
                if grid is None:
                    lats, lons = ds["lat"][:].data, ds["lon"][:].data
                    grid = (lats.shape, float(lats[0]), float(lons[0]))
                    punts = {c: validacio.pixel(lats, lons, e["lat"], e["lon"]) for c, e in estacions.items()}
                    codis = [c for c, ij in punts.items() if ij is not None]
                    fi = np.array([punts[c][0] for c in codis])
                    cj = np.array([punts[c][1] for c in codis])
                elif (ds["lat"].shape, float(ds["lat"][0]), float(ds["lon"][0])) != grid:
                    print(f"⚠️ {nom}: malla diferent, s'ignora")
                    ds.close()
                    continue
                v = np.ma.filled(ds["precipitacio"][:].astype("f8"), np.nan)[fi, cj]
                ds.close()
            except Exception as e:
                print(f"⚠️ {nom}: {e}")
                continue
            if recompte is None:
                recompte = np.zeros((len(codis), n_cls + 2), dtype=int)
            n_ok += 1
            nan = np.isnan(v)
            recompte[nan, n_cls] += 1
            dif = np.abs(v[~nan, None] - classes[None, :])
            k = dif.argmin(axis=1)
            exacte = dif[np.arange(len(k)), k] < 1e-3
            idx = np.where(~nan)[0]
            np.add.at(recompte, (idx[exacte], k[exacte]), 1)
            np.add.at(recompte, (idx[~exacte], n_cls + 1), 1)

        if recompte is None:
            continue
        data = f"{dia[:4]}-{dia[4:6]}-{dia[6:]}"
        files = []
        for e, codi in enumerate(codis):
            r = {"data": data, "codi": codi, "fila": int(fi[e]), "col": int(cj[e]),
                 "n_imatges": n_ok, "n_sense_eco": int(recompte[e, n_cls]),
                 "n_altres": int(recompte[e, n_cls + 1])}
            for k, val in enumerate(validacio.CLASSES):
                r[f"c_{val:g}"] = int(recompte[e, k])
            files.append(r)
        validacio._escriure_mes(validacio.RECOMPTES_DIR, "recomptes", validacio.RECOMPTES_COLS, files)
        print(f"{data}: {n_ok} imatges, altres={int(recompte[:, n_cls + 1].sum())}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
