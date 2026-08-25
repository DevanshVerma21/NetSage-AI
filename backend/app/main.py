"""FastAPI application factory.

Run it with::

    uvicorn backend.app.main:app --reload

CORS is deliberately narrow: the Vite dev server's two local origins, nothing else. There is
no authentication because there is no multi-user model and no real device access — the
prototype is a local, single-operator tool, and adding a login would imply a security
boundary it does not have.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import __version__
from backend.app.api import api_router
from backend.app.models.records import SIMULATION_DISCLAIMER

DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

DESCRIPTION = f"""
AI-assisted troubleshooting for Cisco-style lab networks.

**AI proposes. Deterministic rules verify. A human approves.**

Every diagnosis is stored as `awaiting_human_review` with `applied = false`, and no
endpoint can change that without a recorded human verdict. Fixes are applied to a copy of
the structured lab model and verified by re-running the deterministic rule engine:
*{SIMULATION_DISCLAIMER}*
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="NetSage AI",
        version=__version__,
        description=DESCRIPTION.strip(),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(api_router)
    return app


app = create_app()
