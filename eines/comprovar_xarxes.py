"""
Comprovacions de detall després de l'inventari (pas 1 d'incorporació d'estacions):

1. ACA: unitats i zona horària dels pluviòmetres. Per als pluviòmetres ACA a < 1 km d'una
   estació XEMA, baixa les dades de 5 min de dies de pluja i les sèries semihoràries XEMA
   (variable 35) dels mateixos dies, i ho desa per comparar-ho (notebook analisi/04).
2. ACA: profunditat de l'històric de l'API (/data amb from/to cada vegada més enrere).
3. AEMET: climatologies diàries (l'inventari va fallar): desa la resposta crua i les metadades.

Ús: METEOCAT_API_KEY=... AEMET_API_KEY=... python eines/comprovar_xarxes.py [AAAA-MM-DD ...]
"""
import os
import csv
import sys
import json
import time
from datetime import datetime, timedelta, timezone, date

import requests

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ARREL, "validacio", "xarxes")
ACA = "https://aplicacions.aca.gencat.cat/sdim2/apirest"
XEMA_API = "https://api.meteo.cat/xema/v1"
AEMET = "https://opendata.aemet.es/opendata/api"
UA = {"User-Agent": "PlujaCat (github.com/albverfar123/plujacat)"}
FMT = "%d/%m/%YT%H:%M:%S"
DIES_PER_DEFECTE = ["2026-09-29", "2026-10-03", "2026-09-09"]
resum = []


def log(m=""):
    print(m)
    resum.append(m)


