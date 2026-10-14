"""Local analytics API. No borrower-level data is exposed by the dashboard."""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from creditlens.analytics import association, portfolio, segments, simulate
from creditlens.pipeline import digest

STATIC = Path(__file__).parent / "static"
SEGMENTS = {"NAME_INCOME_TYPE", "age_band", "CODE_GENDER"}


def create_app(data_root: Path | None = None, artifact_root: Path | None = None) -> FastAPI:
    data_root = data_root or Path(os.getenv("CREDITLENS_DATA_ROOT", "data"))
    artifact_root = artifact_root or Path(os.getenv("CREDITLENS_ARTIFACT_ROOT", "artifacts"))
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        try:
            gold_path = data_root / "gold" / "borrowers.csv"
            report = json.loads((artifact_root / "model_report.json").read_text(encoding="utf-8"))
            if digest(gold_path) != report["gold_sha256"]:
                raise ValueError("Model and data fingerprints differ. Retrain before serving.")
            if digest(artifact_root / "validation_scores.csv") != report["validation_scores_sha256"]:
                raise ValueError("Validation score fingerprint differs. Retrain before serving.")
            state.update(frame=pd.read_csv(gold_path),
                         scores=pd.read_csv(artifact_root / "validation_scores.csv"),
                         report=report,
                         quality=json.loads((data_root / "quality.json").read_text(encoding="utf-8")))
        except (FileNotFoundError, ValueError, KeyError) as error:
            state["error"] = str(error)
        yield
        state.clear()

    app = FastAPI(title="CreditLens", version="0.1.0", lifespan=lifespan)

    def ready():
        if "frame" not in state:
            raise HTTPException(503, "Analytics unavailable. Run the ingestion and training commands, then restart the API. " + state.get("error", ""))

    def filtered(frame, income):
        if income is None:
            return frame
        if income not in set(state["frame"].NAME_INCOME_TYPE.dropna()):
            raise HTTPException(422, "Unknown income category")
        return frame.loc[frame.NAME_INCOME_TYPE == income]

    @app.get("/api/health")
    def health():
        ready()
        return {"status": "ok", "data_kind": state["quality"]["data_kind"]}

    @app.get("/api/overview")
    def overview(income: str | None = None):
        ready()
        frame = filtered(state["frame"], income)
        return {"data_kind": state["quality"]["data_kind"], "portfolio": portfolio(frame),
                "income_categories": sorted(state["frame"].NAME_INCOME_TYPE.dropna().unique().tolist()),
                "segments": segments(frame, "NAME_INCOME_TYPE"), "age_segments": segments(frame, "age_band"),
                "association": association(frame, "age_band")}

    @app.get("/api/segments")
    def segment(column: str = "NAME_INCOME_TYPE", income: str | None = None):
        ready()
        if column not in SEGMENTS:
            raise HTTPException(422, "Unsupported segment")
        return segments(filtered(state["frame"], income), column)

    @app.get("/api/model")
    def model():
        ready()
        return state["report"]

    @app.get("/api/quality")
    def quality():
        ready()
        return state["quality"]

    @app.get("/api/simulation")
    def simulation(threshold: float = Query(0.15, ge=0, le=1), income: str | None = None):
        ready()
        scores = filtered(state["scores"], income)
        if scores.empty:
            raise HTTPException(422, "This filter has no policy validation observations.")
        return {"result": simulate(scores, threshold),
                "curve": [simulate(scores, value / 100) for value in range(0, 101, 5)]}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
