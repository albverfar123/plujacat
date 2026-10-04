# Comprovacions de xarxes (2026-10-04 10:34 UTC)

## 1. ACA vs XEMA (pluviòmetres a < 1 km)
- ⚠️ XEMA UD 2026-09-28: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/09/28?codiEstacio=UD
- ⚠️ XEMA UD 2026-09-29: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/09/29?codiEstacio=UD
- ⚠️ XEMA UD 2026-09-30: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/09/30?codiEstacio=UD
- 2026-09-29: fet
- ⚠️ XEMA UD 2026-10-02: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/10/02?codiEstacio=UD
- ⚠️ XEMA UD 2026-10-03: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/10/03?codiEstacio=UD
- ⚠️ XEMA UD 2026-10-04: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/10/04?codiEstacio=UD
- 2026-10-03: fet
- ⚠️ XEMA UD 2026-09-08: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/09/08?codiEstacio=UD
- ⚠️ XEMA UD 2026-09-09: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/09/09?codiEstacio=UD
- ⚠️ XEMA UD 2026-09-10: 400 Client Error: Bad Request for url: https://api.meteo.cat/xema/v1/variables/mesurades/35/2026/09/10?codiEstacio=UD
- 2026-09-09: fet
- 11 parelles, 10829 registres ACA, 3972 registres XEMA → comparacio_aca_xema.csv

## 2. Profunditat de l'històric de l'ACA
- fa 60 dies (2026-08-05): 72 observacions en 6 h
- fa 120 dies (2026-06-06): 0 observacions en 6 h
- fa 240 dies (2026-02-06): 0 observacions en 6 h
- fa 365 dies (2025-10-04): 0 observacions en 6 h
- fa 730 dies (2024-10-04): 0 observacions en 6 h
- fa 1500 dies (2022-08-26): 0 observacions en 6 h

## 3. AEMET climatologies diàries
- todas_3dies: HTTP 200, datos 200, n=2482, 
    - `fecha`: fecha del dia (AAAA-MM-DD)
    - `prec`: PrecipitaciÃ³n diaria de 07 a 07
- estacio_0201D: HTTP 200, datos 500, n=None, Expecting value: line 1 column 1 (char 0)
    - `fecha`: fecha del dia (AAAA-MM-DD)
    - `prec`: PrecipitaciÃ³n diaria de 07 a 07

