"""
Calibració del radar aplicada al pipeline operatiu (només numpy).

Dos passos, justificats a analisi/ (notebooks 02 i 03):

1. Taula de colors ajustada: cada color del radar (valor original de LLEGENDA_RADAR,
   tal com el desa radar_to_nc.py) es converteix al valor calibrat de config_calibracio.json.
   L'acumulat es normalitza per les imatges realment descarregades (240/dia).

2. Correcció local diària amb les estacions XEMA del mateix dia: a cada estació amb pluja
   es calcula log(XEMA/radar); el camp de correcció és una mitjana ponderada per distància
   (IDW, dins de radi_km) d'aquests valors més el biaix mitjà del dia, que actua com una
   "estació" amb pes fix 1/pes_biaix_mitja_km^2. Lluny de les estacions, la correcció tendeix
   al biaix mitjà del dia sense discontinuïtats.

Els fitxers de 6 min continuen guardant els valors ORIGINALS: la calibració només s'aplica
en acumular, i així es pot recalibrar en el futur sense perdre res.
"""
import os
import json
import numpy as np

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_calibracio.json")
IMATGES_DIA = 240
FACTOR_TEMPORAL = 0.1  # 6 min = 0.1 h


def carregar_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    orig = np.array([float(k) for k in cfg["taula"]])
    calib = np.array([float(v) for v in cfg["taula"].values()])
    ordre = np.argsort(orig)
    cfg["_orig"], cfg["_calib"] = orig[ordre], calib[ordre]
    return cfg


# ------------------------------------------------------------------ 1. taula de colors

def calibrar_imatge(valors, cfg):
    """Converteix un camp de 6 min (valors originals, NaN = sense eco) a mm/h calibrats.
    Valors que no corresponen a cap classe es deixen tal com estan."""
    v = np.asarray(valors, dtype="f8")
    out = np.zeros_like(v)
    ok = ~np.isnan(v)
    orig, calib = cfg["_orig"], cfg["_calib"]
    idx = np.clip(np.searchsorted(orig, v[ok]), 0, len(orig) - 1)
    prev = np.clip(idx - 1, 0, len(orig) - 1)
    millor = np.where(np.abs(orig[prev] - v[ok]) < np.abs(orig[idx] - v[ok]), prev, idx)
    exacte = np.abs(orig[millor] - v[ok]) < 1e-3
    res = np.where(exacte, calib[millor], v[ok])
    out[ok] = res
    return out


class Acumulador:
    """Suma imatges de 6 min: acumulat original (com abans) i acumulat calibrat."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.original = None
        self.calibrat = None
        self.n = 0

    def afegir(self, valors):
        v = np.asarray(valors, dtype="f8")
        orig = np.nan_to_num(v) * FACTOR_TEMPORAL
        cal = calibrar_imatge(v, self.cfg) * FACTOR_TEMPORAL
        if self.original is None:
            self.original, self.calibrat = orig, cal
        else:
            self.original += orig
            self.calibrat += cal
        self.n += 1

    def resultat(self):
        """(acumulat_original, acumulat_calibrat_normalitzat)"""
        factor = IMATGES_DIA / self.n if (self.cfg.get("normalitzar_per_imatges", True) and self.n) else 1.0
        return self.original, self.calibrat * factor


# ------------------------------------------------------------------ 2. correcció amb estacions

def _dist_km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    c = (np.sin(la1)[:, None] * np.sin(la2)[None, :]
         + np.cos(la1)[:, None] * np.cos(la2)[None, :] * np.cos(lo1[:, None] - lo2[None, :]))
    return 6371.0 * np.arccos(np.clip(c, -1, 1))


def pixel(lats, lons, lat, lon):
    if not (lats.min() <= lat <= lats.max() and lons.min() <= lon <= lons.max()):
        return None
    return int(np.abs(lats - lat).argmin()), int(np.abs(lons - lon).argmin())


def control_qualitat(estacions, radar_px, radi_km=20, min_veins=2):
    """Retorna una màscara booleana d'estacions vàlides per a la correcció.
    Mateixos criteris que analisi/calibracio.control_qualitat:
      - zero sospitós: obs = 0, radar >= 5 mm i mediana veïns >= 5 mm
      - extrem sospitós: obs > 30 mm i > 5 x radar i > 5 x mediana veïns"""
    lat = np.array([e["lat"] for e in estacions])
    lon = np.array([e["lon"] for e in estacions])
    obs = np.array([e["pluja"] for e in estacions], dtype=float)
    D = _dist_km(lat, lon, lat, lon)
    ok = np.ones(len(estacions), dtype=bool)
    for i in range(len(estacions)):
        v = (D[i] > 0) & (D[i] <= radi_km)
        if v.sum() < min_veins:
            continue
        med = np.median(obs[v])
        if obs[i] == 0 and radar_px[i] >= 5 and med >= 5:
            ok[i] = False
        if obs[i] > 30 and obs[i] > 5 * radar_px[i] and obs[i] > 5 * med:
            ok[i] = False
    return ok


def corregir_amb_estacions(camp, lats, lons, estacions, cfg):
    """Aplica la correcció local diària.

    camp: acumulat diari calibrat (lat x lon), estacions: llista de dicts amb lat, lon, pluja.
    Retorna (camp_corregit, info)."""
    p = cfg["correccio_estacions"]
    min_mm, radi, clip = p["min_mm"], p["radi_km"], tuple(p["clip"])
    w0 = 1.0 / p["pes_biaix_mitja_km"] ** 2

    punts = []
    for e in estacions:
        ij = pixel(lats, lons, e["lat"], e["lon"])
        if ij is not None and e.get("pluja") is not None and e["pluja"] >= 0:
            punts.append((e, ij))
    info = {"estacions_disponibles": len(punts), "estacions_usades": 0, "biaix_mitja": 1.0}
    if not punts:
        info["correccio"] = "sense_estacions"
        return camp.copy(), info

    est = [e for e, _ in punts]
    r = np.array([camp[i, j] for _, (i, j) in punts])
    o = np.array([e["pluja"] for e in est], dtype=float)
    qc = control_qualitat(est, r)
    valid = qc & (o >= min_mm) & (r >= min_mm)
    info["estacions_descartades_qc"] = int((~qc).sum())
    if valid.sum() == 0:
        info["correccio"] = "cap_estacio_amb_pluja"
        return camp.copy(), info

    mfb = o[valid].sum() / r[valid].sum()
    lr_mfb = np.log(np.clip(mfb, *clip))
    lr = np.log(np.clip(o[valid] / r[valid], *clip))
    slat = np.array([e["lat"] for e in est])[valid]
    slon = np.array([e["lon"] for e in est])[valid]

    # Malla de factors (fila a fila per no fer servir massa memòria)
    factor = np.empty_like(camp, dtype="f8")
    lon_grid = np.asarray(lons, dtype="f8")
    for i, la in enumerate(np.asarray(lats, dtype="f8")):
        D = _dist_km(np.full(lon_grid.shape, la), lon_grid, slat, slon)
        W = np.where(D <= radi, 1.0 / np.maximum(D, 1.0) ** 2, 0.0)
        factor[i] = np.exp((W @ lr + w0 * lr_mfb) / (W.sum(axis=1) + w0))

    info.update({"correccio": "local", "estacions_usades": int(valid.sum()),
                 "biaix_mitja": round(float(mfb), 4)})
    return camp * factor, info
