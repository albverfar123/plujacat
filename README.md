# PlujaCat 🌧️

[Català](#ca) · [Castellano](#es) · [English](#en)

<a id="ca"></a>

# Català

### Què és PlujaCat?

PlujaCat és un visor de la **pluja acumulada a Catalunya** dels darrers mesos, a escala **diària, setmanal i mensual**, amb una resolució d'**1 km aproximadament**. Combina dues fonts de dades públiques del Servei Meteorològic de Catalunya (Meteocat):

- **El radar meteorològic**, que veu on plou amb molt detall espacial, però no mesura la quantitat amb precisió.
- **Les estacions automàtiques (XEMA)**, unes 187 a Catalunya, que mesuren la pluja real amb pluviòmetre, però només en punts concrets.

La idea és aprofitar el millor de cadascuna: el radar diu **on** ha plogut i les estacions diuen **quant**.

### Com funciona

1. **Captura del radar (cada 6 minuts).** Es descarrega la imatge del radar del Meteocat i cada color es converteix en una intensitat de pluja (mm/h).
2. **Acumulat diari.** Se sumen totes les imatges del dia (00–24 UTC):
    - Cada color es converteix amb una **taula calibrada** a partir de mesos de dades d'estacions.
    - Es compensen les imatges que no s'han pogut descarregar.
    - El resultat es **corregeix amb les estacions XEMA del mateix dia**. A prop de cada estació, el mapa s'ajusta al que ha mesurat el pluviòmetre. Lluny de les estacions, s'aplica la correcció mitjana del dia.
3. **Acumulats setmanals (dilluns–diumenge) i mensuals.** Són la suma dels diaris. Només es compten els dies en què alguna estació ha registrat almenys 1 mm, per evitar sumar ecos falsos del radar en dies secs.
4. **Conservació.** Els mapes diaris es conserven uns 2–3 mesos. Els setmanals i els mensuals, indefinidament.

Tot el procés s'executa automàticament amb GitHub Actions i els resultats es publiquen en aquesta pàgina.

### Fiabilitat

La calibració s'ha validat amb les estacions XEMA de març a octubre de 2026. Cada estació es comprova amb un mapa corregit **sense** fer servir la seva pròpia dada, com si fos un punt sense estació:

| | Abans de la calibració | Ara |
|---|---|---|
| Pluja estimada / pluja mesurada | 0,46 | 0,89 |
| Correlació amb les estacions | 0,51 | 0,79 |
| Error mitjà diari | 6,9 mm | 4,3 mm |

**Limitacions:**

- És una estimació, no una mesura oficial.
- Pot haver-hi ecos falsos del radar, sobretot sobre el mar i a prop de les muntanyes.
- La neu i la pluja molt localitzada són més difícils d'estimar.
- Els mapes anteriors a l'agost de 2026 es van calcular amb el mètode antic, sense calibrar.

Tota l'anàlisi és pública i reproduïble a la carpeta [`analisi/`](https://github.com/albverfar123/plujacat/tree/main/analisi) del repositori.

### Com fer servir el mapa

- **DIARI / SETMANAL / MENSUAL:** tria l'escala temporal. Amb el calendari i les fletxes ◀ ▶ canvies de data.
- **Estacions:** els números sobre el mapa són la pluja mesurada per cada estació XEMA (mm).
- **Orientació:** mostra l'orientació del relleu (a partir de zoom 8).
- **📍:** centra el mapa a la teva ubicació.

### Dades i crèdits

Dades de radar i d'estacions: **Servei Meteorològic de Catalunya (Meteocat)**. PlujaCat és un projecte independent, sense cap vinculació amb el Meteocat. Codi: [github.com/albverfar123/plujacat](https://github.com/albverfar123/plujacat).

---

<a id="es"></a>

# Castellano

### ¿Qué es PlujaCat?

PlujaCat es un visor de la **lluvia acumulada en Cataluña** de los últimos meses, a escala **diaria, semanal y mensual**, con una resolución de **aproximadamente 1 km**. Combina dos fuentes de datos públicas del Servei Meteorològic de Catalunya (Meteocat):

- **El radar meteorológico**, que ve dónde llueve con mucho detalle espacial, pero no mide la cantidad con precisión.
- **Las estaciones automáticas (XEMA)**, unas 187 en Cataluña, que miden la lluvia real con pluviómetro, pero solo en puntos concretos.

La idea es aprovechar lo mejor de cada una: el radar dice **dónde** ha llovido y las estaciones dicen **cuánto**.

### Cómo funciona

1. **Captura del radar (cada 6 minutos).** Se descarga la imagen del radar del Meteocat y cada color se convierte en una intensidad de lluvia (mm/h).
2. **Acumulado diario.** Se suman todas las imágenes del día (00–24 UTC):
    - Cada color se convierte con una **tabla calibrada** a partir de meses de datos de estaciones.
    - Se compensan las imágenes que no se han podido descargar.
    - El resultado se **corrige con las estaciones XEMA del mismo día**. Cerca de cada estación, el mapa se ajusta a lo que ha medido el pluviómetro. Lejos de las estaciones, se aplica la corrección media del día.
3. **Acumulados semanales (lunes–domingo) y mensuales.** Son la suma de los diarios. Solo se cuentan los días en que alguna estación ha registrado al menos 1 mm, para evitar sumar ecos falsos del radar en días secos.
4. **Conservación.** Los mapas diarios se conservan unos 2–3 meses. Los semanales y los mensuales, indefinidamente.

Todo el proceso se ejecuta automáticamente con GitHub Actions y los resultados se publican en esta página.

### Fiabilidad

La calibración se ha validado con las estaciones XEMA de marzo a octubre de 2026. Cada estación se comprueba con un mapa corregido **sin** usar su propio dato, como si fuera un punto sin estación:

| | Antes de la calibración | Ahora |
|---|---|---|
| Lluvia estimada / lluvia medida | 0,46 | 0,89 |
| Correlación con las estaciones | 0,51 | 0,79 |
| Error medio diario | 6,9 mm | 4,3 mm |

**Limitaciones:**

- Es una estimación, no una medida oficial.
- Puede haber ecos falsos del radar, sobre todo sobre el mar y cerca de las montañas.
- La nieve y la lluvia muy localizada son más difíciles de estimar.
- Los mapas anteriores a agosto de 2026 se calcularon con el método antiguo, sin calibrar.

Todo el análisis es público y reproducible en la carpeta [`analisi/`](https://github.com/albverfar123/plujacat/tree/main/analisi) del repositorio.

### Cómo usar el mapa

- **DIARI / SETMANAL / MENSUAL:** elige la escala temporal. Con el calendario y las flechas ◀ ▶ cambias de fecha.
- **Estaciones:** los números sobre el mapa son la lluvia medida por cada estación XEMA (mm).
- **Orientació:** muestra la orientación del relieve (a partir de zoom 8).
- **📍:** centra el mapa en tu ubicación.

### Datos y créditos

Datos de radar y de estaciones: **Servei Meteorològic de Catalunya (Meteocat)**. PlujaCat es un proyecto independiente, sin ninguna vinculación con el Meteocat. Código: [github.com/albverfar123/plujacat](https://github.com/albverfar123/plujacat).

---

<a id="en"></a>

# English

### What is PlujaCat?

PlujaCat is a viewer of **accumulated rainfall in Catalonia** over recent months, at **daily, weekly and monthly** scale, with a resolution of **about 1 km**. It combines two public data sources from the Catalan Meteorological Service (Meteocat):

- **Weather radar**, which shows where it rains in great spatial detail, but does not measure amounts accurately.
- **Automatic weather stations (XEMA)**, about 187 in Catalonia, which measure actual rainfall with rain gauges, but only at specific points.

The idea is to combine the strengths of both: the radar tells **where** it rained and the stations tell **how much**.

### How it works

1. **Radar capture (every 6 minutes).** The Meteocat radar image is downloaded and each colour is converted into a rain rate (mm/h).
2. **Daily accumulation.** All images of the day (00–24 UTC) are added up:
    - Each colour is converted using a **calibrated table** fitted to months of station data.
    - Missing images are compensated for.
    - The result is **corrected with the XEMA stations of the same day**. Near each station, the map is adjusted to what the rain gauge measured. Far from stations, the day's average correction is applied.
3. **Weekly (Monday–Sunday) and monthly totals.** They are the sum of the daily maps. Only days on which at least one station recorded 1 mm or more are counted, so that false radar echoes on dry days are not added up.
4. **Retention.** Daily maps are kept for about 2–3 months; weekly and monthly maps are kept indefinitely.

The whole process runs automatically with GitHub Actions, and the results are published on this page.

### Reliability

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

### Using the map

- **DIARI / SETMANAL / MENSUAL:** choose the time scale (daily / weekly / monthly). Use the calendar and the ◀ ▶ arrows to change the date.
- **Stations:** the numbers on the map are the rainfall measured by each XEMA station (mm).
- **Orientació:** shows terrain aspect (from zoom level 8).
- **📍:** centres the map on your location.

### Data and credits

Radar and station data: **Servei Meteorològic de Catalunya (Meteocat)**. PlujaCat is an independent project with no affiliation to Meteocat. Code: [github.com/albverfar123/plujacat](https://github.com/albverfar123/plujacat).

---

## Estructura del repositori · Estructura del repositorio · Repository layout

| | |
|---|---|
| `radar_to_nc.py` | Captura del radar cada 6 min → Release del dia `radar-AAAAMMDD` |
| `arxiu_radar.py` | Arxiu de les imatges de 6 min: un paquet comprimit per dia a les Releases mensuals `radar-arxiu-AAAAMM` |
| `daily_accumulation.py` | Acumulat diari calibrat i corregit amb estacions → `acumulats_diaris/` |
| `weekly_accumulation.py` · `monthly_accumulation.py` | Acumulats setmanals i mensuals → `acumulats_setmanals/`, `acumulats_mensuals/` |
| `calibracio_radar.py` · `config_calibracio.json` | Calibració operativa (taula de colors + correcció amb estacions) |
| `validacio.py` · `validacio/` | Dades radar–estació per validar i recalibrar |
| `analisi/` | Notebooks de diagnosi i calibració ([resum](analisi/README.md)) |
| `eines/` | Scripts puntuals (reprocessar, extreure dades de l'historial, generar aquest README) |
| `.github/workflows/` | Automatització (GitHub Actions) |
| `index.html` | Visor web (Leaflet) |
