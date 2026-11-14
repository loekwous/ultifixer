// Ultifixer: installatiehandleiding voor Cura (Windows).
// Bouwen: typst compile --font-path docs/fonts --input version=0.1.0 docs/handleiding.typ handleiding.pdf

#let version = sys.inputs.at("version", default: "dev")
#let release-url = "github.com/loekwous/ultifixer/releases/latest"

// ---------------------------------------------------------------- huisstijl
#let blue = rgb("#196EF0")
#let navy = rgb("#0E1A33")
#let ink = rgb("#1C2230")
#let muted = rgb("#5C6577")
#let line-c = rgb("#D5DBE5")
#let panel = rgb("#F3F6FA")
#let plate = rgb("#E4E8EE")
#let ok-green = rgb("#2E9E5B")

#set document(title: "Ultifixer handleiding", author: "Loek Lankhorst")
#set page(
  paper: "a4",
  margin: (x: 20mm, top: 22mm, bottom: 20mm),
  footer: context [
    #set text(8pt, fill: muted)
    Ultifixer #version #h(1fr) Geen officiële UltiMaker-plugin #h(1fr) #counter(page).display("1 / 1", both: true)
  ],
)
#set text(font: "Noto Sans", size: 10.5pt, fill: ink, lang: "nl")
#set par(leading: 0.65em, justify: false)
#show heading.where(level: 1): it => block(below: 10pt, text(20pt, weight: "bold", fill: navy, it.body))
#show heading.where(level: 2): it => block(above: 16pt, below: 8pt, text(13pt, weight: "bold", fill: navy, it.body))
#show strong: set text(weight: "bold")

// ---------------------------------------------------------------- tekenhulpjes
#let ui(body) = box(fill: panel, stroke: 0.6pt + line-c, inset: (x: 3pt, y: 1.5pt), outset: (y: 1pt), radius: 3pt, text(9pt, weight: "semibold", body))

#let arrow(from, to, color: blue, width: 2.2pt) = {
  let (x1, y1) = from
  let (x2, y2) = to
  let dx = (x2 - x1) / 1pt
  let dy = (y2 - y1) / 1pt
  let len = calc.sqrt(dx * dx + dy * dy)
  let ux = dx / len
  let uy = dy / len
  let head = 9
  let bx = x2 - ux * head * 1pt
  let by = y2 - uy * head * 1pt
  place(line(start: from, end: (bx, by), stroke: (paint: color, thickness: width, cap: "round")))
  place(polygon(fill: color,
    (x2, y2),
    (bx - uy * 5pt, by + ux * 5pt),
    (bx + uy * 5pt, by - ux * 5pt)))
}

#let window(title: "", w: 100%, ht: 120pt, bar: panel, title-color: ink, body) = box(width: w, height: ht,
  stroke: 0.8pt + line-c, radius: 5pt, clip: true, fill: white)[
  #box(width: 100%, height: 16pt, fill: bar, inset: (x: 6pt))[
    #set align(horizon)
    #text(8pt, weight: "semibold", fill: title-color, title) #h(1fr)
    #text(9pt, fill: title-color.lighten(30%))[–  ▢  ✕]
  ]
  #block(width: 100%, height: ht - 16pt, inset: 0pt, body)
]

#let cura-window(w: 100%, ht: 150pt, menu-open: false, body) = window(title: "UltiMaker Cura", w: w, ht: ht, bar: navy, title-color: white)[
  #box(width: 100%, height: 13pt, fill: white, inset: (x: 6pt), stroke: (bottom: 0.5pt + line-c))[
    #set align(horizon)
    #set text(6.5pt, fill: muted)
    Bestand #h(5pt) Bewerken #h(5pt) Beeld #h(5pt) Instellingen #h(5pt)
    #if menu-open { box(fill: blue, inset: (x: 3pt, y: 1.5pt), radius: 2pt, text(fill: white, weight: "bold")[Extensies]) } else [Extensies]
    #h(5pt) Voorkeuren #h(5pt) Help
  ]
  #block(width: 100%, height: 100% - 13pt, fill: plate, body)
]

