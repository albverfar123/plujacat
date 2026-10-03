"""
Funcions compartides per a l'anàlisi i calibració del radar amb les estacions XEMA.

Dades d'entrada (generades pel pipeline, a validacio/):
  - parelles/parelles_YYYYMM.csv   pluja diària estació vs acumulat radar al píxel
  - recomptes/recomptes_YYYYMM.csv nº d'imatges de 6 min de cada classe de color per estació i dia

Model del radar:  acumulat_diari = 0.1 * sum_k n_k * v_k
  n_k = nº d'imatges del dia en què el píxel té el color k
  v_k = intensitat (mm/h) assignada al color k (taula LLEGENDA_RADAR)
"""
import os
import glob

import numpy as np
import pandas as pd
from scipy.optimize import nnls

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDACIO = os.path.join(ARREL, "validacio")

# Taula actual de radar_to_nc.py (mm/h per classe de color)
CLASSES = [0.01, 0.03, 0.05, 0.1, 0.2, 0.4, 0.8, 1.4, 2.0, 3.0, 4.0, 6.0, 9.0,
           14.0, 25.0, 40.0, 55.0, 70.0, 90.0, 120.0]
COLS_CLASSES = [f"c_{v:g}" for v in CLASSES]
IMATGES_DIA = 240  # una imatge cada 6 minuts

# Dia a partir del qual la taula de colors és l'actual
DATA_INICI = "2026-03-05"


# ------------------------------------------------------------------ càrrega

def carregar(desde=DATA_INICI, fins=None):
    """Taula unificada per estació i dia: pluja XEMA, radar i recomptes de classes."""
    par = pd.concat(pd.read_csv(f) for f in sorted(glob.glob(os.path.join(VALIDACIO, "parelles", "*.csv"))))
    rec = pd.concat(pd.read_csv(f) for f in sorted(glob.glob(os.path.join(VALIDACIO, "recomptes", "*.csv"))))
    rec = rec.drop(columns=["fila", "col"]).rename(columns={"n_imatges": "n_imatges_rec"})
    df = par.merge(rec, on=["data", "codi"], how="inner")
    df = df[df["data"] >= desde]
    if fins:
        df = df[df["data"] <= fins]
    df["data"] = pd.to_datetime(df["data"])
    df = df.rename(columns={"pluja_estacio": "obs"})
    df["n_imatges"] = df["n_imatges_rec"]
    return df.reset_index(drop=True)


def estacions(df):
    return df.groupby("codi")[["nom", "lat", "lon"]].first()


# ------------------------------------------------------------------ geometria

def distancies_km(lat1, lon1, lat2, lon2):
    """Matriu de distàncies (km) entre dos conjunts de punts."""
    la1, lo1, la2, lo2 = map(np.radians, (np.asarray(lat1), np.asarray(lon1), np.asarray(lat2), np.asarray(lon2)))
    c = (np.sin(la1)[:, None] * np.sin(la2)[None, :]
         + np.cos(la1)[:, None] * np.cos(la2)[None, :] * np.cos(lo1[:, None] - lo2[None, :]))
    return 6371.0 * np.arccos(np.clip(c, -1, 1))


# ------------------------------------------------------------------ radar a partir de recomptes

def matriu_recomptes(df, normalitzar=True):
    """Matriu N (files = estació-dia, columnes = classes) en nº d'imatges.
    Si normalitzar, s'escala a 240 imatges/dia per compensar imatges no descarregades."""
    N = df[COLS_CLASSES].to_numpy(float)
    if normalitzar:
        N = N * (IMATGES_DIA / df["n_imatges"].clip(lower=1).to_numpy(float))[:, None]
    return N


def radar_amb_taula(df, valors, normalitzar=True):
    """Acumulat diari (mm) amb una taula de valors per classe."""
    return 0.1 * matriu_recomptes(df, normalitzar) @ np.asarray(valors, float)


def ajustar_taula(N, y, pesos=None, monotona=True):
    """Ajusta els valors de cada classe per mínims quadrats no negatius.

    Si monotona=True, imposa v_1 <= v_2 <= ... (un color més intens no pot valer menys):
    es parametritza v_k = sum_{j<=k} d_j amb d_j >= 0 i es resol amb NNLS.
    Les classes sense cap observació hereten el valor de l'anterior."""
    A = 0.1 * N
    if pesos is not None:
        w = np.sqrt(np.asarray(pesos, float))
        A, y = A * w[:, None], np.asarray(y, float) * w
    if monotona:
        T = np.tril(np.ones((A.shape[1], A.shape[1])))  # v = T @ d
        d, _ = nnls(A @ T, y)
        return T @ d
    v, _ = nnls(A, y)
    return v


# ------------------------------------------------------------------ mètriques

