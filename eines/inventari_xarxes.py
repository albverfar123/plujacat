"""
Inventari d'estacions de pluja d'altres xarxes (AEMET i ACA) a Catalunya.

És un script exploratori (pas 1 de la incorporació de més estacions): baixa la llista
d'estacions, una mostra de dades i les metadades de cada API, i ho desa a validacio/xarxes/
perquè es pugui analitzar (notebook analisi/04). No toca res del pipeline operatiu.

Ús (des de l'arrel del repo, normalment des del workflow inventari_xarxes.yml):
    AEMET_API_KEY=... python eines/inventari_xarxes.py
"""
import os
import re
import csv
import sys
import json
import time
import math
from datetime import datetime, timedelta, timezone

import requests

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ARREL, "validacio", "xarxes")
XEMA = os.path.join(ARREL, "validacio", "estacions_xema.json")

# Caixa aproximada de Catalunya (amb marge) i de la malla del radar
BBOX = (40.45, 42.95, 0.1, 3.4)  # lat_min, lat_max, lon_min, lon_max
PROVINCIES_CAT = {"BARCELONA", "GIRONA", "LLEIDA", "TARRAGONA"}
TIMEOUT = 60
UA = {"User-Agent": "PlujaCat (github.com/albverfar123/plujacat)"}

resum = []  # línies del resum_inventari.md


def log(msg=""):
    print(msg)
    resum.append(msg)


def desar_json(nom, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, nom), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def desar_text(nom, text):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, nom), "w", encoding="utf-8") as f:
        f.write(text)


def desar_csv(nom, files):
    if not files:
        return
    os.makedirs(OUT, exist_ok=True)
    cols = list(files[0].keys())
    for r in files[1:]:
        cols += [c for c in r if c not in cols]
    with open(os.path.join(OUT, nom), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(files)


def dins_bbox(lat, lon):
    return lat is not None and lon is not None and BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]


def dist_km(la1, lo1, la2, lo2):
    p = math.pi / 180
    a = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def carregar_xema():
    if not os.path.exists(XEMA):
        return {}
    with open(XEMA, encoding="utf-8") as f:
        return json.load(f)


def xema_mes_propera(lat, lon, xema):
    millor = (None, None)
    for codi, e in xema.items():
        d = dist_km(lat, lon, e["lat"], e["lon"])
        if millor[1] is None or d < millor[1]:
            millor = (codi, d)
    return millor


def decodificar(resp):
    """AEMET de vegades serveix ISO-8859-15 sense declarar-ho."""
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.content.decode("latin-1")


# ===================================================================== AEMET

AEMET_BASE = "https://opendata.aemet.es/opendata/api"


def aemet(ruta, clau, intents=4):
    """Crida en dos passos d'AEMET OpenData. Retorna (dades, metadades) o llença excepció."""
    url = f"{AEMET_BASE}/{ruta.lstrip('/')}"
    for i in range(intents):
        r = requests.get(url, headers={"api_key": clau, **UA}, timeout=TIMEOUT)
        if r.status_code == 429:
            time.sleep(15 * (i + 1))
            continue
        r.raise_for_status()
        cap = r.json()
        if cap.get("estado") == 429:
            time.sleep(15 * (i + 1))
            continue
        if cap.get("estado") != 200 or "datos" not in cap:
            raise RuntimeError(f"{ruta}: {cap}")
        break
    else:
        raise RuntimeError(f"{ruta}: massa peticions (429)")

    dades = json.loads(decodificar(requests.get(cap["datos"], headers=UA, timeout=TIMEOUT)))
    meta = None
    if cap.get("metadatos"):
        try:
            meta = json.loads(decodificar(requests.get(cap["metadatos"], headers=UA, timeout=TIMEOUT)))
        except Exception as e:  # les metadades no són imprescindibles
            meta = {"error": str(e)}
    return dades, meta


