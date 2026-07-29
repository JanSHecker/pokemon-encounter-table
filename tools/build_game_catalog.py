"""Erzeugt die Spielkataloge in data/games/ aus PokeAPI-Daten.

Der Katalog wird committed; die laufende API holt nichts von PokeAPI nach. Dieses
Skript wird nur ausgefuehrt, wenn eine Spieldefinition in tools/games/ geaendert
wurde.

    python tools/build_game_catalog.py --game platinum
    python tools/build_game_catalog.py --all --check

Antworten landen in tools/.cache/, damit wiederholte Laeufe PokeAPI nicht erneut
belasten. Cache loeschen erzwingt frische Daten.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://pokeapi.co/api/v2"
USER_AGENT = "pokemon-encounter-table/1.0 (catalog builder)"
REQUEST_DELAY_SECONDS = 0.2
MAX_ATTEMPTS = 3

TOOLS_DIR = Path(__file__).resolve().parent
CACHE_DIR = TOOLS_DIR / ".cache"
GAMES_DIR = TOOLS_DIR / "games"
OUTPUT_DIR = TOOLS_DIR.parent / "data" / "games"

# PokeAPI-Methoden auf die Begriffe, die im Frontend stehen sollen.
METHOD_NAMES = {
    "walk": "Grasland",
    "grass-spots": "Raschelndes Gras",
    "dark-grass": "Dunkles Gras",
    "cave-spots": "Staubwolke",
    "bridge-spots": "Vogelschatten",
    "surf": "Surfen",
    "surf-spots": "Wasserwirbel",
    "old-rod": "Angel",
    "good-rod": "Angel",
    "super-rod": "Angel",
    "super-rod-spots": "Wasserwirbel (Angel)",
    "rock-smash": "Zertruemmerer",
    "headbutt": "Kopfnuss",
    "gift": "Geschenk",
    "gift-egg": "Ei",
    "only-one": "Einzelbegegnung",
}


class CatalogError(RuntimeError):
    """Bricht den Lauf ab, statt einen halben Katalog zu schreiben."""


def fetch(path: str) -> dict[str, Any]:
    """GET auf die PokeAPI, mit Cache auf Platte."""
    cache_file = CACHE_DIR / f"{path.strip('/').replace('/', '_')}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    url = f"{API_ROOT}/{path.strip('/')}/"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise CatalogError(f"PokeAPI kennt '{url}' nicht.") from exc
            if attempt == MAX_ATTEMPTS:
                raise CatalogError(f"PokeAPI antwortete {exc.code} fuer '{url}'.") from exc
            time.sleep(attempt * 2)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise CatalogError(f"PokeAPI nicht erreichbar: {url}") from exc
            time.sleep(attempt * 2)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    time.sleep(REQUEST_DELAY_SECONDS)
    return payload


def german_name(entry: dict[str, Any], fallback: str) -> str:
    for name in entry.get("names", []):
        if name["language"]["name"] == "de":
            return name["name"]
    return fallback


def species_entry(pokemon_slug: str) -> dict[str, Any]:
    """Deutschen Namen und National-Dex-Nummer zu einem Encounter-Eintrag holen."""
    pokemon = fetch(f"pokemon/{pokemon_slug}")
    species_slug = pokemon["species"]["name"]
    species = fetch(f"pokemon-species/{species_slug}")
    return {
        "species": species_slug,
        "name": german_name(species, species_slug),
        "dex": species["id"],
    }


def collect_encounters(location_slug: str, versions: set[str]) -> list[dict[str, Any]]:
    """Alle Areas eines Ortes zusammenfuehren (Kraterberg hat allein 13)."""
    location = fetch(f"location/{location_slug}")
    by_species: dict[str, dict[str, Any]] = {}

    for area_ref in location["areas"]:
        area = fetch(f"location-area/{area_ref['name']}")
        for encounter in area["pokemon_encounters"]:
            methods: set[str] = set()
            for version_detail in encounter["version_details"]:
                if version_detail["version"]["name"] not in versions:
                    continue
                for detail in version_detail["encounter_details"]:
                    methods.add(detail["method"]["name"])
            if not methods:
                continue

            entry = species_entry(encounter["pokemon"]["name"])
            existing = by_species.setdefault(entry["species"], {**entry, "methods": set()})
            existing["methods"].update(methods)

    return [
        {**entry, "methods": sorted({METHOD_NAMES.get(m, m) for m in entry["methods"]})}
        for entry in sorted(by_species.values(), key=lambda e: e["dex"])
    ]


def build_location(raw: str | dict[str, Any], versions: set[str]) -> dict[str, Any] | None:
    """Einen kuratierten Listeneintrag zu einem Katalog-Ort aufloesen.

    Eintraege sind entweder ein PokeAPI-Slug oder ein Dict mit Overrides.
    'species' setzt die Liste manuell (fuer Orte, die PokeAPI nicht als
    Encounter fuehrt, etwa die Starterwahl).
    """
    spec: dict[str, Any] = {"id": raw} if isinstance(raw, str) else dict(raw)
    location_id = spec["id"]

    if "species" in spec:
        encounters = [species_entry(slug) | {"methods": [spec.get("method", "Geschenk")]} for slug in spec["species"]]
        name = spec.get("name") or location_id
    else:
        encounters = collect_encounters(location_id, versions)
        name = spec.get("name") or german_name(fetch(f"location/{location_id}"), location_id)

    excluded = set(spec.get("exclude_methods", ()))
    if excluded:
        filtered = []
        for entry in encounters:
            methods = [method for method in entry["methods"] if method not in excluded]
            if methods:
                filtered.append({**entry, "methods": methods})
        encounters = filtered

    if not encounters:
        print(f"  uebersprungen (keine Encounter): {location_id}", file=sys.stderr)
        return None

    # 'order' vergibt build_catalog, sobald feststeht, welche Orte uebrig bleiben.
    location = {"id": location_id, "order": 0, "name": name, "encounters": encounters}
    if spec.get("postgame"):
        location["postgame"] = True
    return location


def load_game_definitions() -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for path in sorted(GAMES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"_game_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise CatalogError(f"Spieldefinition nicht ladbar: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        game = getattr(module, "GAME", None)
        if not isinstance(game, dict) or "id" not in game:
            raise CatalogError(f"{path} exportiert kein GAME-Dict mit 'id'.")
        definitions[game["id"]] = game
    return definitions


def build_catalog(game: dict[str, Any]) -> dict[str, Any]:
    versions = set(game["versions"])
    print(f"Baue Katalog '{game['id']}' ({len(game['locations'])} kuratierte Orte)...", file=sys.stderr)

    locations = [
        location for location in (build_location(raw, versions) for raw in game["locations"]) if location is not None
    ]

    # Erst jetzt durchnummerieren - uebersprungene Orte sollen keine Luecke lassen.
    for index, location in enumerate(locations, start=1):
        location["order"] = index

    return {
        "id": game["id"],
        "name": game["name"],
        "versions": game["versions"],
        "locations": locations,
        "level_caps": game.get("level_caps", []),
    }


def write_catalog(catalog: dict[str, Any], check_only: bool) -> bool:
    """True, wenn die Datei auf Platte dem erzeugten Katalog entspricht."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{catalog['id']}.json"
    serialized = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"

    if check_only:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current == serialized:
            print(f"  {target.name}: aktuell", file=sys.stderr)
            return True
        print(f"  {target.name}: WEICHT AB vom generierten Stand", file=sys.stderr)
        return False

    target.write_text(serialized, encoding="utf-8")
    species = sum(len(location["encounters"]) for location in catalog["locations"])
    print(
        f"  {target.name}: {len(catalog['locations'])} Orte, {species} Encounter-Eintraege, "
        f"{len(catalog['level_caps'])} Level-Caps",
        file=sys.stderr,
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", action="append", dest="games", metavar="ID", help="Spiel-ID (mehrfach moeglich)")
    parser.add_argument("--all", action="store_true", help="alle Spieldefinitionen bauen")
    parser.add_argument("--check", action="store_true", help="nur vergleichen, nichts schreiben")
    args = parser.parse_args()

    definitions = load_game_definitions()
    if not definitions:
        print(f"Keine Spieldefinitionen in {GAMES_DIR}.", file=sys.stderr)
        return 1

    if args.all or not args.games:
        selected = list(definitions)
    else:
        unknown = [game_id for game_id in args.games if game_id not in definitions]
        if unknown:
            print(f"Unbekannt: {', '.join(unknown)}. Verfuegbar: {', '.join(definitions)}", file=sys.stderr)
            return 1
        selected = args.games

    up_to_date = True
    for game_id in selected:
        catalog = build_catalog(definitions[game_id])
        up_to_date &= write_catalog(catalog, args.check)

    if args.check and not up_to_date:
        print("Katalog ist nicht aktuell - neu generieren.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CatalogError as error:
        print(f"Abbruch: {error}", file=sys.stderr)
        sys.exit(1)