def metriques(obs, est, llindar=1.0):
    """Mètriques comparables entre mètodes (sempre sobre el mateix conjunt de casos):
    - sobre els estació-dies amb pluja observada (obs >= llindar): ratio_total, r, MAE, RMSE, biaix
    - falses alarmes: % de dies secs a l'estació (obs == 0) en què l'estimació és >= llindar
    - pluja no detectada: % de dies amb obs >= 5 mm en què l'estimació és < 1 mm"""
    obs, est = np.asarray(obs, float), np.asarray(est, float)
    v = ~np.isnan(est)
    obs, est = obs[v], est[v]
    m = obs >= llindar
    o, e = obs[m], est[m]
    err = e - o
    sec = obs == 0
    fort = obs >= 5
    return pd.Series({
        "n": int(m.sum()),
        "ratio_total": e.sum() / o.sum(),          # 1 = sense biaix
        "r": np.corrcoef(o, e)[0, 1],
        "MAE": np.abs(err).mean(),
        "RMSE": np.sqrt((err ** 2).mean()),
        "biaix_mitja": err.mean(),
        "falses_alarmes_%": 100 * (est[sec] >= llindar).mean(),
        "no_detectada_%": 100 * (est[fort] < 1).mean(),
    })


def taula_metriques(df, columnes, obs="obs", llindar=1.0):
    return pd.DataFrame({c: metriques(df[obs], df[c], llindar) for c in columnes}).T


# ------------------------------------------------------------------ control de qualitat

def control_qualitat(df, radi_km=20, min_veins=2):
    """Marca estació-dies sospitosos comparant amb les estacions veïnes i el radar.

    - 'zero_sospitos': l'estació marca 0 però la mediana dels veïns i el radar al píxel
      marquen >= 5 mm (possible pluviòmetre obstruït o avariat).
    - 'extrem_sospitos': l'estació marca > 5 vegades els veïns i el radar, i > 30 mm.
    Les estacions sense prou veïns (min_veins dins de radi_km) no es marquen mai.
    Retorna el df amb columnes 'mediana_veins', 'qc_flag' (text) i 'qc_ok' (bool)."""
    st = estacions(df)
    D = distancies_km(st.lat, st.lon, st.lat, st.lon)
    codis = st.index.to_numpy()
    veins = {c: codis[(D[i] > 0) & (D[i] <= radi_km)] for i, c in enumerate(codis)}

    piv = df.pivot_table(index="data", columns="codi", values="obs")
    med = pd.DataFrame(index=piv.index, columns=piv.columns, dtype=float)
    for c in codis:
        v = [x for x in veins[c] if x in piv.columns]
        if len(v) >= min_veins:
            med[c] = piv[v].median(axis=1)
    medl = med.stack().rename("mediana_veins").reset_index()
    out = df.drop(columns=[c for c in ["mediana_veins", "qc_flag", "qc_ok"] if c in df]).merge(
        medl, on=["data", "codi"], how="left")

    zero = (out.obs == 0) & (out.mediana_veins >= 5) & (out.radar_px >= 5)
    extrem = (out.obs > 30) & out.mediana_veins.notna() & (out.obs > 5 * out.mediana_veins) & (out.obs > 5 * out.radar_px)
    out["qc_flag"] = np.where(zero, "zero_sospitos", np.where(extrem, "extrem_sospitos", ""))
    out["qc_ok"] = out["qc_flag"] == ""
    return out


# ------------------------------------------------------------------ correccions amb estacions

def _llista_per_dia(df, col_radar, min_mm):
    """Per a cada dia, arrays de lat, lon, obs, radar de les estacions vàlides."""
    for dia, g in df.groupby("data"):
        yield dia, g


def correccio_mfb(df, col_radar, min_mm=0.5, loo=True):
    """Mean field bias diari: factor = sum(obs)/sum(radar) de les estacions on tots dos >= min_mm.
    Amb loo=True, el factor d'una estació es calcula sense ella (leave-one-out)."""
    out = np.full(len(df), np.nan)
    for _, g in df.groupby("data"):
        o, r = g.obs.to_numpy(float), g[col_radar].to_numpy(float)
        ok = (o >= min_mm) & (r >= min_mm) & g.get("qc_ok", pd.Series(True, index=g.index)).to_numpy()
        so, sr = (o * ok).sum(), (r * ok).sum()
        if loo:
            so_i, sr_i = so - o * ok, sr - r * ok
        else:
            so_i, sr_i = np.full(len(g), so), np.full(len(g), sr)
        f = np.where(sr_i > 0, so_i / np.where(sr_i > 0, sr_i, 1), 1.0)
        out[df.index.get_indexer(g.index)] = r * f
    return out