def coord_aemet(s):
    """'413512N' / '021108E' (GGMMSS + hemisferi) → graus decimals."""
    if s is None:
        return None
    m = re.fullmatch(r"\s*(\d{2,3})(\d{2})(\d{2})([NSEW])\s*", str(s))
    if not m:
        try:
            return float(str(s).replace(",", "."))
        except ValueError:
            return None
    g, mi, se, h = m.groups()
    v = int(g) + int(mi) / 60 + int(se) / 3600
    return -v if h in "SW" else v


def num_aemet(v):
    """'1,2' → 1.2 ; 'Ip' (inapreciable) → 0.0 ; altres → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.lower() == "ip":
        return 0.0
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def inventari_aemet(clau, xema):
    log("## AEMET")
    estacions = {}

    # 1. Inventari d'estacions climatològiques
    try:
        inv, meta = aemet("valores/climatologicos/inventarioestaciones/todasestaciones", clau)
        desar_json("aemet_metadades_inventari.json", meta)
        n_total = len(inv)
        for e in inv:
            if str(e.get("provincia", "")).upper() not in PROVINCIES_CAT:
                continue
            lat, lon = coord_aemet(e.get("latitud")), coord_aemet(e.get("longitud"))
            estacions[e["indicativo"]] = {
                "indicativo": e["indicativo"], "nom": e.get("nombre"), "provincia": e.get("provincia"),
                "lat": round(lat, 5) if lat else None, "lon": round(lon, 5) if lon else None,
                "altitud": e.get("altitud"), "indsinop": e.get("indsinop", ""),
                "a_inventari_climatologic": True, "a_observacio_horaria": False,
            }
        log(f"- Inventari climatològic: {n_total} estacions a Espanya, {len(estacions)} a Catalunya.")
    except Exception as e:
        log(f"- ❌ Inventari climatològic: {e}")

    # 2. Observació convencional (dades horàries de les últimes ~24 h)
    try:
        obs, meta = aemet("observacion/convencional/todas", clau)
        desar_json("aemet_metadades_observacio.json", meta)
        cat = [o for o in obs if dins_bbox(o.get("lat"), o.get("lon"))]
        desar_json("aemet_mostra_observacio.json", cat)
        camps = sorted({k for o in cat for k in o})
        per_est = {}
        for o in cat:
            per_est.setdefault(o["idema"], []).append(o)
        for idema, files in per_est.items():
            e = estacions.setdefault(idema, {
                "indicativo": idema, "nom": files[0].get("ubi"), "provincia": "",
                "lat": files[0].get("lat"), "lon": files[0].get("lon"), "altitud": files[0].get("alt"),
                "indsinop": "", "a_inventari_climatologic": False})
            e["a_observacio_horaria"] = True
            hores = sorted(f["fint"] for f in files if "fint" in f)
            amb_prec = [f for f in files if num_aemet(f.get("prec")) is not None]
            e["obs_n_registres"] = len(files)
            e["obs_n_amb_prec"] = len(amb_prec)
            e["obs_primera"] = hores[0] if hores else ""
            e["obs_darrera"] = hores[-1] if hores else ""
            e["obs_prec_suma"] = round(sum(num_aemet(f["prec"]) for f in amb_prec), 1)
        n_prec = sum(1 for e in estacions.values() if e.get("obs_n_amb_prec"))
        log(f"- Observació convencional: {len(obs)} registres a Espanya, {len(cat)} a la caixa de Catalunya, "
            f"{len(per_est)} estacions ({n_prec} amb precipitació).")
        log(f"- Camps de l'observació: `{', '.join(camps)}`")
        hores_tot = sorted({o["fint"] for o in cat if "fint" in o})
        if hores_tot:
            log(f"- Finestra temporal de l'observació: {hores_tot[0]} → {hores_tot[-1]} ({len(hores_tot)} hores diferents)")
    except Exception as e:
        log(f"- ❌ Observació convencional: {e}")

    # 3. Climatologies diàries (dades validades, amb retard): una setmana d'ara fa ~3 setmanes
    try:
        fi = datetime.now(timezone.utc).date() - timedelta(days=14)
        ini = fi - timedelta(days=6)
        ruta = (f"valores/climatologicos/diarios/datos/fechaini/{ini}T00:00:00UTC/"
                f"fechafin/{fi}T23:59:59UTC/todasestaciones")
        clim, meta = aemet(ruta, clau)
        desar_json("aemet_metadades_climatologia.json", meta)
        cat = [c for c in clim if str(c.get("provincia", "")).upper() in PROVINCIES_CAT]
        desar_json("aemet_mostra_climatologia.json", cat)
        camps = sorted({k for c in cat for k in c})
        per_est = {}
        for c in cat:
            per_est.setdefault(c["indicativo"], []).append(c)
        for ind, files in per_est.items():
            e = estacions.get(ind)
            if e is None:
                continue
            e["clim_dies"] = len(files)
            e["clim_dies_amb_prec"] = sum(1 for f in files if num_aemet(f.get("prec")) is not None)
        log(f"- Climatologies diàries {ini} → {fi}: {len(cat)} registres a Catalunya, "
            f"{len(per_est)} estacions, {sum(1 for c in cat if num_aemet(c.get('prec')) is not None)} amb precipitació.")
        log(f"- Camps de la climatologia: `{', '.join(camps)}`")
        # Definició del camp prec segons les metadades (per saber la finestra del dia pluviomètric)
        for camp in (meta or {}).get("campos", []):
            if camp.get("id") in ("prec", "fecha"):
                log(f"- Metadades `{camp.get('id')}`: {camp.get('descripcion')}")
    except Exception as e:
        log(f"- ❌ Climatologies diàries: {e}")

    # Distància a la XEMA
    files = []
    for e in sorted(estacions.values(), key=lambda x: x["indicativo"]):
        if e.get("lat") is not None and xema:
            codi, d = xema_mes_propera(e["lat"], e["lon"], xema)
            e["xema_propera"], e["dist_xema_km"] = codi, round(d, 2)
        files.append(e)
    desar_csv("aemet_estacions.csv", files)
    resum_distancies(files)
    return files


# ===================================================================== ACA (Sentilo)

ACA_BASES = ["https://aplicacions.aca.gencat.cat/sdim2/apirest",
             "http://aca-web.gencat.cat/sdim2/apirest"]
PARAULES_PLUJA = re.compile(r"pluvi|precip|pluja|rain", re.I)


def get_json(url, **kw):
    r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return json.loads(decodificar(r))


def parse_location(loc):
    """Sentilo: 'lat lon' (o 'lat lon,lat lon' per a línies)."""
    if not loc:
        return None, None
    try:
        lat, lon = str(loc).split(",")[0].split()[:2]
        return float(lat), float(lon)
    except ValueError:
        return None, None


def inventari_aca(xema):
    log("## ACA")
    cataleg, base = None, None
    for b in ACA_BASES:
        try:
            cataleg, base = get_json(f"{b}/catalog"), b
            log(f"- Catàleg obtingut de `{b}/catalog`")
            break
        except Exception as e:
            log(f"- ⚠️ `{b}/catalog`: {e}")
    if cataleg is None:
        log("- ❌ No s'ha pogut obtenir el catàleg de l'ACA")
        return []

    sensors = []
    for p in cataleg.get("providers", []):
        for s in p.get("sensors", []):
            sensors.append({"provider": p.get("provider"), **s})
    tipus = {}
    for s in sensors:
        clau = (s.get("componentType"), s.get("type"), s.get("unit"))
        tipus[clau] = tipus.get(clau, 0) + 1
    log(f"- {len(cataleg.get('providers', []))} proveïdors, {len(sensors)} sensors.")
    log("- Tipus de sensor (componentType · type · unit → nombre):")
    log("")
    for (ct, t, u), n in sorted(tipus.items(), key=lambda x: -x[1]):
        log(f"    - {ct} · {t} · {u} → {n}")
    log("")

    pluja = [s for s in sensors if PARAULES_PLUJA.search(" ".join(
        str(s.get(k, "")) for k in ("type", "description", "componentType", "componentDesc", "component", "sensor")))]
    files = []
    for s in pluja:
        lat, lon = parse_location(s.get("location"))
        f = {"provider": s.get("provider"), "sensor": s.get("sensor"), "component": s.get("component"),
             "componentType": s.get("componentType"), "type": s.get("type"), "unit": s.get("unit"),
             "description": s.get("description"), "componentDesc": s.get("componentDesc"),
             "lat": lat, "lon": lon, "timeZone": s.get("timeZone", "")}
        if lat is not None and xema:
            codi, d = xema_mes_propera(lat, lon, xema)
            f["xema_propera"], f["dist_xema_km"] = codi, round(d, 2)
        files.append(f)
    desar_json("aca_mostra_cataleg_pluja.json", pluja[:20])
    desar_csv("aca_sensors_pluja.csv", files)
    log(f"- Sensors que semblen de pluja: {len(files)} ({sum(1 for f in files if dins_bbox(f['lat'], f['lon']))} amb coordenades a Catalunya)")
    resum_distancies(files)

    # Mostra de dades: provem diverses formes de la crida /data de Sentilo amb uns quants sensors
    if files:
        ara = datetime.now(timezone.utc)
        fmt = "%d/%m/%YT%H:%M:%S"
        proves = {}
        for f in files[:3]:
            for etiqueta, params in [
                ("ultims", {"limit": 50}),
                ("dia_anterior", {"from": (ara - timedelta(days=2)).strftime(fmt),
                                  "to": (ara - timedelta(days=1)).strftime(fmt), "limit": 1000}),
                ("fa_30_dies", {"from": (ara - timedelta(days=31)).strftime(fmt),
                                "to": (ara - timedelta(days=30)).strftime(fmt), "limit": 1000}),
            ]:
                url = f"{base}/data/{f['provider']}/{f['sensor']}"
                try:
                    d = get_json(url, params=params)
                    obs = d.get("observations", d) if isinstance(d, dict) else d
                    n = len(obs) if isinstance(obs, list) else "?"
                    proves[f"{f['sensor']}|{etiqueta}"] = {"url": url, "params": params, "n": n,
                                                          "resposta": obs[:30] if isinstance(obs, list) else d}
                    log(f"- /data {f['sensor']} [{etiqueta}]: {n} observacions")
                except Exception as e:
                    proves[f"{f['sensor']}|{etiqueta}"] = {"url": url, "params": params, "error": str(e)}
                    log(f"- ⚠️ /data {f['sensor']} [{etiqueta}]: {e}")
                time.sleep(1)
        desar_json("aca_mostra_dades.json", proves)
    return files


# ===================================================================== resum

def resum_distancies(files):
    d = sorted(f["dist_xema_km"] for f in files if f.get("dist_xema_km") is not None)
    if not d:
        return
    log(f"- Distància a l'estació XEMA més propera: < 1 km: {sum(x < 1 for x in d)} · "
        f"1–5 km: {sum(1 <= x < 5 for x in d)} · 5–10 km: {sum(5 <= x < 10 for x in d)} · "
        f"≥ 10 km: {sum(x >= 10 for x in d)} (mediana {d[len(d) // 2]:.1f} km)")


def main():
    xema = carregar_xema()
    log(f"# Inventari d'altres xarxes ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
    log("")
    log(f"Referència: {len(xema)} estacions XEMA (validacio/estacions_xema.json).")
    log("")
    clau = os.environ.get("AEMET_API_KEY", "").strip()
    if clau:
        try:
            inventari_aemet(clau, xema)
        except Exception as e:
            log(f"- ❌ Error inesperat a AEMET: {e!r}")
    else:
        log("## AEMET\n- ❌ Falta AEMET_API_KEY")
    log("")
    try:
        inventari_aca(xema)
    except Exception as e:
        log(f"- ❌ Error inesperat a l'ACA: {e!r}")
    desar_text("resum_inventari.md", "\n".join(resum) + "\n")
    print(f"\nResultats a {OUT}")


if __name__ == "__main__":
    sys.exit(main())
