"""
Arxiu de les imatges de radar de 6 min fora de git.

Les imatges de 6 min ja no es pugen al repositori: el workflow del radar les desa com a
fitxers adjunts d'una Release de GitHub per dia (`radar-AAAAMMDD`). Després de calcular
l'acumulat diari, aquest mòdul les empaqueta en UN fitxer per dia (NetCDF comprimit, ~1–1,5 MB)
que el workflow diari puja a una Release mensual (`radar-arxiu-AAAAMM`), i la Release del dia
s'esborra.

Format del paquet diari (radar_AAAAMMDD.nc):
  - classe (temps, lat, lon), uint8: 0 = sense eco; k = 1..20 → color k de la llegenda
    (valor original k-1 de VALORS_CLASSES, en mm/h, tal com el desa radar_to_nc.py);
    255 = valor no reconegut.
  - temps: marca de temps de cada imatge (AAAAMMDD_HHMMSS, UTC).
Així es poden tornar a calcular els acumulats amb qualsevol calibració futura.
"""
import os
import numpy as np
import xarray as xr

VALORS_CLASSES = [0.01, 0.03, 0.05, 0.1, 0.2, 0.4, 0.8, 1.4, 2.0, 3.0, 4.0, 6.0, 9.0,
                  14.0, 25.0, 40.0, 55.0, 70.0, 90.0, 120.0]
ARXIU_DIR = "arxiu_radar"


def a_classes(valors):
    """Camp de 6 min (mm/h originals, NaN = sense eco) → índex de classe uint8."""
    v = np.asarray(valors, dtype="f8")
    out = np.zeros(v.shape, dtype=np.uint8)
    ok = ~np.isnan(v)
    cls = np.array(VALORS_CLASSES)
    dif = np.abs(v[ok][:, None] - cls[None, :])
    k = dif.argmin(axis=1)
    exacte = dif[np.arange(len(k)), k] < 1e-3
    out[ok] = np.where(exacte, k + 1, 255).astype(np.uint8)
    return out


def de_classes(classes):
    """Índex de classe → mm/h originals (NaN = sense eco o valor no reconegut)."""
    taula = np.full(256, np.nan)
    taula[1:len(VALORS_CLASSES) + 1] = VALORS_CLASSES
    return taula[np.asarray(classes)]


def crear_paquet_dia(paths, dia, out_dir=ARXIU_DIR):
    """Empaqueta els fitxers de 6 min d'un dia en un sol NetCDF comprimit."""
    camps, temps, lat, lon = [], [], None, None
    for p in sorted(paths):
        try:
            with xr.open_dataset(p) as ds:
                if lat is None:
                    lat, lon = ds["lat"].values, ds["lon"].values
                camps.append(a_classes(ds["precipitacio"].values))
                temps.append(os.path.basename(p)[6:21])
        except Exception as e:
            print(f"⚠️ Arxiu: no s'ha pogut llegir {p}: {e}")
    if not camps:
        return None
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"radar_{dia}.nc")
    ds = xr.Dataset(
        {"classe": (("temps", "lat", "lon"), np.stack(camps))},
        coords={"temps": np.array(temps), "lat": lat, "lon": lon},
        attrs={"descripcio": "Imatges de radar Meteocat de 6 min com a índex de classe de color",
               "valors_classes_mm_h": VALORS_CLASSES,
               "codificacio": "0 = sense eco; k = valors_classes_mm_h[k-1]; 255 = no reconegut"})
    ds.to_netcdf(out, encoding={"classe": {"zlib": True, "complevel": 6,
                                           "chunksizes": (1, len(lat), len(lon))}})
    print(f"📦 Paquet diari del radar: {out} ({len(temps)} imatges, {os.path.getsize(out) / 1e6:.1f} MB)")
    return out


def llegir_paquet(path):
    """Generador (marca_de_temps, camp_mm_h_original) per tornar a processar un dia arxivat."""
    with xr.open_dataset(path) as ds:
        for t, c in zip(ds["temps"].values, ds["classe"].values):
            yield str(t), de_classes(c)
