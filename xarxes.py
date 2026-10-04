"""
Altres xarxes d'estacions de pluja (a més de la XEMA): ACA i AEMET.

Per ara serveixen per VALIDAR el radar (i per mostrar-les al visor). No entren a la
correcció diària, que continua fent servir només la XEMA.

ACA (Agència Catalana de l'Aigua, plataforma Sentilo)
  - ~60 pluviòmetres; un valor cada 5 min = intensitat mitjana en mm/h → mm = Σ v · 5/60.
  - Hora UTC (tot i que el catàleg diu CET). L'API només guarda ~2–4 mesos.
  - Els pluviòmetres a < 1 km d'una estació XEMA donen els mateixos valors que la XEMA
    (és el mateix aparell): es marquen com a duplicat_xema.

AEMET (OpenData, observació convencional)
  - `prec` = mm de l'hora anterior a `fint` (UTC). L'API només dona les últimes ~12 h, per això
    el workflow del radar en desa una còpia cada 3 h a la Release del dia (aemet_AAAAMMDDTHH.json).

Dia = 00–24 UTC, igual que el radar i la XEMA.

Fitxers:
  validacio/xarxes/diari/{aca,aemet}_diari_AAAAMM.csv   pluja diària per estació
  validacio/parelles_xarxes/parelles_xarxes_AAAAMM.csv  parelles amb el radar (original, taula, final)
  acumulats_diaris/xarxes_AAAAMMDD.json                  GeoJSON per al visor
  arxiu_radar/aemet_horari_AAAAMMDD.csv                  dades horàries AEMET del dia (→ Release mensual)

Ús:
  python xarxes.py recollir-aemet FITXER.json        (workflow del radar)
  python xarxes.py diari [DIR_AEMET]                 (workflow diari)
  python xarxes.py backfill-aca AAAA-MM-DD AAAA-MM-DD
  python xarxes.py parelles
"""
import os
import sys
import csv
import json
import glob
import math
import time
from datetime import datetime, date, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import requests

ARREL = os.path.dirname(os.path.abspath(__file__))
XARXES_DIR = os.path.join(ARREL, "validacio", "xarxes")
DIARI_DIR = os.path.join(XARXES_DIR, "diari")
PARELLES_DIR = os.path.join(ARREL, "validacio", "parelles_xarxes")
DAILY_DIR = os.path.join(ARREL, "acumulats_diaris")
ARXIU_DIR = os.path.join(ARREL, "arxiu_radar")
XEMA_CACHE = os.path.join(ARREL, "validacio", "estacions_xema.json")

BBOX = (40.45, 42.95, 0.1, 3.4)
UA = {"User-Agent": "PlujaCat (github.com/albverfar123/plujacat)"}
TIMEOUT = 60
DIST_DUPLICAT_KM = 1.0

ACA_API = "https://aplicacions.aca.gencat.cat/sdim2/apirest"
ACA_PROVIDER = "PLUVIOMETREACA-EST"
ACA_CACHE = os.path.join(XARXES_DIR, "aca_sensors.json")
ACA_OBS_DIA = 288
ACA_MIN_COMPLETESA = 0.9

AEMET_API = "https://opendata.aemet.es/opendata/api"
AEMET_MIN_HORES = 23

DIARI_COLS = ["data", "xarxa", "codi", "nom", "lat", "lon", "pluja", "n_obs",
              "xema_propera", "dist_xema_km", "duplicat_xema"]
PARELLES_COLS = ["data", "xarxa", "codi", "nom", "lat", "lon", "fila", "col", "pluja_estacio",
                 "radar_original_px", "radar_taula_px", "radar_final_px", "radar_final_3x3_mitjana",
                 "correccio", "xema_propera", "dist_xema_km", "duplicat_xema"]


# ===================================================================== utilitats

def dist_km(la1, lo1, la2, lo2):
    p = math.pi / 180
    a = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def dins_bbox(lat, lon):
    return lat is not None and lon is not None and BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]