#let cura-plate = place(center + horizon, dy: 14pt, polygon(fill: rgb("#CBD2DC"), stroke: 0.5pt + rgb("#B5BDC9"),
  (0pt, 0pt), (150pt, 0pt), (185pt, 38pt), (-35pt, 38pt)))

#let vase(scale: 1.0, hollow: false) = {
  let s = scale
  let body = polygon(fill: if hollow { blue.lighten(75%) } else { blue.lighten(35%) }, stroke: 1.2pt + blue.darken(10%),
    (8pt * s, 0pt), (30pt * s, 0pt), (27pt * s, 14pt * s), (36pt * s, 40pt * s), (30pt * s, 62pt * s),
    (8pt * s, 62pt * s), (2pt * s, 40pt * s), (11pt * s, 14pt * s))
  box(width: 38pt * s, height: 62pt * s, body)
}

#let file-icon(name, highlight: false) = box(width: 74pt)[
  #set align(center)
  #box(width: 30pt, height: 36pt, fill: if highlight { blue.lighten(85%) } else { white },
    stroke: 1pt + if highlight { blue } else { muted }, radius: (top-right: 8pt, rest: 2pt))[
    #set align(center + horizon)
    #text(7pt, weight: "bold", fill: blue)[CURA]
  ]
  #v(2pt)
  #text(7pt, weight: if highlight { "bold" } else { "regular" }, name)
]

#let cura-message(title, body, buttons: ()) = box(width: 230pt, fill: white, stroke: 0.8pt + line-c, radius: 6pt,
  inset: 8pt)[
  #set align(left)
  #text(8.5pt, weight: "bold", title) #h(1fr) #text(8pt, fill: muted)[✕] \
  #text(7.5pt, body)
  #if buttons.len() > 0 {
    v(3pt)
    for (i, b) in buttons.enumerate() {
      box(fill: if i == 0 { white } else { white }, stroke: 0.8pt + blue, radius: 10pt, inset: (x: 7pt, y: 3pt),
        text(7pt, weight: "semibold", fill: blue, b))
      h(4pt)
    }
  }
]

#let cursor = polygon(fill: white, stroke: 1pt + ink, (0pt, 0pt), (0pt, 14pt), (4pt, 10.5pt), (7pt, 16pt),
  (9pt, 15pt), (6pt, 9.5pt), (11pt, 9.5pt))

#let step(n, title, text-body, picture) = block(breakable: false, above: 14pt, below: 6pt)[
  #grid(columns: (26pt, 1fr), column-gutter: 10pt,
    circle(radius: 12pt, fill: blue, stroke: none)[#set align(center + horizon); #text(13pt, weight: "bold", fill: white, str(n))],
    [
      #text(13pt, weight: "bold", fill: navy, title)
      #v(-2pt)
      #text-body
      #v(4pt)
      #picture
    ])
]

// ================================================================ voorpagina
#block(width: 100%, fill: navy, inset: 18pt, radius: 8pt)[
  #grid(columns: (1fr, auto), align: horizon,
    [
      #text(30pt, weight: "bold", fill: white)[Ultifixer]
      #v(-10pt)
      #text(13pt, fill: white.darken(15%))[Vazen van MakerWorld hol printen in Cura]
    ],
    box(inset: (right: 10pt), grid(columns: 3, column-gutter: 10pt, align: horizon,
      vase(scale: 1.1, hollow: false), text(20pt, fill: white)[→], vase(scale: 1.1, hollow: true))),
  )
]

#v(6pt)
*Waarom?* Veel vazen op MakerWorld zijn getekend als een dicht blok. Bambu Lab-printers maken er een holle vaas
van omdat het bestand de instelling _vaasmodus_ meestuurt. Cura leest die instelling niet en print daarom
een massieve vaas vol vulling. Ultifixer ziet dat het een vaas is en zet in Cura de vaasmodus aan.

