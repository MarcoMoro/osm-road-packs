import json

import pytest

from orpk.codec import ATTRIBUTION
from orpk.manifest import write_manifest
from scripts.ci_build import notes, open_url, require_built, select
from tests.golden import make_golden

COUNTRIES = {"ch": {"name": "Switzerland", "geofabrik": "europe/switzerland"},
             "li": {"name": "Liechtenstein", "geofabrik": "europe/liechtenstein"}}


def test_select_validates_ids():
    assert select(COUNTRIES, "") == ["ch", "li"]
    assert select(COUNTRIES, " li ") == ["li"]
    assert select(COUNTRIES, "li ch li") == ["li", "ch"]
    for bad in ("de", "CH", "ch;rm"):
        with pytest.raises(SystemExit):
            select(COUNTRIES, bad)


def test_open_url_refuses_redirect_to_http(monkeypatch):
    class Response:
        closed = False

        def geturl(self):
            return "http://mirror.example/x.osm.pbf"

        def close(self):
            self.closed = True

    r = Response()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: r)
    with pytest.raises(SystemExit, match="non-https"):
        open_url("https://download.example/x.osm.pbf")
    assert r.closed


def test_release_requires_packs_built_in_this_run(tmp_path):
    (tmp_path / "ch.orpk").write_bytes(b"")
    require_built(tmp_path, ["ch"])
    with pytest.raises(SystemExit, match="li"):
        require_built(tmp_path, ["ch", "li"])


def test_manifest_requires_every_configured_pack(tmp_path):
    (tmp_path / "ch.orpk").write_bytes((make_golden.GOLDEN_DIR / "t_junction.orpk").read_bytes())
    with pytest.raises(FileNotFoundError, match="li"):
        write_manifest(tmp_path / "packs.json", "2026-11-02", COUNTRIES, tmp_path)


def test_manifest_and_notes(tmp_path):
    for cid in COUNTRIES:
        (tmp_path / f"{cid}.orpk").write_bytes((make_golden.GOLDEN_DIR / "t_junction.orpk").read_bytes())
    doc = write_manifest(tmp_path / "packs.json", "2026-11-02", COUNTRIES, tmp_path)
    assert json.loads((tmp_path / "packs.json").read_text(encoding="utf-8")) == doc
    entry, _ = doc["packs"]
    assert entry["country"] == "ch" and entry["file"] == "ch.orpk"
    assert entry["osm_timestamp"] == "2026-01-01T00:00:00Z" and entry["format_version"] == "1.1"
    assert entry["source"] == "https://download.geofabrik.de/europe/switzerland-latest.osm.pbf"
    text = notes(doc, "2026-10-03", ["li"])
    assert ATTRIBUTION in text and "Carried over unchanged from release 2026-10-03: li." in text


def test_notes_edge_cases():
    with pytest.raises(SystemExit):
        notes({"release": "x", "packs": []}, None, [])
    pack = {"name": "N", "file": "n.orpk", "size": 1, "osm_timestamp": None, "edges": 0, "sha256": "0",
            "format_version": "1.0"}
    assert "| unknown |" in notes({"release": "x", "packs": [pack]}, None, [])
