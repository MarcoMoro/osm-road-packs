import json

import pytest

import make_golden
from orpk.codec import ATTRIBUTION
from orpk.manifest import write_manifest
from scripts.ci_build import notes, select

COUNTRIES = {"ch": {"name": "Switzerland", "geofabrik": "europe/switzerland"},
             "li": {"name": "Liechtenstein", "geofabrik": "europe/liechtenstein"}}


def test_select_validates_ids():
    assert select(COUNTRIES, "") == ["ch", "li"]
    assert select(COUNTRIES, " li ") == ["li"]
    for bad in ("de", "CH", "ch;rm"):
        with pytest.raises(SystemExit):
            select(COUNTRIES, bad)


def test_manifest_and_notes(tmp_path):
    (tmp_path / "ch.orpk").write_bytes((make_golden.GOLDEN_DIR / "t_junction.orpk").read_bytes())
    doc = write_manifest(tmp_path / "packs.json", "2026-11-02", COUNTRIES, tmp_path)
    assert json.loads((tmp_path / "packs.json").read_text(encoding="utf-8")) == doc
    (entry,) = doc["packs"]
    assert entry["country"] == "ch" and entry["file"] == "ch.orpk"
    assert entry["osm_timestamp"] == "2026-01-01T00:00:00Z" and entry["format_version"] == "1.0"
    assert entry["source"] == "https://download.geofabrik.de/europe/switzerland-latest.osm.pbf"
    text = notes(doc, "2026-10-03", ["li"])
    assert ATTRIBUTION in text and "Carried over unchanged from release 2026-10-03: li." in text


def test_notes_edge_cases():
    with pytest.raises(SystemExit):
        notes({"release": "x", "packs": []}, None, [])
    pack = {"name": "N", "file": "n.orpk", "size": 1, "osm_timestamp": None, "edges": 0, "sha256": "0",
            "format_version": "1.0"}
    assert "| unknown |" in notes({"release": "x", "packs": [pack]}, None, [])