def xema_propera(lat, lon, _cache={}):
    if "x" not in _cache:
        try:
            with open(XEMA_CACHE, encoding="utf-8") as f:
                _cache["x"] = json.load(f)
        except OSError:
            _cache["x"] = {}
    millor = ("", None)
    for codi, e in _cache["x"].items():
        d = dist_km(lat, lon, e["lat"], e["lon"])
        if millor[1] is None or d < millor[1]:
            millor = (codi, d)
    return millor[0], (round(millor[1], 2) if millor[1] is not None else "")


def limits_dia(dia):
    d0 = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)
    return d0, d0 + timedelta(days=1)


def _llegir_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def escriure_mes(dir_, prefix, cols, files_noves):
    """Afegeix files als CSV mensuals, substituint les que tinguin la mateixa (data, codi)."""
    os.makedirs(dir_, exist_ok=True)
    per_mes = {}
    for r in files_noves:
        per_mes.setdefault(r["data"][:7].replace("-", ""), []).append(r)
    for mes, noves in per_mes.items():
        path = os.path.join(dir_, f"{prefix}_{mes}.csv")
        claus = {(r["data"], r["codi"]) for r in noves}
        totes = [r for r in _llegir_csv(path) if (r["data"], r["codi"]) not in claus] + noves
        totes.sort(key=lambda r: (r["data"], r["codi"]))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(totes)


def llegir_diari(xarxa, dia=None):
    """Files del CSV diari d'una xarxa (d'un dia concret o totes)."""
    if dia:
        files = _llegir_csv(os.path.join(DIARI_DIR, f"{xarxa}_diari_{dia:%Y%m}.csv"))
        return [r for r in files if r["data"] == dia.isoformat()]
    files = []
    for p in sorted(glob.glob(os.path.join(DIARI_DIR, f"{xarxa}_diari_*.csv"))):
        files += _llegir_csv(p)
    return files


def dies_amb_dades(xarxa):
    return {r["data"] for r in llegir_diari(xarxa)}


# ===================================================================== ACA

