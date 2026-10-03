## What is PlujaCat?

PlujaCat is a viewer of **accumulated rainfall in Catalonia** over recent months, at **daily, weekly and monthly** scale, with a resolution of **about 1 km**. It combines two public data sources from the Catalan Meteorological Service (Meteocat):

- **Weather radar**, which shows where it rains in great spatial detail, but does not measure amounts accurately.
- **Automatic weather stations (XEMA)**, about 187 in Catalonia, which measure actual rainfall with rain gauges, but only at specific points.

The idea is to combine the strengths of both: the radar tells **where** it rained and the stations tell **how much**.

## How it works

1. **Radar capture (every 6 minutes).** The Meteocat radar image is downloaded and each colour is converted into a rain rate (mm/h).
2. **Daily accumulation.** All images of the day (00–24 UTC) are added up:
    - Each colour is converted using a **calibrated table** fitted to months of station data.
    - Missing images are compensated for.
    - The result is **corrected with the XEMA stations of the same day**. Near each station, the map is adjusted to what the rain gauge measured. Far from stations, the day's average correction is applied.
3. **Weekly (Monday–Sunday) and monthly totals.** They are the sum of the daily maps. Only days on which at least one station recorded 1 mm or more are counted, so that false radar echoes on dry days are not added up.
4. **Retention.** Daily maps are kept for about 2–3 months; weekly and monthly maps are kept indefinitely.

The whole process runs automatically with GitHub Actions, and the results are published on this page.

## Reliability

The calibration was validated against XEMA stations from March to October 2026. Each station is checked against a map corrected **without** its own measurement, as if it were a point with no station:

| | Before calibration | Now |
|---|---|---|
| Estimated / measured rainfall | 0.46 | 0.89 |
| Correlation with stations | 0.51 | 0.79 |
| Mean daily error | 6.9 mm | 4.3 mm |

**Limitations:**

- This is an estimate, not an official measurement.
- There may be false radar echoes, especially over the sea and near mountains.
- Snow and very localised rain are harder to estimate.
- Maps before August 2026 were computed with the old, uncalibrated method.

The full analysis is public and reproducible in the [`analisi/`](https://github.com/albverfar123/plujacat/tree/main/analisi) folder of the repository.

## Using the map

- **DIARI / SETMANAL / MENSUAL:** choose the time scale (daily / weekly / monthly). Use the calendar and the ◀ ▶ arrows to change the date.
- **Stations:** the numbers on the map are the rainfall measured by each XEMA station (mm).
- **Orientació:** shows terrain aspect (from zoom level 8).
- **📍:** centres the map on your location.

## Data and credits

Radar and station data: **Servei Meteorològic de Catalunya (Meteocat)**. PlujaCat is an independent project with no affiliation to Meteocat. Code: [github.com/albverfar123/plujacat](https://github.com/albverfar123/plujacat).
