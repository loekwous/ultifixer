# Ultifixer

Cura-plugin die vazen van MakerWorld / Bambu Lab hol laat printen.

Veel vazen op MakerWorld zijn een **massieve** vorm. Bambu Studio print ze hol omdat de 3MF
de instelling *vaasmodus* (`spiral_mode`) meestuurt. Cura leest alleen de vorm en print dus
een vol blok. Ultifixer herkent zo'n vaas bij het openen en zet Cura's eigen vaasmodus
(**Spiralize Outer Contour**) aan, met een wand en bodem die bij je nozzle passen.

- **3MF** van Bambu Studio, OrcaSlicer of PrusaSlicer met vaasmodus: altijd herkend.
- **STL** (en 3MF zonder slicer-instellingen): herkend aan de vorm (dicht, één omtrek op elke hoogte,
  vlakke bodem, open rand). Lukt dat niet: *Extensies › Ultifixer › Maak er een vaas van*.
- **Bambu-3MF met een uitsparing** (*negative part*, bijvoorbeeld het gat van een vaas die met wanden en
  vulling geprint wordt): Cura laat die uitsparing weg en print een massief blok. Ultifixer zet hem terug als gat,
  zet het model op de bedoelde grootte (als dat op je printer past) en midden op het bed.
- Melding met **Ongedaan maken** en **Niet meer automatisch**. Vaas van het bed gehaald? Dan gaan de gewone
  instellingen vanzelf terug.

Getest met UltiMaker Cura 5.12, 5.13 en 5.14 (end-to-end in GitHub Actions, elke maandag opnieuw tegen de nieuwste Cura).

**Bekend:** Bambu *modifier parts* en *support enforcers* laadt Cura niet; daar doet Ultifixer niets mee.
Past een model op de bedoelde grootte niet op je printer, dan blijft het op de grootte die Cura opende en meldt
Ultifixer dat.

## Installeren

Download `Ultifixer.curapackage` van de [laatste release](https://github.com/loekwous/ultifixer/releases/latest),
sleep het op het Cura-venster en start Cura opnieuw. De handleiding (PDF) staat bij dezelfde release.

## Ontwikkelen

```bash
python -m pip install numpy pytest
python tests/fixtures/make_fixtures.py
python -m pytest tests/unit
python scripts/build_package.py
```

End-to-end in een echte Cura (Linux, Xvfb): zie `tests/e2e/run_e2e.py` en `.github/workflows/ci.yml`.
Lokaal draait dat het snelst in Docker, één container per Cura-versie en altijd met een geheugenlimiet
(`docker run --memory 4g ...`); `--only <regex>` draait alleen de scenario's die je nodig hebt.
Zonder limiet kan een op hol geslagen CuraEngine de pc vastzetten. Het testprofiel zet `send_engine_crash = False`:
met crash-rapportage aan groeit CuraEngine op sommige machines snel tot hij gekild wordt.

Echte MakerWorld-bestanden (niet in git, auteursrecht) horen in `tests/fixtures/private/`; de tests die ze nodig
hebben slaan zichzelf over als ze ontbreken.
