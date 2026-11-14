# Overdracht

Stand op 2026-11-14.

## Klaar in v0.2.1
- v0.2.0 printte "Make My Vase"-modellen (Stratos Pillar) als gladde vaas zonder ribben:
  `minimum_polygon_circumference = 20` gooide elke rib (omtrek ~8 mm) weg voordat hij met de kern samensmolt.
  Die instelling is weg. De e2e keurde dat goed omdat een gladde spiraal ook een nette spiraal is; hij vergelijkt
  nu de breedte van de print met die van het model (`MAX_SHRINK_MM`).

## Klaar in v0.2.0
- "Make My Vase"-modellen (kern + ribben die net niet raken): `xy_offset = 0.05`.
  Testmodel `gap_ribs.stl` (ribben op 0,002 mm van de kern) faalt zonder die instelling en slaagt ermee.
- Bambu *negative parts* (VASO_CALLE.3mf, de Calla Lily-vaas van MakerWorld). Cura's 3MF-lezer laat zo'n part
  helemaal weg en negeert de schaal per part. De plugin leest het part zelf uit de 3MF, zet het als
  `cutting_mesh` zonder wanden/vulling in een groep met het model, zet de schaal terug als het model dan nog past,
  en zet een model dat over de bedrand hangt in het midden (Cura t/m 5.13 doet dat niet zelf).
  Testmodel `bambu_negative_part.3mf`; de e2e controleert dat er geen plastic in het gat komt.

## Lokaal testen
- Echte bestanden (niet in git, auteursrecht): `tests/fixtures/private/` (ook op `loek@embedded-nuc`, zelfde pad).
- Altijd in Docker met `--memory`: zonder limiet kan een op hol geslagen CuraEngine de pc vastzetten.
- `send_engine_crash = False` in het testprofiel is nodig: met crash-rapportage (Sentry) aan groeit CuraEngine op
  sommige machines ~1 GB/s en wordt hij gekild (-9). Staat in `tests/e2e/run_e2e.py`.

## Bekend
- Open punt uit de vorige overdracht (materiaal binnen r<40 mm boven z≈190 bij VASO_CALLE) is verklaard: het
  negative part is geen zuivere cilinder maar loopt bovenaan taps toe (r 40 → 35 → punt), dus het gat wordt daar
  smaller. De transform uit `3D/3dmodel.model` (z-schaal 1.0099, +30.77) is de juiste; de `matrix` in
  `model_settings.config` wordt niet gebruikt.
- VASO_CALLE is op ware grootte 200,0 mm hoog en past dus net niet op een Ultimaker S3 (200 mm); de plugin laat
  hem dan op de grootte die Cura opende en meldt dat.
- Bambu *modifier parts* en *support enforcers* laadt Cura ook niet; daar doet de plugin niets mee.
