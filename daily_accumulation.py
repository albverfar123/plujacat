import os
import sys
import xarray as xr
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, date
import matplotlib.colors as colors
import json
import requests
import csv

# --- CONFIGURACIÓ API METEOCAT ---
# La clau es llegeix del secret del repositori (Settings > Secrets > Actions > METEOCAT_API_KEY)
API_KEY = os.environ.get("METEOCAT_API_KEY", "").strip()
BASE_URL = "https://api.meteo.cat/xema/v1"
CODI_PLUJA = "1300"
TIMEOUT = 30

OUTPUT_DIR = "dades_radar"
DAILY_DIR = "acumulats_diaris"
FACTOR_TEMPORAL = 0.1  # cada imatge representa ~6 minuts (mm/h * 0.1 h)

# Cache per no repetir crides a l'API quan es processen molts dies
_cache_metadades = None
_cache_mesos = {}


def api_get(path):
    if not API_KEY:
        raise RuntimeError("Falta la variable d'entorn METEOCAT_API_KEY")
    res = requests.get(f"{BASE_URL}{path}", headers={"X-Api-Key": API_KEY}, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def get_estacions_info():
    global _cache_metadades
    if _cache_metadades is None:
        _cache_metadades = {}
        for e in api_get("/estacions/metadades"):
            _cache_metadades[e['codi']] = {
                'nom': e['nom'],
                'lat': e['coordenades']['latitud'],
                'lon': e['coordenades']['longitud']
            }
    return _cache_metadades


def get_dades_mes(year, month):
    key = (year, month)
    if key not in _cache_mesos:
        _cache_mesos[key] = api_get(f"/variables/estadistics/diaris/{CODI_PLUJA}?any={year}&mes={month:02d}")
    return _cache_mesos[key]


def get_stations_daily_data(date_obj):
    """Obté la pluja i coordenades de les estacions per a un dia concret"""
    date_api_str = date_obj.strftime("%Y-%m-%dZ")
    print(f"📡 Descarregant dades d'estacions per al {date_obj.strftime('%Y-%m-%d')}...")

    estacions_info = get_estacions_info()
    dades_completes = []
    for estacio in get_dades_mes(date_obj.year, date_obj.month):
        codi = estacio.get('codiEstacio')
        if codi in estacions_info:
            info = estacions_info[codi]
            for val in estacio.get('valors', []):
                if val['data'] == date_api_str:
                    dades_completes.append({
                        'codi': codi,
                        'nom': info['nom'],
                        'lat': info['lat'],
                        'lon': info['lon'],
                        'data': date_api_str.replace('Z', ''),
                        'pluja': float(val['valor'])
                    })
    return dades_completes


def dies_pendents():
    """Retorna tots els dies anteriors a avui (UTC) que tenen fitxers de radar sense processar,
    més el dia d'ahir (per assegurar que sempre es descarreguen les estacions)."""
    avui = datetime.utcnow().date()
    dies = set()
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith("radar_") and f.endswith(".nc"):
                try:
                    d = datetime.strptime(f[6:14], "%Y%m%d").date()
                except ValueError:
                    continue
                if d < avui:
                    dies.add(d)
    ahir = avui - timedelta(days=1)
    dies.add(ahir)
    # Dies recents sense fitxer d'estacions (p. ex. si l'API va fallar)
    for i in range(1, 31):
        d = avui - timedelta(days=i)
        if os.path.exists(os.path.join(DAILY_DIR, f"acumulat_{d:%Y%m%d}.nc")) and \
           not os.path.exists(os.path.join(DAILY_DIR, f"estacions_{d:%Y%m%d}.json")):
            dies.add(d)
    return sorted(dies)


def process_radar_day(dia_str):
    all_files_paths = sorted(
        os.path.join(OUTPUT_DIR, f) for f in os.listdir(OUTPUT_DIR)
        if f.startswith(f"radar_{dia_str}") and f.endswith(".nc")
    ) if os.path.exists(OUTPUT_DIR) else []

    if not all_files_paths:
        print(f"ℹ️ No hi ha fitxers de radar pendents per al dia {dia_str}.")
        return

    total_precip, lon, lat = None, None, None
    used_files = []
    for file_path in all_files_paths:
        try:
            with xr.open_dataset(file_path) as ds:
                data = ds['precipitacio'].fillna(0).load()
                if total_precip is None:
                    total_precip = data * FACTOR_TEMPORAL
                    lon, lat = ds['lon'].load(), ds['lat'].load()
                else:
                    total_precip += data * FACTOR_TEMPORAL
                used_files.append(os.path.basename(file_path))
        except Exception as e:
            print(f"⚠️ Error obrint {file_path}: {e}")

    if total_precip is None:
        print(f"⚠️ Cap fitxer de radar llegible per al dia {dia_str}.")
        return

    ds_daily = xr.Dataset(
        {"precipitacio_acumulada": (["lat", "lon"], total_precip.values)},
        coords={"lon": lon, "lat": lat},
        attrs={
            "description": f"Acumulat diari {dia_str}",
            "units": "mm",
            "date": dia_str,
            "files_count": len(used_files),
            "resolution_min": 6
        }
    )
    nc_out_path = os.path.join(DAILY_DIR, f"acumulat_{dia_str}.nc")
    ds_daily.to_netcdf(nc_out_path)
    print(f"✅ NetCDF diari guardat: {nc_out_path} ({len(used_files)} fitxers)")

    with open(os.path.join(DAILY_DIR, f"fonts_acumulat_{dia_str}.txt"), "w") as f_txt:
        f_txt.write(f"Resum de l'acumulat del dia {dia_str}:\nTotal fitxers processats: {len(used_files)}\n\n")
        f_txt.write("\n".join(used_files))

    generate_daily_png(total_precip, lon, lat, dia_str)

    print(f"🗑️ Netejant fitxers de radar del dia {dia_str}...")
    for f_path in all_files_paths:
        try:
            os.remove(f_path)
        except Exception as e:
            print(f"⚠️ No s'ha pogut eliminar {f_path}: {e}")


def process_stations_day(dia_obj):
    dia_str = dia_obj.strftime("%Y%m%d")
    try:
        estacions_data = get_stations_daily_data(dia_obj)
    except Exception as e:
        print(f"❌ Error obtenint dades d'estacions per al {dia_str}: {e}")
        return False
    if not estacions_data:
        print(f"⚠️ No s'han trobat dades d'estacions per al {dia_str}.")
        return True

    csv_path = os.path.join(DAILY_DIR, f"estacions_{dia_str}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Codi', 'Nom', 'Data', 'Precipitacio_mm'])
        for d in estacions_data:
            writer.writerow([d['codi'], d['nom'], d['data'], d['pluja']])
    save_stations_geojson(estacions_data, os.path.join(DAILY_DIR, f"estacions_{dia_str}.json"))
    print(f"📍 Estacions guardades: {len(estacions_data)} ({dia_str})")
    return True


def calculate_daily():
    os.makedirs(DAILY_DIR, exist_ok=True)
    dies = dies_pendents()
    print(f"📅 Dies a processar: {', '.join(d.strftime('%Y%m%d') for d in dies)}")

    errors_estacions = 0
    for dia_obj in dies:
        dia_str = dia_obj.strftime("%Y%m%d")
        print(f"\n===== {dia_str} =====")
        process_radar_day(dia_str)
        if not process_stations_day(dia_obj):
            errors_estacions += 1

    if errors_estacions:
        print(f"\n⚠️ {errors_estacions} dia(es) sense dades d'estacions. Es reintentarà a la propera execució.")


def generate_daily_png(data, lon, lat, date_str):
    fig = plt.figure(frameon=False)
    fig.set_size_inches(data.shape[1] / 100, data.shape[0] / 100)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.set_axis_off()
    fig.add_axes(ax)
    norm = colors.LogNorm(vmin=0.1, vmax=200)
    cmap = plt.get_cmap('turbo').copy()
    cmap.set_under(alpha=0)
    ax.pcolormesh(lon.values, lat.values, data.values, cmap=cmap, norm=norm, shading='auto')
    png_out_path = os.path.join(DAILY_DIR, f"acumulat_{date_str}.png")
    fig.savefig(png_out_path, transparent=True, dpi=100)
    plt.close(fig)
    print(f"🎨 PNG guardat: {png_out_path}")

    bounds_data = {
        "lat_min": float(lat.min()), "lat_max": float(lat.max()),
        "lon_min": float(lon.min()), "lon_max": float(lon.max())
    }
    with open("bounds.json", "w") as f:
        json.dump(bounds_data, f)


def save_stations_geojson(dades, path):
    geojson = {"type": "FeatureCollection", "features": []}
    for d in dades:
        if d['pluja'] >= 0:
            geojson["features"].append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [d['lon'], d['lat']]},
                "properties": {
                    "codi": d['codi'], "nom": d['nom'],
                    "pluja": d['pluja'], "data": d['data']
                }
            })
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)


if __name__ == "__main__":
    if not API_KEY:
        print("⚠️ Falta METEOCAT_API_KEY (Settings > Secrets and variables > Actions). "
              "Es processarà el radar però no les estacions.")
    calculate_daily()
