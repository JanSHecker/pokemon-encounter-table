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
    # Renegade-Platinum-Caps. `place` zeigt im kompakten Frontend das Ace an;
    # das vollstaendige Set bleibt fuer API-Clients strukturiert im Katalog.
    "level_caps": [
        {
            "order": 1, "kind": "gym", "leader": "Roark", "place": "Cranidos", "cap": 16,
            "ace": "Cranidos", "item": "Sitrus Berry", "nature": "Hasty", "ability": "Rock Head (!)",
            "moves": ["Zen Headbutt", "Rock Tomb", "Thunder Punch", "Scary Face"],
        },
        {
            "order": 2, "kind": "gym", "leader": "Gardenia", "place": "Roserade", "cap": 26,
            "ace": "Roserade", "item": "Sitrus Berry", "nature": "Timid", "ability": "Technician",
            "moves": ["Magical Leaf", "Sludge", "Dazzling Gleam", "Extrasensory"],
        },
        {
            "order": 3, "kind": "gym", "leader": "Fantina", "place": "Mismagius", "cap": 33,
            "ace": "Mismagius", "item": "Sitrus Berry", "nature": "Naive", "ability": "Levitate",
            "moves": ["Shadow Ball", "Power Gem", "Calm Mind", "Dazzling Gleam"],
        },
        {
            "order": 4, "kind": "gym", "leader": "Maylene", "place": "Lucario", "cap": 39,
            "ace": "Lucario", "item": "Focus Sash", "nature": "Timid", "ability": "Adaptability (!)",
            "moves": ["Aura Sphere", "Flash Cannon", "Dark Pulse", "Agility"],
        },
        {
            "order": 5, "kind": "gym", "leader": "Wake", "place": "Floatzel", "cap": 44,
            "ace": "Floatzel", "item": "Life Orb", "nature": "Naive", "ability": "Swift Swim",
            "moves": ["Aqua Tail", "Crunch", "Ice Punch", "Aqua Jet"],
        },
        {
            "order": 6, "kind": "gym", "leader": "Byron", "place": "Bastiodon", "cap": 53,
            "ace": "Bastiodon", "item": "Leftovers", "nature": "Sassy", "ability": "Soundproof",
            "moves": ["Iron Head", "Toxic", "Protect", "Metal Burst"],
        },
        {
            "order": 7, "kind": "gym", "leader": "Candice", "place": "Froslass", "cap": 56,
            "ace": "Froslass", "item": "Life Orb", "nature": "Modest", "ability": "Levitate (!)",
            "moves": ["Blizzard", "Shadow Ball", "Thunderbolt", "Attract"],
        },
        {
            "order": 8, "kind": "gym", "leader": "Volkner", "place": "Electivire", "cap": 62,
            "ace": "Electivire", "item": "Life Orb", "nature": "Jolly", "ability": "Motor Drive",
            "moves": ["Wild Charge", "Close Combat", "Ice Punch", "Earthquake"],
        },
        {
            "order": 9, "kind": "elite", "leader": "Aaron", "place": "Drapion", "cap": 72,
            "ace": "Drapion", "item": "Scope Lens", "nature": "Naive", "ability": "Sniper",
            "moves": ["Cross Poison", "Night Slash", "X-Scissor", "Earthquake"],
        },
        {
            "order": 10, "kind": "elite", "leader": "Bertha", "place": "Rhyperior", "cap": 73,
            "ace": "Rhyperior", "item": "Choice Band", "nature": "Naughty", "ability": "Solid Rock",
            "moves": ["Earthquake", "Stone Edge", "Megahorn", "Fire Punch"],
        },
        {
            "order": 11, "kind": "elite", "leader": "Flint", "place": "Magmortar", "cap": 74,
            "ace": "Magmortar", "item": "Life Orb", "nature": "Modest", "ability": "Flame Body",
            "moves": ["Fire Blast", "Thunderbolt", "Aura Sphere", "Solar Beam"],
        },
        {
            "order": 12, "kind": "elite", "leader": "Lucian", "place": "Gallade", "cap": 75,
            "ace": "Gallade", "item": "Scope Lens", "nature": "Jolly", "ability": "Steadfast",
            "moves": ["Psycho Cut", "Close Combat", "Leaf Blade", "Night Slash"],
        },
        {
            "order": 13, "kind": "champion", "leader": "Cynthia", "place": "Garchomp", "cap": 78,
            "ace": "Garchomp", "item": "Yache Berry", "nature": "Hasty", "ability": "Rough Skin",
            "moves": ["Earthquake", "Outrage", "Stone Edge", "Swords Dance"],
        },
        {
            "order": 14, "kind": "rematch", "leader": "Cynthia R2", "place": "Rayquaza", "cap": 89,
            "ace": "Rayquaza", "item": "Focus Sash", "nature": "?", "ability": "Air Lock",
            "moves": ["Outrage", "Earthquake", "Overheat", "Dragon Dance"],
        },
    ],
}
