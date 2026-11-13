# Overdracht (werk in uitvoering)

Stand op 2026-11-13, voor een nieuwe Claude Code-sessie op een machine met meer geheugen.

## Klaar
- Plugin v0.1.0 gereleased; CI (unit + echte Cura 5.12.1 / 5.13.0 / nieuwste, wekelijks op maandag) groen.
- **Nieuw, nog niet in een release:** fix voor MakerWorld "Make My Vase"-modellen (kern + tientallen rib-lichamen
  die net niet raken, bv. Stratos Pillar). Cura hield de rib-uiteinden als losse eilandjes en trok in vaasmodus
  extrusielijnen dwars door de vaas (tot 122 mm). Fix in `plugin/Ultifixer/vase_settings.py`:
  `xy_offset = 0.05` (per extruder) en `minimum_polygon_circumference = 20` (globaal).
  Gemeten met CuraEngine 5.13 op de echte Stratos: 569 → 4 lagen met sprongen, langste lijn 122 → 3,6 mm,
  filament 92 → 40 cm³. V_za ongewijzigd.
- `tests/e2e/gcode_check.py` is strenger: per laag één aaneengesloten extrusie en geen extrusie > 15 mm.

## Nog te doen
1. **Testmodel met microspleten** toevoegen aan `tests/fixtures/make_fixtures.py` (ribben die de kern op ~0,002 mm
   missen) en in `tests/e2e/run_e2e.py` slicen, zodat CI dit probleem vangt. Het huidige `ribbed_pillar.stl`
   overlapt te ruim en reproduceert het niet.
2. **Bambu "negative parts"** (VASO_CALLE.3mf): dicht vaasblok + cilinder met `subtype="negative_part"` in
   `Metadata/model_settings.config`. Bambu snijdt die weg en print normaal (spiral_mode 0, 2 wanden, 10% infill).
   Cura laadt de cilinder als gewoon mesh → vaas massief. Plan: in de plugin bij een Bambu-3MF de parts met
   `negative_part` mappen op de child-nodes van de groep (volgorde van `<component>` in 3D/3dmodel.model) en
   per-object instellen: `cutting_mesh=True`, `wall_line_count=0`, `infill_sparse_density=0`, `top_layers=0`,
   `bottom_layers=0`, `initial_bottom_layers=0`. Modifier/support-parts (`modifier_part`, `support_blocker`,
   `support_enforcer`) niet laten printen (bv. `anti_overhang_mesh=True`). Eerst met CuraEngine verifiëren dat de
   cutting mesh echt een leeg gat met binnenwand geeft, daarna e2e-fixture (Bambu-3MF met negatieve cilinder) en
   check "geen extrusie binnen de gatstraal".
3. Daarna CI groen → tag `v0.2.0` (release-job publiceert pakket + handleiding).

## Lokaal testen
- Echte bestanden (niet in git, auteursrecht): `tests/fixtures/private/` (V_za.stl, Stratos_Pillar_S.3mf,
  VASO_CALLE.3mf).
- Hulpscripts voor CuraEngine-only slicen en G-code-analyse staan niet in de repo; `tests/e2e/run_e2e.py` draait de
  volledige Cura (Linux AppImage onder Xvfb), zie `.github/workflows/ci.yml` voor de benodigde pakketten.
