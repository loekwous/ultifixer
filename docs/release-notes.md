**Installeren:** download `Ultifixer.curapackage`, sleep het op het Cura-venster, klik OK en start Cura opnieuw.
Stap voor stap met plaatjes: `Ultifixer-handleiding.pdf`.

- Bambu Studio-, OrcaSlicer- en PrusaSlicer-3MF met vaasmodus: Cura-vaasmodus gaat vanzelf aan.
- STL en 3MF zonder instellingen: herkend aan de vorm, anders via *Extensies › Ultifixer › Maak er een vaas van*.
- **Nieuw in 0.2:** Bambu-3MF met een uitsparing (*negative part*): Cura print die als massief blok; Ultifixer maakt
  er weer een gat van en zet het model op de bedoelde grootte en midden op het bed.
- **Nieuw in 0.2:** "Make My Vase"-modellen (kern met losse ribben, zoals Stratos Pillar) geven geen lijnen dwars
  door de vaas meer.
- Melding met *Ongedaan maken* en *Niet meer automatisch*; vaas van het bed = gewone instellingen terug.
- Wand past bij de nozzle (max. 1,5 × nozzle; AA 0.4 → 0,6 mm).

Getest in GitHub Actions met UltiMaker Cura 5.12.1, 5.13.0 en de nieuwste Cura-release (installeren uit het pakket,
bestanden openen, slicen, G-code controleren op een holle spiraal).