def desar_json(nom, obj):
    with open(os.path.join(OUT, nom), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def aca_data(provider, sensor, ini, fi):
    """Totes les observacions entre ini i fi (UTC). L'API retorna com a màxim 200 per crida,
    de la més nova a la més antiga, així que anem paginant cap enrere."""
    obs, to = [], fi
    for _ in range(20):
        r = requests.get(f"{ACA}/data/{provider}/{sensor}", headers=UA, timeout=60,
                         params={"from": ini.strftime(FMT), "to": to.strftime(FMT), "limit": 200})
        r.raise_for_status()
        lot = r.json().get("observations", [])
        if not lot:
            break
        obs += lot
        mes_antic = min(int(o["time"]) for o in lot) / 1000
        if len(lot) < 200 or mes_antic <= ini.timestamp():
            break
        to = datetime.fromtimestamp(mes_antic - 1, timezone.utc)
        time.sleep(0.3)
    unics = {o["time"]: o for o in obs}
    return [unics[k] for k in sorted(unics)]


def xema_35(codi, dia, clau):
    r = requests.get(f"{XEMA_API}/variables/mesurades/35/{dia:%Y/%m/%d}",
                     params={"codiEstacio": codi}, headers={"X-Api-Key": clau, **UA}, timeout=60)
    r.raise_for_status()
    d = r.json()
    if isinstance(d, list):
        d = d[0] if d else {}
    return d.get("lectures", [])


# ------------------------------------------------------------------ 1. ACA vs XEMA

def aca_vs_xema(dies):
    log("## 1. ACA vs XEMA (pluviòmetres a < 1 km)")
    clau = os.environ.get("METEOCAT_API_KEY", "").strip()
    with open(os.path.join(OUT, "aca_sensors_pluja.csv"), encoding="utf-8") as f:
        sensors = [s for s in csv.DictReader(f) if s["dist_xema_km"] and float(s["dist_xema_km"]) < 1]
    files = []
    for dia_s in dies:
        dia = date.fromisoformat(dia_s)
        # finestra ampla (±3 h) per poder detectar desfasaments horaris
        ini = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc) - timedelta(hours=3)
        fi = ini + timedelta(hours=30)
        for s in sensors:
            try:
                for o in aca_data(s["provider"], s["sensor"], ini, fi):
                    files.append({"xarxa": "ACA", "dia": dia_s, "codi": s["sensor"], "xema": s["xema_propera"],
                                  "timestamp": o["timestamp"], "time_ms": o["time"], "valor": o["value"]})
            except Exception as e:
                log(f"- ⚠️ ACA {s['sensor']} {dia_s}: {e}")
            if clau:
                for d in (dia - timedelta(days=1), dia, dia + timedelta(days=1)):
                    try:
                        for l in xema_35(s["xema_propera"], d, clau):
                            files.append({"xarxa": "XEMA", "dia": dia_s, "codi": s["xema_propera"],
                                          "xema": s["xema_propera"], "timestamp": l.get("data"),
                                          "time_ms": "", "valor": l.get("valor"),
                                          "estat": l.get("estat", ""), "base": l.get("baseHoraria", "")})
                    except Exception as e:
                        log(f"- ⚠️ XEMA {s['xema_propera']} {d}: {e}")
        log(f"- {dia_s}: fet")
    if files:
        cols = ["xarxa", "dia", "codi", "xema", "timestamp", "time_ms", "valor", "estat", "base"]
        with open(os.path.join(OUT, "comparacio_aca_xema.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(files)
    n_aca = sum(f["xarxa"] == "ACA" for f in files)
    log(f"- {len(sensors)} parelles, {n_aca} registres ACA, {len(files) - n_aca} registres XEMA "
        f"→ comparacio_aca_xema.csv")


# ------------------------------------------------------------------ 2. Històric ACA

def historic_aca():
    log("## 2. Profunditat de l'històric de l'ACA")
    with open(os.path.join(OUT, "aca_sensors_pluja.csv"), encoding="utf-8") as f:
        s = next(csv.DictReader(f))
    ara = datetime.now(timezone.utc)
    for dies in (60, 120, 240, 365, 730, 1500):
        ini = ara - timedelta(days=dies)
        try:
            r = requests.get(f"{ACA}/data/{s['provider']}/{s['sensor']}", headers=UA, timeout=60,
                             params={"from": ini.strftime(FMT),
                                     "to": (ini + timedelta(hours=6)).strftime(FMT), "limit": 200})
            r.raise_for_status()
            n = len(r.json().get("observations", []))
            log(f"- fa {dies} dies ({ini:%Y-%m-%d}): {n} observacions en 6 h")
        except Exception as e:
            log(f"- fa {dies} dies: ⚠️ {e}")
        time.sleep(0.5)


# ------------------------------------------------------------------ 3. AEMET climatologies

def aemet_clim():
    log("## 3. AEMET climatologies diàries")
    clau = os.environ.get("AEMET_API_KEY", "").strip()
    if not clau:
        log("- ❌ Falta AEMET_API_KEY")
        return
    proves = {
        "todas_3dies": "valores/climatologicos/diarios/datos/fechaini/2026-09-08T00:00:00UTC/"
                       "fechafin/2026-09-10T23:59:59UTC/todasestaciones",
        "estacio_0201D": "valores/climatologicos/diarios/datos/fechaini/2026-09-01T00:00:00UTC/"
                         "fechafin/2026-09-30T23:59:59UTC/estacion/0201D",
    }
    crues = {}
    for nom, ruta in proves.items():
        info = {"ruta": ruta}
        try:
            r = requests.get(f"{AEMET}/{ruta}", headers={"api_key": clau, **UA}, timeout=60)
            info["status"], info["cap_text"] = r.status_code, r.text[:500]
            cap = r.json()
            if cap.get("datos"):
                time.sleep(1)
                d = requests.get(cap["datos"], headers=UA, timeout=60)
                info["datos_status"] = d.status_code
                try:
                    txt = d.content.decode("utf-8")
                except UnicodeDecodeError:
                    txt = d.content.decode("latin-1")
                info["datos_inici"] = txt[:300]
                try:
                    dades = json.loads(txt)
                    info["n"] = len(dades)
                    cat = [x for x in dades if str(x.get("provincia", "")).upper()
                           in {"BARCELONA", "GIRONA", "LLEIDA", "TARRAGONA"}]
                    info["mostra"] = cat[:40]
                except ValueError as e:
                    info["error_json"] = str(e)
            if cap.get("metadatos"):
                m = requests.get(cap["metadatos"], headers=UA, timeout=60)
                try:
                    info["metadades"] = json.loads(m.content.decode("latin-1"))
                except ValueError:
                    info["metadades_text"] = m.text[:1000]
            log(f"- {nom}: HTTP {info['status']}, datos {info.get('datos_status')}, "
                f"n={info.get('n')}, {info.get('error_json', '')}")
            for c in (info.get("metadades") or {}).get("campos", []):
                if c.get("id") in ("prec", "fecha"):
                    log(f"    - `{c['id']}`: {c.get('descripcion')}")
        except Exception as e:
            info["error"] = repr(e)
            log(f"- {nom}: ⚠️ {e!r}")
        crues[nom] = info
        time.sleep(3)
    desar_json("aemet_prova_climatologia.json", crues)


def main():
    dies = sys.argv[1:] or DIES_PER_DEFECTE
    log(f"# Comprovacions de xarxes ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
    log("")
    for f in (lambda: aca_vs_xema(dies), historic_aca, aemet_clim):
        try:
            f()
        except Exception as e:
            log(f"- ❌ Error inesperat: {e!r}")
        log("")
    with open(os.path.join(OUT, "resum_comprovacions.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(resum) + "\n")


if __name__ == "__main__":
    main()
