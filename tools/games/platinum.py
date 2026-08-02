"""Kuratierte Spieldefinition fuer Pokémon Platin.

Was PokeAPI nicht liefert und deshalb von Hand steht:

* die Reihenfolge der Orte im Spielverlauf (die API kennt nur eine ungeordnete
  Liste aus 128 Sinnoh-"Locations" inklusive Shops und Battle Frontier)
* welche Orte ueberhaupt als Encounter zaehlen
* die Level-Caps

Die Ortsliste selbst steht in _sinnoh.py, weil Renegade Platin dieselbe benutzt.
Die Pokemon-Listen dazu erzeugt tools/build_game_catalog.py aus PokeAPI.
"""

from _sinnoh import LOCATIONS

GAME = {
    "id": "platinum",
    "name": "Pokémon Platin",
    "versions": ["platinum"],
    # National-Dex bis Generation 4 - so weit reicht die Auswahlliste im Frontend.
    "dex_max": 493,
    "locations": LOCATIONS,
    # Caps des unveraenderten Spiels: das hoechste Level im Team des jeweiligen
    # Gegners. Der Hack hat eigene - die stehen in renegade_platinum.py.
    #
    # `place` ist hier die Stadt, `type` der Typ des Kampfes (faerbt Badge und
    # Zeitleiste der Cap-Karte). Leer heisst "gemischt": die Champion hat keinen.
    #
    # Quelle: Recherche aus dem Design-Handoff, vor dem Livegang gegen die eigene
    # Quelle pruefen.
    "level_caps": [
        {"order": 1, "kind": "gym", "leader": "Veit", "place": "Erzelingen", "cap": 14, "type": "rock"},
        {"order": 2, "kind": "gym", "leader": "Silvana", "place": "Ewigenau", "cap": 22, "type": "grass"},
        {"order": 3, "kind": "gym", "leader": "Lamina", "place": "Herzhofen", "cap": 26, "type": "ghost"},
        {"order": 4, "kind": "gym", "leader": "Hilda", "place": "Schleiede", "cap": 32, "type": "fighting"},
        {"order": 5, "kind": "gym", "leader": "Marinus", "place": "Weideburg", "cap": 33, "type": "water"},
        {"order": 6, "kind": "gym", "leader": "Adam", "place": "Fleetburg", "cap": 39, "type": "steel"},
        {"order": 7, "kind": "gym", "leader": "Frida", "place": "Blizzach", "cap": 42, "type": "ice"},
        {"order": 8, "kind": "gym", "leader": "Volkner", "place": "Sonnewik", "cap": 49, "type": "electric"},
        {"order": 9, "kind": "elite", "leader": "Herbaro", "place": "Top Vier", "cap": 53, "type": "bug"},
        {"order": 10, "kind": "elite", "leader": "Teresa", "place": "Top Vier", "cap": 55, "type": "ground"},
        {"order": 11, "kind": "elite", "leader": "Ignaz", "place": "Top Vier", "cap": 57, "type": "fire"},
        {"order": 12, "kind": "elite", "leader": "Lucian", "place": "Top Vier", "cap": 59, "type": "psychic"},
        {"order": 13, "kind": "champion", "leader": "Cynthia", "place": "Champ", "cap": 62, "type": ""},
    ],
}