def _aca_get(ruta, params=None, intents=3):
    for i in range(intents):
        try:
            r = requests.get(f"{ACA_API}/{ruta}", params=params, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == intents - 1:
                raise
            time.sleep(5 * (i + 1))


def aca_sensors():
    """Pluviòmetres de l'ACA (catàleg; si l'API falla, la còpia desada)."""
    try:
        cat = _aca_get("catalog")
        sensors = []
        for p in cat.get("providers", []):
            for s in p.get("sensors", []):
                if p.get("provider") != ACA_PROVIDER or s.get("componentType") != "pluviometre":
                    continue
                try:
                    lat, lon = (float(x) for x in str(s["location"]).split(",")[0].split()[:2])
                except (KeyError, ValueError):
                    continue
                codi_x, d = xema_propera(lat, lon)
                sensors.append({
                    "codi": s["sensor"], "component": s.get("component"), "nom": s.get("componentDesc"),
                    "lat": round(lat, 5), "lon": round(lon, 5), "unitat": s.get("unit"),
                    "estat": s.get("state"), "xema_propera": codi_x, "dist_xema_km": d,
                    "duplicat_xema": bool(d != "" and d < DIST_DUPLICAT_KM),
                })
        if sensors:
            os.makedirs(XARXES_DIR, exist_ok=True)
            with open(ACA_CACHE, "w", encoding="utf-8") as f:
                json.dump(sensors, f, ensure_ascii=False, indent=1)
            return sensors
    except Exception as e:
        print(f"⚠️ ACA: catàleg no disponible ({e}); faig servir la còpia desada")
    if os.path.exists(ACA_CACHE):
        with open(ACA_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return []


def aca_obs(sensor, ini, fi):
    """Observacions (time_s, valor) amb ini < t <= fi. Pagina perquè l'API en dona 200 com a màxim."""
    fmt = "%d/%m/%YT%H:%M:%S"
    obs, to = {}, fi
    for _ in range(10):
        d = _aca_get(f"data/{ACA_PROVIDER}/{sensor}",
                     {"from": ini.strftime(fmt), "to": to.strftime(fmt), "limit": 200})
        lot = d.get("observations", [])
        for o in lot:
            obs[int(o["time"]) // 1000] = o["value"]
        if len(lot) < 200:
            break
        mes_antic = min(int(o["time"]) for o in lot) // 1000
        if mes_antic <= ini.timestamp():
            break
        to = datetime.fromtimestamp(mes_antic - 1, timezone.utc)
        time.sleep(0.2)
    t0, t1 = ini.timestamp(), fi.timestamp()
    return sorted((t, v) for t, v in obs.items() if t0 < t <= t1)


def aca_dia_sensor(s, dia):
    d0, d1 = limits_dia(dia)
    try:
        obs = aca_obs(s["codi"], d0, d1)
    except Exception as e:
        print(f"⚠️ ACA {s['codi']} {dia}: {e}")
        return None
    if not obs:
        return None
    vals = []
    for _, v in obs:
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            pass
    complet = len(vals) >= ACA_MIN_COMPLETESA * ACA_OBS_DIA
    return {"data": dia.isoformat(), "xarxa": "ACA", "codi": s["codi"], "nom": s["nom"],
            "lat": s["lat"], "lon": s["lon"],
            "pluja": round(sum(vals) * 5 / 60, 1) if complet else "",
            "n_obs": len(vals), "xema_propera": s["xema_propera"],
            "dist_xema_km": s["dist_xema_km"], "duplicat_xema": int(bool(s["duplicat_xema"]))}


def aca_dia(dia, sensors, workers=4):
    with ThreadPoolExecutor(workers) as ex:
        files = [r for r in ex.map(lambda s: aca_dia_sensor(s, dia), sensors) if r]
    return files


def backfill_aca(des, fins):
    sensors = aca_sensors()
    print(f"ACA: {len(sensors)} pluviòmetres; recuperant {des} → {fins}")
    dia, buits = des, 0
    while dia <= fins:
        files = aca_dia(dia, sensors)
        if files:
            escriure_mes(DIARI_DIR, "aca_diari", DIARI_COLS, files)
            ok = sum(1 for f in files if f["pluja"] != "")
            print(f"  {dia}: {len(files)} pluviòmetres amb dades ({ok} complets)")
        else:
            buits += 1
            print(f"  {dia}: sense dades")
        dia += timedelta(days=1)
    print(f"Dies sense cap dada: {buits}")


# ===================================================================== AEMET

def aemet_get(ruta, clau, intents=4):
    url = f"{AEMET_API}/{ruta}"
    for i in range(intents):
        try:
            r = requests.get(url, headers={"api_key": clau, **UA}, timeout=TIMEOUT)
            cap = r.json() if r.status_code == 200 else {"estado": r.status_code}
            if cap.get("estado") == 200 and cap.get("datos"):
                d = requests.get(cap["datos"], headers=UA, timeout=TIMEOUT)
                d.raise_for_status()
                try:
                    txt = d.content.decode("utf-8")
                except UnicodeDecodeError:
                    txt = d.content.decode("latin-1")
                return json.loads(txt)
            print(f"⚠️ AEMET {ruta}: {cap}")
        except Exception as e:
            print(f"⚠️ AEMET {ruta}: {e}")
        time.sleep(10 * (i + 1))
    raise RuntimeError(f"AEMET {ruta}: no s'ha pogut obtenir")


def recollir_aemet(path):
    """Desa les observacions horàries de Catalunya de les últimes ~12 h."""
    clau = os.environ.get("AEMET_API_KEY", "").strip()
    if not clau:
        raise SystemExit("❌ Falta AEMET_API_KEY")
    obs = aemet_get("observacion/convencional/todas", clau)
    camps = ("idema", "ubi", "lat", "lon", "alt", "fint", "prec")
    cat = [{k: o.get(k) for k in camps} for o in obs if dins_bbox(o.get("lat"), o.get("lon"))]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, separators=(",", ":"))
    hores = sorted({o["fint"] for o in cat})
    print(f"✅ AEMET: {len(cat)} registres, {len({o['idema'] for o in cat})} estacions, "
          f"{hores[0] if hores else '-'} → {hores[-1] if hores else '-'}")


def _fint(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def aemet_dia(dia, dir_json):
    """Totals diaris (00–24 UTC) a partir de les còpies aemet_*.json. Retorna (files, horari)."""
    d0, d1 = limits_dia(dia)
    registres = {}
    for p in sorted(glob.glob(os.path.join(dir_json, "aemet_*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                for o in json.load(f):
                    if o.get("fint") and o.get("idema"):
                        registres[(o["idema"], o["fint"])] = o
        except Exception as e:
            print(f"⚠️ {p}: {e}")
    horari = [o for (_, fi), o in registres.items() if d0 < _fint(fi) <= d1]
    per_est = {}
    for o in horari:
        per_est.setdefault(o["idema"], []).append(o)
    files = []
    for idema, obs in sorted(per_est.items()):
        precs = [o["prec"] for o in obs if isinstance(o.get("prec"), (int, float))]
        if not precs:
            continue  # estació sense pluviòmetre
        lat, lon = obs[0]["lat"], obs[0]["lon"]
        codi_x, dx = xema_propera(lat, lon)
        files.append({"data": dia.isoformat(), "xarxa": "AEMET", "codi": idema, "nom": obs[0].get("ubi"),
                      "lat": lat, "lon": lon,
                      "pluja": round(sum(precs), 1) if len(precs) >= AEMET_MIN_HORES else "",
                      "n_obs": len(precs), "xema_propera": codi_x, "dist_xema_km": dx,
                      "duplicat_xema": ""})
    return files, sorted(horari, key=lambda o: (o["idema"], o["fint"]))


def desar_horari_aemet(dia, horari):
    if not horari:
        return
    os.makedirs(ARXIU_DIR, exist_ok=True)
    path = os.path.join(ARXIU_DIR, f"aemet_horari_{dia:%Y%m%d}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["idema", "fint", "prec", "lat", "lon", "alt", "ubi"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(horari)


# ===================================================================== parelles i visor

def parelles(nomes_noves=True, forcar=()):
    """Parelles estació–radar per als dies amb acumulat diari i dades d'altres xarxes.
    forcar: dies (date) que cal tornar a calcular encara que ja tinguin parelles."""
    import numpy as np
    import xarray as xr
    from validacio import pixel

    fetes = set()
    if nomes_noves:
        for p in glob.glob(os.path.join(PARELLES_DIR, "parelles_xarxes_*.csv")):
            fetes |= {(r["data"], r["xarxa"]) for r in _llegir_csv(p)}
        fetes = {(d, x) for d, x in fetes if d not in {f.isoformat() for f in forcar}}
    per_dia = {}
    for xarxa in ("aca", "aemet"):
        for r in llegir_diari(xarxa):
            if r["pluja"] != "" and (r["data"], r["xarxa"]) not in fetes:
                per_dia.setdefault(r["data"], []).append(r)
    noves, dies = [], 0
    for data, files in sorted(per_dia.items()):
        nc = os.path.join(DAILY_DIR, f"acumulat_{data.replace('-', '')}.nc")
        if not os.path.exists(nc):
            continue
        with xr.open_dataset(nc) as ds:
            final = ds["precipitacio_acumulada"].values
            taula = ds["precipitacio_radar"].values if "precipitacio_radar" in ds else None
            orig = ds["precipitacio_original"].values if "precipitacio_original" in ds else None
            lats, lons = ds["lat"].values, ds["lon"].values
            correccio = ds.attrs.get("correccio", "")
        for r in files:
            ij = pixel(lats, lons, float(r["lat"]), float(r["lon"]))
            if ij is None:
                continue
            i, j = ij
            fin = final[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]
            noves.append({**{k: r[k] for k in ("data", "xarxa", "codi", "nom", "lat", "lon", "xema_propera",
                                               "dist_xema_km", "duplicat_xema")},
                          "fila": i, "col": j, "pluja_estacio": r["pluja"],
                          "radar_original_px": round(float(orig[i, j]), 2) if orig is not None else "",
                          "radar_taula_px": round(float(taula[i, j]), 2) if taula is not None else "",
                          "radar_final_px": round(float(final[i, j]), 2),
                          "radar_final_3x3_mitjana": round(float(np.nanmean(fin)), 2),
                          "correccio": correccio})
        dies += 1
    if noves:
        escriure_mes(PARELLES_DIR, "parelles_xarxes", PARELLES_COLS, noves)
    print(f"🔗 Parelles d'altres xarxes: {dies} dies, {len(noves)} files")


def geojson_visor(dia):
    """acumulats_diaris/xarxes_AAAAMMDD.json amb les estacions ACA i AEMET del dia."""
    feats = []
    for xarxa in ("aca", "aemet"):
        for r in llegir_diari(xarxa, dia):
            if r["pluja"] == "":
                continue
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                          "properties": {"xarxa": r["xarxa"], "codi": r["codi"], "nom": r["nom"],
                                         "pluja": float(r["pluja"]),
                                         "duplicat_xema": r["duplicat_xema"] == "1"}})
    if not feats or not os.path.isdir(DAILY_DIR):
        return
    with open(os.path.join(DAILY_DIR, f"xarxes_{dia:%Y%m%d}.json"), "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)


# ===================================================================== execució diària

def diari(dir_aemet="dades_aemet"):
    avui = datetime.now(timezone.utc).date()
    actualitzats = set()

    # ACA: ahir i els dies recents que encara no tinguin dades (l'API guarda uns quants mesos)
    try:
        sensors = aca_sensors()
        fets = dies_amb_dades("aca")
        for i in range(1, 15):
            dia = avui - timedelta(days=i)
            if i > 1 and dia.isoformat() in fets:
                continue
            files = aca_dia(dia, sensors)
            if files:
                escriure_mes(DIARI_DIR, "aca_diari", DIARI_COLS, files)
                actualitzats.add(dia)
                print(f"💧 ACA {dia}: {sum(1 for f in files if f['pluja'] != '')}/{len(sensors)} pluviòmetres complets")
    except Exception as e:
        print(f"⚠️ ACA: {e}")

    # AEMET: dies anteriors a avui amb còpies horàries descarregades de les Releases
    try:
        dies = set()
        for p in glob.glob(os.path.join(dir_aemet, "aemet_*.json")):
            try:
                dies.add(datetime.strptime(os.path.basename(p)[6:14], "%Y%m%d").date())
            except ValueError:
                pass
        # una còpia del dia D+1 pot completar el dia D
        candidats = {d for d in dies if d < avui} | {d - timedelta(days=1) for d in dies if d <= avui}
        fets = dies_amb_dades("aemet")
        for dia in sorted(candidats):
            files, horari = aemet_dia(dia, dir_aemet)
            if not files:
                continue
            complets = sum(1 for f in files if f["pluja"] != "")
            previs = [r for r in llegir_diari("aemet", dia) if r["pluja"] != ""]
            if dia.isoformat() in fets and complets <= len(previs):
                continue  # ja el teníem igual o més complet
            escriure_mes(DIARI_DIR, "aemet_diari", DIARI_COLS, files)
            desar_horari_aemet(dia, horari)
            actualitzats.add(dia)
            print(f"🌦️ AEMET {dia}: {complets}/{len(files)} estacions completes (≥ {AEMET_MIN_HORES} h)")
    except Exception as e:
        print(f"⚠️ AEMET: {e}")

    for dia in sorted(actualitzats):
        geojson_visor(dia)
    try:
        parelles(forcar=actualitzats)
    except Exception as e:
        print(f"⚠️ Parelles d'altres xarxes: {e}")


def main(args):
    if not args:
        print(__doc__)
        return 1
    ordre = args[0]
    if ordre == "recollir-aemet":
        recollir_aemet(args[1])
    elif ordre == "diari":
        diari(args[1] if len(args) > 1 else "dades_aemet")
    elif ordre == "backfill-aca":
        des = date.fromisoformat(args[1])
        fins = date.fromisoformat(args[2]) if len(args) > 2 else datetime.now(timezone.utc).date() - timedelta(days=1)
        backfill_aca(des, fins)
        dia = des
        while dia <= fins:
            geojson_visor(dia)
            dia += timedelta(days=1)
        parelles()
    elif ordre == "parelles":
        parelles(nomes_noves=False)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
