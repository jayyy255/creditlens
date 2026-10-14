import json

import pytest
from fastapi.testclient import TestClient

from creditlens.api import create_app
from creditlens.model import train
from creditlens.pipeline import run_pipeline
from creditlens.synthetic import generate


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("api-data")
    generate(root / "raw", rows=1000)
    run_pipeline(root / "raw", root / "data")
    train(root / "data", root / "artifacts")
    return root


def test_api_serves_real_computed_metrics_and_filters(prepared):
    with TestClient(create_app(prepared / "data", prepared / "artifacts")) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        overview = client.get("/api/overview").json()
        assert overview["data_kind"] == "synthetic"
        assert overview["portfolio"]["applications"] == 1000
        category = overview["income_categories"][0]
        filtered = client.get("/api/overview", params={"income": category}).json()
        assert filtered["portfolio"]["applications"] < 1000
        assert client.get("/api/overview?income=invalid").status_code == 422
        assert client.get("/api/simulation?threshold=-1").status_code == 422
        assert client.get("/api/segments?column=TARGET").status_code == 422
        assert client.get("/api/simulation?threshold=1").json()["result"]["approval_rate"] == 1
        assert client.get("/api/simulation?threshold=0").json()["result"]["accepted"] == 0
        report = client.get("/api/model").json()
        assert client.get("/api/simulation").json()["result"]["population"] == report["partitions"]["validation"]


def test_missing_data_returns_actionable_503(tmp_path):
    with TestClient(create_app(tmp_path, tmp_path)) as client:
        response = client.get("/api/overview")
        assert response.status_code == 503
        assert "restart" in response.json()["detail"]


def test_stale_data_rejected(prepared, tmp_path):
    original = json.loads((prepared / "artifacts" / "model_report.json").read_text())
    original["gold_sha256"] = "stale"
    (tmp_path / "model_report.json").write_text(json.dumps(original))
    with TestClient(create_app(prepared / "data", tmp_path)) as client:
        assert client.get("/api/health").status_code == 503
