"""
Dades per validar i calibrar el radar amb les estacions XEMA.

Genera dos conjunts de fitxers a validacio/ (un CSV per mes, per no inflar l'historial de git):

1. parelles/parelles_YYYYMM.csv
   Per a cada dia i estació: pluja de l'estació i acumulat diari del radar al píxel de
   l'estació (i la mitjana i el màxim de la finestra 3x3 del voltant).
   Es calcula a partir dels acumulats diaris (acumulats_diaris/acumulat_*.nc).

2. recomptes/recomptes_YYYYMM.csv
   Per a cada dia i estació: quantes imatges de 6 min ha tingut el píxel de l'estació
   de cada classe de color del radar. Permet ajustar objectivament la taula
   LLEGENDA_RADAR, perquè l'acumulat diari és lineal en el valor de cada classe:
       acumulat = 0.1 * sum_k(n_k * valor_k)
   Només es pot calcular abans d'esborrar els fitxers de 6 min (dades_radar/), per això
   el crida daily_accumulation.py.

Ús manual (backfill de parelles):
    python validacio.py [directori_diaris]
"""
import os
import csv
import sys
import json
import glob
import numpy as np
import xarray as xr

VALIDACIO_DIR = "validacio"
PARELLES_DIR = os.path.join(VALIDACIO_DIR, "parelles")
RECOMPTES_DIR = os.path.join(VALIDACIO_DIR, "recomptes")
ESTACIONS_CACHE = os.path.join(VALIDACIO_DIR, "estacions_xema.json")

# Valors (mm/h) de les classes de color, tal com queden als NetCDF de dades_radar/
CLASSES = [0.01, 0.03, 0.05, 0.1, 0.2, 0.4, 0.8, 1.4, 2.0, 3.0, 4.0, 6.0, 9.0,
           14.0, 25.0, 40.0, 55.0, 70.0, 90.0, 120.0]

PARELLES_COLS = ["data", "codi", "nom", "lat", "lon", "fila", "col",
                 "pluja_estacio", "radar_px", "radar_3x3_mitjana", "radar_3x3_max", "n_imatges"]
RECOMPTES_COLS = (["data", "codi", "fila", "col", "n_imatges", "n_sense_eco"]
                  + [f"c_{v:g}" for v in CLASSES] + ["n_altres"])


# ---------------------------------------------------------------- utilitats

def pixel(lats, lons, lat, lon):
    """Índex (fila, col) del píxel més proper, o None si cau fora de la malla."""
    if not (min(lats) <= lat <= max(lats) and min(lons) <= lon <= max(lons)):
        return None
    return int(np.abs(lats - lat).argmin()), int(np.abs(lons - lon).argmin())


def _llegir_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _escriure_mes(dir_, prefix, cols, files_noves):
    """Afegeix files als CSV mensuals, substituint les que tinguin la mateixa (data, codi)."""
    os.makedirs(dir_, exist_ok=True)
    per_mes = {}
    for r in files_noves:
        per_mes.setdefault(r["data"][:7].replace("-", ""), []).append(r)
    for mes, noves in per_mes.items():
        path = os.path.join(dir_, f"{prefix}_{mes}.csv")
        claus_noves = {(r["data"], r["codi"]) for r in noves}
        existents = [r for r in _llegir_csv(path) if (r["data"], r["codi"]) not in claus_noves]
        totes = sorted(existents + noves, key=lambda r: (r["data"], r["codi"]))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(totes)


def dates_amb_parelles():
    """Conjunt de dates YYYYMMDD que ja tenen parelles guardades."""
    dates = set()
    for path in glob.glob(os.path.join(PARELLES_DIR, "parelles_*.csv")):
        for r in _llegir_csv(path):
            dates.add(r["data"].replace("-", ""))
    return dates


def desar_estacions(estacions_info):
    """Guarda la llista d'estacions per poder-la fer servir si l'API falla."""
    os.makedirs(VALIDACIO_DIR, exist_ok=True)
    with open(ESTACIONS_CACHE, "w", encoding="utf-8") as f:
        json.dump(estacions_info, f, ensure_ascii=False)