*Wat heb je nodig?* Een Windows-computer met UltiMaker Cura 5.12 of nieuwer. De installatie duurt een paar minuten
en hoef je maar één keer te doen.

#block(fill: panel, radius: 6pt, inset: 10pt, width: 100%)[
  #text(weight: "bold")[Het downloadadres] \
  #text(14pt, weight: "bold", fill: blue, release-url)
]

= Installeren

#step(1, "Download de plugin",
  [Typ het adres hierboven in je internetbrowser. Klik onder *Assets* op #ui[Ultifixer.curapackage].
   Het bestand komt in je map *Downloads*.],
  box(width: 100%, height: 122pt)[
    #window(title: "Ultifixer · loekwous/ultifixer", w: 300pt, ht: 118pt)[
      #pad(8pt)[
        #text(8pt, fill: muted)[#release-url] \
        #v(2pt)
        #text(11pt, weight: "bold")[Ultifixer #version] \
        #text(8pt, weight: "bold")[▾ Assets]
        #v(-2pt)
        #box(width: 100%, fill: blue.lighten(88%), stroke: 1pt + blue, radius: 3pt, inset: 4pt, text(8pt, weight: "bold", fill: blue)[Ultifixer.curapackage])
        #box(width: 100%, inset: 4pt, text(8pt)[Ultifixer-handleiding.pdf])
      ]
    ]
    #place(top + left, dx: 140pt, dy: 76pt, cursor)
  ])

#step(2, "Open Cura",
  [Start UltiMaker Cura zoals je altijd doet. Laat het venster open.],
  box(width: 100%, height: 84pt)[
    #cura-window(w: 300pt, ht: 80pt)[#cura-plate]
  ])

#v(1fr)
#block(breakable: false, fill: panel, radius: 6pt, inset: 10pt, width: 100%)[
  #set text(8.5pt, fill: muted)
  *Wat doet Ultifixer precies?* Het zet in Cura _Buitencontour Spiraliseren_ (vaasmodus) aan, met één wand
  van maximaal 1,5 × de nozzle, een dichte bodem (meestal 1 mm), geen vulling en geen bovenkant.
  Bij een 3MF van Bambu Studio, OrcaSlicer of PrusaSlicer leest het de vaasmodus uit het bestand. Bij een STL kijkt het naar
  de vorm: één dichte omtrek op elke hoogte, een vlakke bodem en een open rand.
  Broncode en vragen: #text(fill: blue)[github.com/loekwous/ultifixer].
]

#pagebreak()
#step(3, "Sleep het bestand op Cura",
  [Open de map *Downloads* (Verkenner). Pak #ui[Ultifixer.curapackage] met de muis vast en laat het los
   boven het Cura-venster, ergens op het grijze printbed.],
  box(width: 100%, height: 130pt)[
    #place(top + left, window(title: "Downloads", w: 150pt, ht: 120pt)[
      #pad(10pt)[#file-icon("Ultifixer.curapackage", highlight: true)]
    ])
    #place(top + left, dx: 200pt, cura-window(w: 260pt, ht: 120pt)[#cura-plate])
    #place(top + left, arrow((70pt, 62pt), (300pt, 82pt)))
    #place(top + left, dx: 298pt, dy: 78pt, cursor)
  ])

#step(4, "Klik op OK",
  [Cura zegt: _Dit package wordt na opnieuw starten geïnstalleerd._ Klik op #ui[OK].],
  box(width: 100%, height: 92pt)[
    #window(title: "Package installeren", w: 250pt, ht: 86pt)[
      #pad(10pt)[
        #text(9pt)[Dit package wordt na opnieuw starten geïnstalleerd.]
        #v(6pt)
        #align(right, box(fill: blue, radius: 10pt, inset: (x: 14pt, y: 4pt), text(9pt, weight: "bold", fill: white)[OK]))
      ]
    ]
    #place(top + left, dx: 236pt, dy: 74pt, cursor)
  ])

