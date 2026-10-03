## Què és PlujaCat?

PlujaCat és un visor de la **pluja acumulada a Catalunya** dels darrers mesos, a escala **diària, setmanal i mensual**, amb una resolució d'**1 km aproximadament**. Combina dues fonts de dades públiques del Servei Meteorològic de Catalunya (Meteocat):

- **El radar meteorològic**, que veu on plou amb molt detall espacial, però no mesura la quantitat amb precisió.
- **Les estacions automàtiques (XEMA)**, unes 187 a Catalunya, que mesuren la pluja real amb pluviòmetre, però només en punts concrets.

La idea és aprofitar el millor de cadascuna: el radar diu **on** ha plogut i les estacions diuen **quant**.

## Com funciona

1. **Captura del radar (cada 6 minuts).** Es descarrega la imatge del radar del Meteocat i cada color es converteix en una intensitat de pluja (mm/h).
2. **Acumulat diari.** Se sumen totes les imatges del dia (00–24 UTC):
    - Cada color es converteix amb una **taula calibrada** a partir de mesos de dades d'estacions.
    - Es compensen les imatges que no s'han pogut descarregar.
    - El resultat es **corregeix amb les estacions XEMA del mateix dia**. A prop de cada estació, el mapa s'ajusta al que ha mesurat el pluviòmetre. Lluny de les estacions, s'aplica la correcció mitjana del dia.
3. **Acumulats setmanals (dilluns–diumenge) i mensuals.** Són la suma dels diaris. Només es compten els dies en què alguna estació ha registrat almenys 1 mm, per evitar sumar ecos falsos del radar en dies secs.
4. **Conservació.** Els mapes diaris es conserven uns 2–3 mesos. Els setmanals i els mensuals, indefinidament.

Tot el procés s'executa automàticament amb GitHub Actions i els resultats es publiquen en aquesta pàgina.

## Fiabilitat

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

## Com fer servir el mapa

- **DIARI / SETMANAL / MENSUAL:** tria l'escala temporal. Amb el calendari i les fletxes ◀ ▶ canvies de data.
- **Estacions:** els números sobre el mapa són la pluja mesurada per cada estació XEMA (mm).
- **Orientació:** mostra l'orientació del relleu (a partir de zoom 8).
- **📍:** centra el mapa a la teva ubicació.

## Dades i crèdits

Dades de radar i d'estacions: **Servei Meteorològic de Catalunya (Meteocat)**. PlujaCat és un projecte independent, sense cap vinculació amb el Meteocat. Codi: [github.com/albverfar123/plujacat](https://github.com/albverfar123/plujacat).
