"""Kuratierte Spieldefinition fuer Pokémon Schwarz 2 und Weiß 2.

Aufbau wie tools/games/platinum.py - siehe dort fuer die Feldbedeutungen.

Zwei Eigenheiten dieser Edition:

* PokeAPI kennt die Jahreszeiten nicht. Die Pokémon-Liste je Ort fasst deshalb
  alle vier Jahreszeiten zusammen; im Spiel ist pro Jahreszeit nur ein Teil
  davon anzutreffen.
* Die Level-Caps gelten fuer den **Normal-Modus**. Easy und Challenge Mode haben
  abweichende Level (Challenge liegt rund 2 Level darueber).

Staedte sind wie bei Platin nicht enthalten, ausser sie liegen ohnehin im
Story-Verlauf und haben eigene Encounter.
"""

GAME = {
    "id": "black-2-white-2",
    "name": "Pokémon Schwarz 2 / Weiß 2",
    "versions": ["black-2", "white-2"],
    # National-Dex bis Generation 5 - so weit reicht die Auswahlliste im Frontend.
    "dex_max": 649,
    "locations": [
        # Die Starter gibt es in Eventura City; PokeAPI fuehrt sie dort als
        # Geschenk. Eine eigene Starter-Zeile waere dieselbe Wahl zweimal.
        "aspertia-city",
        "unova-route-19",
        "floccesy-town",
        "unova-route-20",
        "floccesy-ranch",
        "pledge-grove",
        "virbank-city",
        "virbank-complex",
        "castelia-city",
        "castelia-sewers",
        "unova-route-4",
        "desert-resort",
        "relic-castle",
        "nimbasa-city",
        "anville-town",
        "unova-route-16",
        "lostlorn-forest",
        "unova-route-5",
        "driftveil-drawbridge",
        "driftveil-city",
        "relic-passage",
        "unova-route-6",
        "mistralton-cave",
        "chargestone-cave",
        "mistralton-city",
        "unova-route-7",
        "celestial-tower",
        "lentimas-town",
        "strange-house",
        "reversal-mountain",
        "undella-town",
        "undella-bay",
        "unova-route-13",
        "lacunosa-town",
        "unova-route-12",
        "village-bridge",
        "unova-route-11",
        "opelucid-city",
        "unova-route-9",
        "marine-tube",
        "humilau-city",
        "unova-route-22",
        "unova-route-21",
        "seaside-cave",
        "giant-chasm",
        "unova-route-23",
        # Die Siegesstraße von Schwarz 2/Weiß 2 ist eine andere als die aus Schwarz/Weiß.
        "unova-victory-road-2",
        "unova-pokemon-league",
        # Ab hier Postgame: der halbe Westen Einalls wird erst nach der Liga zugaenglich.
        {"id": "nuvema-town", "postgame": True},
        {"id": "unova-route-1", "postgame": True},
        {"id": "accumula-town", "postgame": True},
        {"id": "unova-route-2", "postgame": True},
        {"id": "striaton-city", "postgame": True},
        {"id": "dreamyard", "postgame": True},
        {"id": "unova-route-3", "postgame": True},
        {"id": "wellspring-cave", "postgame": True},
        {"id": "nacrene-city", "postgame": True},
        {"id": "pinwheel-forest", "postgame": True},
        {"id": "unova-route-18", "postgame": True},
        {"id": "p2-laboratory", "postgame": True},
        {"id": "unova-route-17", "postgame": True},
        {"id": "unova-route-8", "postgame": True},
        {"id": "moor-of-icirrus", "postgame": True},
        {"id": "icirrus-city", "postgame": True},
        {"id": "twist-mountain", "postgame": True},
        {"id": "dragonspiral-tower", "postgame": True},
        {"id": "unova-route-14", "postgame": True},
        {"id": "abundant-shrine", "postgame": True},
        {"id": "unova-route-15", "postgame": True},
        {"id": "challengers-cave", "postgame": True},
        {"id": "cave-of-being", "postgame": True},
        {"id": "clay-tunnel", "postgame": True},
        {"id": "underground-ruins", "postgame": True},
        {"id": "abyssal-ruins", "postgame": True},
        {"id": "unova-route-10", "postgame": True},
        {"id": "black-city", "postgame": True},
        {"id": "white-forest", "postgame": True},
        {"id": "nature-sanctuary", "postgame": True},
        {"id": "liberty-garden", "postgame": True},
    ],
    # Cap = hoechstes Level im Team des jeweils naechsten Gegners, Normal-Modus.
    #
    # Die Top Vier laesst sich in beliebiger Reihenfolge angehen, deshalb ein
    # gemeinsames Cap statt vier einzelner: 58 ist das hoechste Level der vier.
    #
    # Quelle: Bulbapedia, Stand Juli 2026, jeweils der Abschnitt Schwarz 2/Weiß 2.
    #
    # `type` ist der Typ des Kampfes (faerbt Badge und Zeitleiste der Cap-Karte);
    # die Top Vier deckt vier Typen ab und bleibt deshalb leer = "gemischt".
    "level_caps": [
        {"order": 1, "kind": "gym", "leader": "Cheren", "place": "Eventura City", "cap": 13, "type": "normal"},
        {"order": 2, "kind": "gym", "leader": "Mica", "place": "Vapydro City", "cap": 18, "type": "poison"},
        {"order": 3, "kind": "gym", "leader": "Artie", "place": "Stratos City", "cap": 24, "type": "bug"},
        {"order": 4, "kind": "gym", "leader": "Kamilla", "place": "Rayono City", "cap": 30, "type": "electric"},
        {"order": 5, "kind": "gym", "leader": "Turner", "place": "Marea City", "cap": 33, "type": "ground"},
        {"order": 6, "kind": "gym", "leader": "Géraldine", "place": "Panaero City", "cap": 36, "type": "flying"},
        {"order": 7, "kind": "gym", "leader": "Lysander", "place": "Twindrake City", "cap": 44, "type": "dragon"},
        {"order": 8, "kind": "gym", "leader": "Benson", "place": "Abidaya City", "cap": 51, "type": "water"},
        {"order": 9, "kind": "elite", "leader": "Top Vier", "place": "Anissa · Eugen · Astor · Kattlea", "cap": 58, "type": ""},
        {"order": 10, "kind": "champion", "leader": "Lilia", "place": "Champion", "cap": 59, "type": "dragon"},
    ],
}