def carregar_estacions():
    if os.path.exists(ESTACIONS_CACHE):
        with open(ESTACIONS_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------- 1. parelles

def _n_imatges(daily_dir, dia, ds):
    if "files_count" in ds.attrs:
        return int(ds.attrs["files_count"])
    path = os.path.join(daily_dir, f"fonts_acumulat_{dia}.txt")
    if os.path.exists(path):
        for linia in open(path, encoding="utf-8"):
            if linia.startswith("Total fitxers processats:"):
                return int(linia.split(":")[1])
    return ""


def extreure_parelles(daily_dir="acumulats_diaris", nomes_noves=True):
    """Crea les parelles radar-estació per als dies amb acumulat diari i estacions."""
    ja_fetes = dates_amb_parelles() if nomes_noves else set()
    files = []
    dies = 0
    for nc in sorted(glob.glob(os.path.join(daily_dir, "acumulat_*.nc"))):
        dia = os.path.basename(nc)[9:17]
        js = os.path.join(daily_dir, f"estacions_{dia}.json")
        if dia in ja_fetes or not os.path.exists(js):
            continue
        with xr.open_dataset(nc) as ds:
            # Fem servir sempre l'acumulat amb la taula ORIGINAL (sense calibrar), perquè les
            # parelles siguin comparables al llarg del temps i no depenguin de la calibració
            var = "precipitacio_original" if "precipitacio_original" in ds else "precipitacio_acumulada"
            camp = ds[var].values
            lats, lons = ds["lat"].values, ds["lon"].values
            n_img = _n_imatges(daily_dir, dia, ds)
        with open(js, encoding="utf-8") as f:
            feats = json.load(f)["features"]
        data = f"{dia[:4]}-{dia[4:6]}-{dia[6:]}"
        for ft in feats:
            lon, lat = ft["geometry"]["coordinates"]
            ij = pixel(lats, lons, lat, lon)
            if ij is None:
                continue
            i, j = ij
            fin = camp[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]
            p = ft["properties"]
            files.append({
                "data": data, "codi": p["codi"], "nom": p["nom"],
                "lat": round(lat, 5), "lon": round(lon, 5), "fila": i, "col": j,
                "pluja_estacio": p["pluja"],
                "radar_px": round(float(camp[i, j]), 3),
                "radar_3x3_mitjana": round(float(np.nanmean(fin)), 3),
                "radar_3x3_max": round(float(np.nanmax(fin)), 3),
                "n_imatges": n_img,
            })
        dies += 1
    if files:
        _escriure_mes(PARELLES_DIR, "parelles", PARELLES_COLS, files)
    print(f"🔗 Parelles radar-estació: {dies} dies nous, {len(files)} files.")
    return dies


# ---------------------------------------------------------------- 2. recomptes de classes

def recomptes_classes(paths_radar, data, estacions_info):
    """Recompte de classes de color al píxel de cada estació per a un dia.
    estacions_info: {codi: {'nom', 'lat', 'lon'}}"""
    if not paths_radar or not estacions_info:
        return 0
    with xr.open_dataset(paths_radar[0]) as ds:
        lats, lons = ds["lat"].values, ds["lon"].values

    punts = {}
    for codi, e in estacions_info.items():
        ij = pixel(lats, lons, e["lat"], e["lon"])
        if ij is not None:
            punts[codi] = ij
    if not punts:
        return 0
    codis = list(punts)
    files_i = np.array([punts[c][0] for c in codis])
    cols_j = np.array([punts[c][1] for c in codis])

    classes = np.array(CLASSES)
    n_cls = len(classes)
    # recompte[estació, classe]; columnes extra: sense eco, altres
    recompte = np.zeros((len(codis), n_cls + 2), dtype=int)
    n_ok = 0
    for path in paths_radar:
        try:
            with xr.open_dataset(path) as ds:
                v = ds["precipitacio"].values[files_i, cols_j]
        except Exception as e:
            print(f"⚠️ Recomptes: no s'ha pogut llegir {path}: {e}")
            continue
        n_ok += 1
        nan = np.isnan(v)
        recompte[nan, n_cls] += 1
        dif = np.abs(v[~nan, None] - classes[None, :])
        k = dif.argmin(axis=1)
        exacte = dif[np.arange(len(k)), k] < 1e-3
        idx = np.where(~nan)[0]
        np.add.at(recompte, (idx[exacte], k[exacte]), 1)
        np.add.at(recompte, (idx[~exacte], n_cls + 1), 1)

    files = []
    for e, codi in enumerate(codis):
        r = {"data": data, "codi": codi, "fila": int(files_i[e]), "col": int(cols_j[e]),
             "n_imatges": n_ok, "n_sense_eco": int(recompte[e, n_cls]),
             "n_altres": int(recompte[e, n_cls + 1])}
        for k, val in enumerate(CLASSES):
            r[f"c_{val:g}"] = int(recompte[e, k])
        files.append(r)
    _escriure_mes(RECOMPTES_DIR, "recomptes", RECOMPTES_COLS, files)
    print(f"🎨 Recomptes de classes guardats: {len(files)} estacions, {n_ok} imatges ({data}).")
    return len(files)


if __name__ == "__main__":
    extreure_parelles(sys.argv[1] if len(sys.argv) > 1 else "acumulats_diaris")
