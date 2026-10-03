## ¿Qué es PlujaCat?

PlujaCat es un visor de la **lluvia acumulada en Cataluña** de los últimos meses, a escala **diaria, semanal y mensual**, con una resolución de **aproximadamente 1 km**. Combina dos fuentes de datos públicas del Servei Meteorològic de Catalunya (Meteocat):

- **El radar meteorológico**, que ve dónde llueve con mucho detalle espacial, pero no mide la cantidad con precisión.
- **Las estaciones automáticas (XEMA)**, unas 187 en Cataluña, que miden la lluvia real con pluviómetro, pero solo en puntos concretos.

La idea es aprovechar lo mejor de cada una: el radar dice **dónde** ha llovido y las estaciones dicen **cuánto**.

## Cómo funciona

1. **Captura del radar (cada 6 minutos).** Se descarga la imagen del radar del Meteocat y cada color se convierte en una intensidad de lluvia (mm/h).
2. **Acumulado diario.** Se suman todas las imágenes del día (00–24 UTC):
    - Cada color se convierte con una **tabla calibrada** a partir de meses de datos de estaciones.
    - Se compensan las imágenes que no se han podido descargar.
    - El resultado se **corrige con las estaciones XEMA del mismo día**. Cerca de cada estación, el mapa se ajusta a lo que ha medido el pluviómetro. Lejos de las estaciones, se aplica la corrección media del día.
3. **Acumulados semanales (lunes–domingo) y mensuales.** Son la suma de los diarios. Solo se cuentan los días en que alguna estación ha registrado al menos 1 mm, para evitar sumar ecos falsos del radar en días secos.
4. **Conservación.** Los mapas diarios se conservan unos 2–3 meses. Los semanales y los mensuales, indefinidamente.

Todo el proceso se ejecuta automáticamente con GitHub Actions y los resultados se publican en esta página.

## Fiabilidad

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

## Cómo usar el mapa

- **DIARI / SETMANAL / MENSUAL:** elige la escala temporal. Con el calendario y las flechas ◀ ▶ cambias de fecha.
- **Estaciones:** los números sobre el mapa son la lluvia medida por cada estación XEMA (mm).
- **Orientació:** muestra la orientación del relieve (a partir de zoom 8).
- **📍:** centra el mapa en tu ubicación.

## Datos y créditos

Datos de radar y de estaciones: **Servei Meteorològic de Catalunya (Meteocat)**. PlujaCat es un proyecto independiente, sin ninguna vinculación con el Meteocat. Código: [github.com/albverfar123/plujacat](https://github.com/albverfar123/plujacat).