#step(5, "Sluit Cura en start het opnieuw",
  [Klik rechtsboven op het kruisje #ui[✕] om Cura te sluiten. Start Cura daarna opnieuw.
   Nu is Ultifixer geïnstalleerd.],
  box(width: 100%, height: 84pt)[
    #cura-window(w: 300pt, ht: 80pt)[#cura-plate]
    #place(top + left, dx: 278pt, dy: 1pt, circle(radius: 8pt, stroke: 2pt + rgb("#E0453A")))
  ])

#step(6, "Controleer het",
  [Klik in de menubalk op #ui[Extensies]. Zie je daar *Ultifixer*? Dan is alles klaar.],
  box(width: 100%, height: 120pt)[
    #cura-window(w: 300pt, ht: 116pt, menu-open: true)[]
    #place(top + left, dx: 152pt, dy: 46pt, box(width: 120pt, fill: white, stroke: 0.8pt + line-c, radius: 3pt, inset: 6pt)[
      #set text(8pt)
      Post-processing #h(1fr) ▸ \
      #box(width: 100%, fill: blue.lighten(85%), inset: 2pt)[*Ultifixer* #h(1fr) ▸]
    ])
    #place(top + left, dx: 272pt, dy: 60pt, box(width: 140pt, fill: white, stroke: 0.8pt + line-c, radius: 3pt, inset: 6pt)[
      #set text(8pt)
      Maak er een vaas van \
      Vaasmodus uitzetten \
      Automatisch herkennen aan/uit
    ])
  ])

#pagebreak()
= Een vaas printen

#step(7, "Open de vaas zoals altijd",
  [Open het bestand van MakerWorld (.3mf of .stl) zoals je gewend bent. Ultifixer kijkt mee. Is het een vaas,
   dan verschijnt er onderin een melding en staat de vaasmodus al aan. Zo ziet dat eruit in Cura:],
  box(width: 88%, stroke: 0.8pt + line-c, radius: 4pt, clip: true, image("img/cura-melding.png", width: 100%)))

#step(8, "Slicen en printen",
  [Klik zoals altijd op #ui[Slicen] en daarna op printen of opslaan. De vaas wordt één dunne wand, net als op de
   foto's op MakerWorld. In onze test: *20 g en 1 uur 16 minuten* in plaats van 94 g en 4 uur.
   Zie je ook een melding over een ongebruikte printkern (_Extruder 2_)? Die is normaal; je mag hem wegklikken.],
  [])

== Goed om te weten
#set list(spacing: 0.55em)
#set par(leading: 0.55em)

- *Iets anders printen?* Haal de vaas van het printbed. Ultifixer zet dan zelf de gewone instellingen terug.
- *Geen melding gezien?* Ultifixer twijfelde. Kies dan zelf #ui[Extensies] › #ui[Ultifixer] › #ui[Maak er een vaas van].
- *Toch geen vaas?* Klik in de melding op #ui[Ongedaan maken], of kies #ui[Extensies] › #ui[Ultifixer] › #ui[Vaasmodus uitzetten].
- *Liever niets automatisch?* Klik op #ui[Niet meer automatisch]. Via het menu kun je het later weer aanzetten.
- *Meerdere modellen tegelijk?* De vaasmodus geldt voor alles op het bed. Print een vaas daarom het liefst alleen.
- *Melding "uitsparing herkend"?* Sommige vazen zijn een dicht blok waar Bambu Studio een gat uit snijdt. Cura
  vergeet dat gat; Ultifixer zet het terug. Zo'n vaas print met gewone wanden en vulling, niet in vaasmodus.
- *Welke nozzle?* Ultifixer kijkt welke printkern erin zit. Met een AA 0.4 wordt de wand 0,6 mm.

== Verwijderen

Klik rechtsboven in Cura op #ui[Marktplaats] › #ui[Pakketten beheren]. Zoek *Ultifixer*, klik op
#ui[De-installeren] en start Cura opnieuw.

