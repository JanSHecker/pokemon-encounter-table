"""Lokaler Entwicklungsserver: API und Frontend unter einem Origin.

Bildet die Produktionspfade nach, damit das Frontend ohne Anpassung laeuft:

    /encounter-table/      -> web/
    /encounter-table/api/  -> api/app.py

    .venv/Scripts/python.exe -m uvicorn tools.dev_server:app --port 8010 --reload

Geschrieben wird per Default nach data/encounters.local.json (gitignored), damit
der committete Datenstand beim Ausprobieren unangetastet bleibt. Ein eigener
Pfad laesst sich weiterhin ueber ENCOUNTER_DATA_PATH setzen.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if not os.environ.get("ENCOUNTER_DATA_PATH"):
    local_data = ROOT / "data" / "encounters.local.json"
    if not local_data.exists():
        shutil.copyfile(ROOT / "data" / "encounters.json", local_data)
    os.environ["ENCOUNTER_DATA_PATH"] = str(local_data)

sys.path.insert(0, str(ROOT / "api"))

from fastapi import FastAPI  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from app import app as api_app  # noqa: E402

app = FastAPI(title="Encounter-Table Dev")


@app.middleware("http")
async def never_cache(request, call_next):
    """Sonst liefert der Browser nach einer Aenderung weiter das alte app.js aus."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


app.mount("/encounter-table/api", api_app)
app.mount("/encounter-table", StaticFiles(directory=ROOT / "web", html=True), name="web")


@app.get("/")
def root() -> dict[str, str]:
    return {"tabelle": "/encounter-table/", "api": "/encounter-table/api/"}