def correccio_local(df, col_radar, min_mm=0.5, radi_km=30, potencia=2, loo=True, clip=(0.1, 10)):
    """Correcció local diària: s'interpola (IDW) el log del quocient obs/radar de les
    estacions properes (dins radi_km). Si no n'hi ha cap, es fa servir el mean field bias.
    Amb loo=True, l'estació avaluada no participa en la seva pròpia correcció."""
    mfb = correccio_mfb(df, col_radar, min_mm, loo)
    out = np.full(len(df), np.nan)
    for _, g in df.groupby("data"):
        o, r = g.obs.to_numpy(float), g[col_radar].to_numpy(float)
        idx = df.index.get_indexer(g.index)
        ok = (o >= min_mm) & (r >= min_mm) & g.get("qc_ok", pd.Series(True, index=g.index)).to_numpy()
        corr = mfb[idx].copy()
        if ok.sum() >= 1:
            lr = np.log(np.clip(o[ok] / r[ok], *clip))
            D = distancies_km(g.lat.to_numpy(), g.lon.to_numpy(), g.lat.to_numpy()[ok], g.lon.to_numpy()[ok])
            if loo:
                pos = np.where(ok)[0]
                D[pos, np.arange(len(pos))] = np.inf
            W = np.where(D <= radi_km, 1.0 / np.maximum(D, 1.0) ** potencia, 0.0)
            sw = W.sum(axis=1)
            te = sw > 0
            corr[te] = r[te] * np.exp((W[te] @ lr) / sw[te])
        out[idx] = corr
    return out


def factor_estatic_loo(df, col_radar, min_mm=1.0, radi_km=40, potencia=2, clip=(0.1, 10)):
    """Factor de correcció ESTÀTIC (climatològic) per estació: quocient sum(obs)/sum(radar)
    de tot el període a les estacions veïnes, interpolat amb IDW sense l'estació avaluada.
    Retorna una Series codi -> factor."""
    ok = (df.obs >= min_mm) & (df[col_radar] >= min_mm) & df.get("qc_ok", True)
    t = df[ok].groupby("codi").agg(o=("obs", "sum"), r=(col_radar, "sum"))
    st = estacions(df)
    t = t.join(st)
    lr = np.log(np.clip(t.o / t.r, *clip)).to_numpy()
    D = distancies_km(st.lat, st.lon, t.lat, t.lon)
    for i, c in enumerate(st.index):
        if c in t.index:
            D[i, t.index.get_loc(c)] = np.inf
    W = np.where(D <= radi_km, 1.0 / np.maximum(D, 1.0) ** potencia, 0.0)
    sw = W.sum(axis=1)
    global_lr = np.log(t.o.sum() / t.r.sum())
    f = np.where(sw > 0, np.exp((W @ lr) / np.where(sw > 0, sw, 1)), np.exp(global_lr))
    return pd.Series(f, index=st.index)


# ------------------------------------------------------------------ ajust amb validació creuada

def ajustar_potencia(N, y):
    """Ajusta v_k = a * v_original_k ** b (2 paràmetres, com una relació Z-R).
    Molt més robust que l'ajust lliure per a les classes intenses, que tenen poques dades."""
    from scipy.optimize import least_squares
    o = np.array(CLASSES)
    res = least_squares(lambda p: 0.1 * N @ (p[0] * o ** p[1]) - y, [1.0, 1.0],
                        bounds=([0.01, 0.2], [50.0, 3.0]))
    a, b = res.x
    return a * o ** b, (a, b)


def ajust_cv(df, model="lliure", n_folds=10, normalitzar=True):
    """Estimació del radar amb la taula ajustada, avaluada per validació creuada PER ESTACIONS:
    cada estació s'estima amb una taula ajustada sense ella (GroupKFold).
    Retorna (estimacio_cv, taula_ajustada_amb_totes_les_dades)."""
    from sklearn.model_selection import GroupKFold
    N = matriu_recomptes(df, normalitzar)
    y = df.obs.to_numpy(float)
    ok = df.get("qc_ok", pd.Series(True, index=df.index)).to_numpy()
    est = np.full(len(df), np.nan)

    def fit(idx):
        if model == "lliure":
            return ajustar_taula(N[idx], y[idx])
        return ajustar_potencia(N[idx], y[idx])[0]

    for tr, te in GroupKFold(n_folds).split(df, groups=df.codi):
        est[te] = 0.1 * N[te] @ fit(tr[ok[tr]])
    return est, fit(np.where(ok)[0])


# ------------------------------------------------------------------ estil de gràfics

COLORS = {"blau": "#2a78d6", "taronja": "#eb6834", "aqua": "#1baf7a",
          "gris": "#8c8c8c", "tinta": "#1f1f1f", "tinta2": "#5c5c5c"}


def estil():
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#bdbdbd", "axes.labelcolor": COLORS["tinta2"],
        "xtick.color": COLORS["tinta2"], "ytick.color": COLORS["tinta2"],
        "axes.grid": True, "grid.color": "#ececec", "grid.linewidth": 0.8,
        "axes.titlesize": 11, "axes.titleweight": "bold", "font.size": 9,
        "legend.frameon": False, "lines.linewidth": 2, "axes.axisbelow": True,
    })


def cmap_divergent():
    """Taronja (radar subestima) – gris – blau (radar sobreestima)."""
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("div", [COLORS["taronja"], "#e6e6e6", COLORS["blau"]])
