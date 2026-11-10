import gzip
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def real_history():
    scratch_path = Path("/home/nick/.gemini/antigravity/brain/edec4172-019a-4ad6-ae53-2a7340555a8b/scratch/history_20261103_10.json.gz")
    fix_path = FIX / "history_20261103_10.json.gz"
    p = scratch_path if scratch_path.exists() else fix_path
    if not p.exists():
        pytest.skip("history_20261103_10.json.gz fixture not found")
    d = json.loads(gzip.open(p).read())
    return {e: [(datetime.fromisoformat(t), v) for t, v in pts] for e, pts in d["history"].items()}


@pytest.fixture(scope="session")
def baseline_rows():
    return json.loads((FIX / "baseline_kpi.json").read_text(encoding="utf-8"))["kpis"]


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


class FakeSession:
    """Records every request; serves /states from an in-memory dict and history from a dict."""

    def __init__(self, states=None, history=None):
        self.states = states or {}
        self.history = history or {}
        self.posts = []
        self.gets = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.gets.append(url)
        path = url.split("/api", 1)[1] if "/api" in url else url
        if path in ("", "/"):
            return FakeResponse(200, {"message": "API running."})
        if path.startswith("/states/"):
            eid = path[len("/states/"):]
            if eid in self.states:
                return FakeResponse(200, {"entity_id": eid, "state": self.states[eid], "attributes": {}})
            return FakeResponse(404, {"message": "not found"})
        if path.startswith("/history/period/"):
            ids = params["filter_entity_id"].split(",")
            out = []
            for eid in ids:
                pts = self.history.get(eid, [])
                if pts:
                    out.append([{"entity_id": eid, "state": s, "last_changed": t.isoformat(),
                                 "attributes": {"cloud_coverage": s} if "no_attributes" not in params else None}
                                for t, s in pts])
            return FakeResponse(200, out)
        return FakeResponse(404)

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, json))
        if "/services/input_" in url and json and "entity_id" in json:
            eid = json["entity_id"]
            if url.endswith("turn_on"):
                self.states[eid] = "on"
            elif url.endswith("turn_off"):
                self.states[eid] = "off"
            elif "value" in json:
                self.states[eid] = str(json["value"])
            elif "option" in json:
                self.states[eid] = json["option"]
            elif "datetime" in json:
                self.states[eid] = json["datetime"]
        return FakeResponse(200, [])
