"""Kuratierte Spieldefinition fuer Pokémon Renegade Platinum.

Renegade Platinum ist ein Hack von Platin. Orte und Reihenfolge sind dieselben
(sie stehen in _sinnoh.py und werden geteilt), die Level-Caps nicht: der Hack
zieht die Level deutlich an und schiebt Rivalen- und Team-Galaktik-Kaempfe als
eigene Huerden dazwischen.

**Die Wild-Encounter des Hacks kennt PokeAPI nicht.** Der Katalog traegt deshalb
die Listen von Platin; im Hack steht an vielen Orten etwas anderes. Die Auswahl
im Frontend zeigt ohnehin den ganzen Pokedex, die Ortsliste ist nur der
Vorschlag oben - fuer einen Renegade-Run ist sie ein Anhaltspunkt, keine Regel.

Aufbau wie tools/games/platinum.py - siehe dort fuer die Feldbedeutungen.
"""

from _sinnoh import LOCATIONS

GAME = {
    "id": "renegade-platinum",
    "name": "Pokémon Renegade Platin",
    # Der Hack laeuft auf Platin - die Encounter-Listen kommen aus dieser Version.
    "versions": ["platinum"],
    # National-Dex bis Generation 4 - so weit reicht die Auswahlliste im Frontend.
    "dex_max": 493,
    "locations": LOCATIONS,
    # Ein Eintrag pro Kampf, der ein Cap setzt - nicht nur die Arenen. Der Hack
    # verlangt auch bei Mars, Barry und Zyrus ein Team auf Hoehe, und ohne diese
    # Zwischenstufen springt die Karte von 16 auf 26.
    #
    # `leader` und `place` sind die deutschen Namen (sie stehen so auf der Karte:
    # "Veit · Erzelingen"), `ace` und die Teamdetails sind die englischen des
    # Hacks - sie kommen aus dessen Dokumentation und bleiben unuebersetzt.
    #
    # `type` ist der Typ des Kampfes: er faerbt Badge und Zeitleiste der
    # Cap-Karte. Leer heisst "gemischt" und wird grau dargestellt - Team Galaktik,
    # Rivale und Champion haben keinen festen Typ.
    "level_caps": [
        {
            "order": 1, "kind": "gym", "leader": "Veit", "place": "Erzelingen", "cap": 16, "type": "rock",
            "ace": "Cranidos", "item": "Sitrus Berry", "nature": "Hasty", "ability": "Rock Head (!)",
            "moves": ["Zen Headbutt", "Rock Tomb", "Thunder Punch", "Scary Face"],
        },
        {"order": 2, "kind": "team", "leader": "Mars", "place": "Wetterstation", "cap": 19, "type": ""},
        {
            "order": 3, "kind": "gym", "leader": "Silvana", "place": "Ewigenau", "cap": 26, "type": "grass",
            "ace": "Roserade", "item": "Sitrus Berry", "nature": "Timid", "ability": "Technician",
            "moves": ["Magical Leaf", "Sludge", "Dazzling Gleam", "Extrasensory"],
        },
        {
            "order": 4, "kind": "gym", "leader": "Lamina", "place": "Herzhofen", "cap": 33, "type": "ghost",
            "ace": "Mismagius", "item": "Sitrus Berry", "nature": "Naive", "ability": "Levitate",
            "moves": ["Shadow Ball", "Power Gem", "Calm Mind", "Dazzling Gleam"],
        },
        {
            "order": 5, "kind": "gym", "leader": "Hilda", "place": "Schleiede", "cap": 39, "type": "fighting",
            "ace": "Lucario", "item": "Focus Sash", "nature": "Timid", "ability": "Adaptability (!)",
            "moves": ["Aura Sphere", "Flash Cannon", "Dark Pulse", "Agility"],
        },
        {
            "order": 6, "kind": "gym", "leader": "Marinus", "place": "Weideburg", "cap": 44, "type": "water",
            "ace": "Floatzel", "item": "Life Orb", "nature": "Naive", "ability": "Swift Swim",
            "moves": ["Aqua Tail", "Crunch", "Ice Punch", "Aqua Jet"],
        },
        {"order": 7, "kind": "rival", "leader": "Barry", "place": "Fleetburg", "cap": 49, "type": ""},
        {
            "order": 8, "kind": "gym", "leader": "Adam", "place": "Fleetburg", "cap": 53, "type": "steel",
            "ace": "Bastiodon", "item": "Leftovers", "nature": "Sassy", "ability": "Soundproof",
            "moves": ["Iron Head", "Toxic", "Protect", "Metal Burst"],
        },
        {
            "order": 9, "kind": "gym", "leader": "Frida", "place": "Blizzach", "cap": 56, "type": "ice",
            "ace": "Froslass", "item": "Life Orb", "nature": "Modest", "ability": "Levitate (!)",
            "moves": ["Blizzard", "Shadow Ball", "Thunderbolt", "Attract"],
        },
        {"order": 10, "kind": "team", "leader": "Zyrus", "place": "Speersäule", "cap": 60, "type": ""},
        {
            "order": 11, "kind": "gym", "leader": "Volkner", "place": "Sonnewik", "cap": 62, "type": "electric",
            "ace": "Electivire", "item": "Life Orb", "nature": "Jolly", "ability": "Motor Drive",
            "moves": ["Wild Charge", "Close Combat", "Ice Punch", "Earthquake"],
        },
        {
            "order": 12, "kind": "elite", "leader": "Herbaro", "place": "Top Vier", "cap": 72, "type": "bug",
            "ace": "Drapion", "item": "Scope Lens", "nature": "Naive", "ability": "Sniper",
            "moves": ["Cross Poison", "Night Slash", "X-Scissor", "Earthquake"],
        },
        {
            "order": 13, "kind": "elite", "leader": "Teresa", "place": "Top Vier", "cap": 73, "type": "ground",
            "ace": "Rhyperior", "item": "Choice Band", "nature": "Naughty", "ability": "Solid Rock",
            "moves": ["Earthquake", "Stone Edge", "Megahorn", "Fire Punch"],
        },
        {
            "order": 14, "kind": "elite", "leader": "Ignaz", "place": "Top Vier", "cap": 74, "type": "fire",
            "ace": "Magmortar", "item": "Life Orb", "nature": "Modest", "ability": "Flame Body",
            "moves": ["Fire Blast", "Thunderbolt", "Aura Sphere", "Solar Beam"],
        },
        {
            "order": 15, "kind": "elite", "leader": "Lucian", "place": "Top Vier", "cap": 75, "type": "psychic",
            "ace": "Gallade", "item": "Scope Lens", "nature": "Jolly", "ability": "Steadfast",
            "moves": ["Psycho Cut", "Close Combat", "Leaf Blade", "Night Slash"],
        },
        {
            "order": 16, "kind": "champion", "leader": "Cynthia", "place": "Champ", "cap": 78, "type": "",
            "ace": "Garchomp", "item": "Yache Berry", "nature": "Hasty", "ability": "Rough Skin",
            "moves": ["Earthquake", "Outrage", "Stone Edge", "Swords Dance"],
        },
        # Der Rematch nach der Liga - Postgame, deshalb hinter dem Champion.
        {
            "order": 17, "kind": "rematch", "leader": "Cynthia", "place": "Rematch", "cap": 89, "type": "",
            "ace": "Rayquaza", "item": "Focus Sash", "nature": "?", "ability": "Air Lock",
            "moves": ["Outrage", "Earthquake", "Overheat", "Dragon Dance"],
        },
    ],
}
