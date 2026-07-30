"""Kuratierte Spieldefinition fuer Pokemon Platin.

Was PokeAPI nicht liefert und deshalb hier von Hand steht:

* die Reihenfolge der Orte im Spielverlauf (die API kennt nur eine ungeordnete
  Liste aus 128 Sinnoh-"Locations" inklusive Shops und Battle Frontier)
* welche Orte ueberhaupt als Encounter zaehlen
* die Level-Caps

Die Pokemon-Listen dazu erzeugt tools/build_game_catalog.py aus PokeAPI.

Eintraege sind entweder ein PokeAPI-Slug oder ein Dict:
    "name"      Anzeigename statt des PokeAPI-Namens
    "species"   Pokemon-Liste manuell setzen (fuer Orte ohne Wild-Encounter)
    "postgame"  erst nach der Liga erreichbar

Staedte mit einem eigenen Encounter sind enthalten. Dazu zaehlen neben Surf- und
Angelstellen auch Geschenke und Eier; Staedte ohne irgendeinen Encounter laesst
der Generator weiterhin weg.
"""

GAME = {
    "id": "platinum",
    "name": "Pokémon Platin",
    "versions": ["platinum"],
    # National-Dex bis Generation 4 - so weit reicht die Auswahlliste im Frontend.
    "dex_max": 493,
    "locations": [
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
        {"id": "ravaged-path", "name": "Ruinental"},
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
    ],
    # Cap = hoechstes Level im Team des jeweils naechsten Gegners.
    #
    # Achtung: Platin hat die Arenareihenfolge gegenueber Diamant/Perl geaendert -
    # Lamina (Herzhofen) ist hier die dritte Arena, nicht die fuenfte.
    #
    # Die Top-Vier-Level gelten fuer den ersten Durchgang; nach dem Kahlberg-Event
    # steigen sie deutlich an (Herbaro dann 69, Cynthia 78).
    #
    # Quelle: Bulbapedia, Stand Juli 2026, jeweils der Platin-Abschnitt.
    "level_caps": [
        {"order": 1, "kind": "gym", "leader": "Veit", "place": "Erzelingen", "cap": 14},
        {"order": 2, "kind": "gym", "leader": "Silvana", "place": "Ewigenau", "cap": 22},
        {"order": 3, "kind": "gym", "leader": "Lamina", "place": "Herzhofen", "cap": 26},
        {"order": 4, "kind": "gym", "leader": "Hilda", "place": "Schleiede", "cap": 32},
        {"order": 5, "kind": "gym", "leader": "Marinus", "place": "Weideburg", "cap": 37},
        {"order": 6, "kind": "gym", "leader": "Adam", "place": "Fleetburg", "cap": 41},
        {"order": 7, "kind": "gym", "leader": "Frida", "place": "Blizzach", "cap": 42},
        {"order": 8, "kind": "gym", "leader": "Volkner", "place": "Sonnewik", "cap": 50},
        {"order": 9, "kind": "elite", "leader": "Herbaro", "place": "Top Vier", "cap": 53},
        {"order": 10, "kind": "elite", "leader": "Teresa", "place": "Top Vier", "cap": 55},
        {"order": 11, "kind": "elite", "leader": "Ignaz", "place": "Top Vier", "cap": 57},
        {"order": 12, "kind": "elite", "leader": "Lucian", "place": "Top Vier", "cap": 59},
        {"order": 13, "kind": "champion", "leader": "Cynthia", "place": "Champion", "cap": 62},
    ],
}
