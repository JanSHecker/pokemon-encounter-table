"""Die Sinnoh-Ortsliste in Spielreihenfolge - geteilt von Platin und Renegade Platin.

Der Generator ueberspringt Dateien mit fuehrendem Unterstrich; hier steht also
keine Spieldefinition, sondern nur die Liste, die sich beide Editionen teilen.
Renegade Platinum ist ein Hack von Platin: dieselben Orte in derselben
Reihenfolge, andere Level-Caps. Die Wild-Encounter des Hacks kennt PokeAPI
nicht - beide Kataloge tragen deshalb die Listen von Platin.

Eintraege sind entweder ein PokeAPI-Slug oder ein Dict:
    "name"      Anzeigename statt des PokeAPI-Namens
    "species"   Pokemon-Liste manuell setzen (fuer Orte ohne Wild-Encounter)
    "postgame"  erst nach der Liga erreichbar

Staedte mit einem eigenen Encounter sind enthalten. Dazu zaehlen neben Surf- und
Angelstellen auch Geschenke und Eier; Staedte ohne irgendeinen Encounter laesst
der Generator weiterhin weg.
"""

LOCATIONS = [
    # Die Starter sind der Encounter von Route 201 und stehen bei PokeAPI genau
    # dort als Geschenk. Eine eigene Starter-Zeile waere dieselbe Wahl zweimal.
    "sinnoh-route-201",
    "twinleaf-town",
    {"id": "lake-verity", "name": "See der Wahrheit"},
    "sinnoh-route-202",
    "sinnoh-route-203",
    {"id": "oreburgh-gate", "name": "Erzelinger Tunnel"},
    {"id": "oreburgh-mine", "name": "Erzelingen-Mine"},
    "oreburgh-city",
    "sinnoh-route-207",
    "sinnoh-route-204",
    {"id": "ravaged-path", "name": "Verwüsteter Pfad"},
    {"id": "valley-windworks", "name": "Windkraftwerk"},
    "sinnoh-route-205",
    {"id": "eterna-forest", "name": "Ewigwald"},
    "eterna-city",
    {"id": "old-chateau", "name": "Alte Villa"},
    "sinnoh-route-211",
    "sinnoh-route-206",
    {"id": "wayward-cave", "name": "Bizarre Höhle"},
    "sinnoh-route-208",
    "hearthome-city",
    "sinnoh-route-209",
    "lost-tower",
    "solaceon-ruins",
    "sinnoh-route-210",
    "celestic-town",
    "sinnoh-route-215",
    "veilstone-city",
    "sinnoh-route-214",
    "valor-lakefront",
    "sinnoh-route-213",
    "pastoria-city",
    "great-marsh",
    "sinnoh-route-212",
    "fuego-ironworks",
    "sinnoh-route-218",
    "canalave-city",
    "sinnoh-route-219",
    "sinnoh-sea-route-220",
    "sinnoh-route-221",
    "sinnoh-route-222",
    "sunyshore-city",
    "iron-island",
    "lake-valor",
    "sinnoh-route-216",
    "sinnoh-route-217",
    "acuity-lakefront",
    "lake-acuity",
    {"id": "mt-coronet", "name": "Kraterberg"},
    "spear-pillar",
    "distortion-world",
    "sinnoh-victory-road",
    # Ab hier erst nach den Top Vier erreichbar.
    {"id": "sinnoh-sea-route-223", "postgame": True},
    {"id": "sinnoh-route-224", "postgame": True},
    {"id": "sinnoh-route-225", "postgame": True},
    {"id": "sinnoh-sea-route-226", "postgame": True},
    {"id": "sinnoh-route-227", "postgame": True},
    {"id": "sinnoh-route-228", "postgame": True},
    {"id": "sinnoh-route-229", "postgame": True},
    {"id": "sinnoh-sea-route-230", "postgame": True},
    {"id": "stark-mountain", "postgame": True},
    {"id": "turnback-cave", "postgame": True},
    {"id": "sendoff-spring", "postgame": True},
    {"id": "fullmoon-island", "postgame": True},
    {"id": "newmoon-island", "postgame": True},
    {"id": "snowpoint-temple", "postgame": True},
    # maniac-tunnel ist bei PokeAPI derselbe Ort mit derselben Liste - nur einmal fuehren.
    {"id": "ruin-maniac-cave", "postgame": True},
    {"id": "trophy-garden", "postgame": True},
    {"id": "floaroma-meadow", "postgame": True},
    {"id": "resort-area", "postgame": True},
    {"id": "seabreak-path", "postgame": True},
    {"id": "flower-paradise", "postgame": True},
    {"id": "spring-path", "postgame": True},
]
