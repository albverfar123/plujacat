"""
Genera el README.md principal i la finestra d'informació de index.html a partir dels
textos de info/info_{ca,es,en}.md, perquè tots dos tinguin sempre el mateix contingut.

Ús (des de l'arrel del repo):  pip install markdown && python eines/generar_info.py
"""
import os
import re
import markdown

ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGS = [("ca", "Català"), ("es", "Castellano"), ("en", "English")]

ESTRUCTURA = """## Estructura del repositori · Estructura del repositorio · Repository layout

| | |
|---|---|
| `radar_to_nc.py` | Captura del radar cada 6 min → `dades_radar/` |
| `daily_accumulation.py` | Acumulat diari calibrat i corregit amb estacions → `acumulats_diaris/` |
| `weekly_accumulation.py` · `monthly_accumulation.py` | Acumulats setmanals i mensuals → `acumulats_setmanals/`, `acumulats_mensuals/` |
| `calibracio_radar.py` · `config_calibracio.json` | Calibració operativa (taula de colors + correcció amb estacions) |
| `validacio.py` · `validacio/` | Dades radar–estació per validar i recalibrar |
| `analisi/` | Notebooks de diagnosi i calibració ([resum](analisi/README.md)) |
| `eines/` | Scripts puntuals (reprocessar, extreure dades de l'historial, generar aquest README) |
| `.github/workflows/` | Automatització (GitHub Actions) |
| `index.html` | Visor web (Leaflet) |
"""


def llegir(lang):
    with open(os.path.join(ARREL, "info", f"info_{lang}.md"), encoding="utf-8") as f:
        return f.read().strip()


def readme():
    parts = ["# PlujaCat 🌧️", "",
             " · ".join(f"[{nom}](#{lang})" for lang, nom in LANGS), "",
             ]
    for lang, nom in LANGS:
        cos = llegir(lang).replace("\n## ", "\n### ")
        if cos.startswith("## "):
            cos = "#" + cos
        parts += [f'<a id="{lang}"></a>', "", f"# {nom}", "", cos, "", "---", ""]
    parts += [ESTRUCTURA]
    with open(os.path.join(ARREL, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def html():
    path = os.path.join(ARREL, "index.html")
    with open(path, encoding="utf-8") as f:
        s = f.read()
    blocs = []
    for i, (lang, _) in enumerate(LANGS):
        cos = markdown.markdown(llegir(lang), extensions=["tables"])
        cos = cos.replace("<a href=", '<a target="_blank" rel="noopener" href=')
        ocult = "" if i == 0 else " hidden"
        blocs.append(f'<div class="info-lang" data-lang="{lang}"{ocult}>\n{cos}\n</div>')
    nou = "<!-- INFO:START (generat per eines/generar_info.py, no editar a mà) -->\n" + \
          "\n".join(blocs) + "\n<!-- INFO:END -->"
    s2 = re.sub(r"<!-- INFO:START.*?<!-- INFO:END -->", lambda m: nou, s, flags=re.S)
    if s2 == s and "INFO:START" not in s:
        raise SystemExit("index.html no té els marcadors <!-- INFO:START --> ... <!-- INFO:END -->")
    with open(path, "w", encoding="utf-8") as f:
        f.write(s2)


if __name__ == "__main__":
    readme()
    html()
    print("README.md i index.html actualitzats")
