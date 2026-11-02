import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "golden"))

import make_golden  # noqa: E402
from orpk.codec import CLASS_ID, ONEWAY_BACKWARD, ONEWAY_BOTH, ONEWAY_FORWARD  # noqa: E402
from orpk.reader import Pack  # noqa: E402

GOLDEN = make_golden.GOLDEN_DIR
NAMES = sorted(make_golden.SCENARIOS)


def committed(name):
    return Pack.open(GOLDEN / f"{name}.orpk")


def edges(pack):
    return [e for c in pack.cells() for e in c.edges]


@pytest.mark.parametrize("name", NAMES)
def test_rebuild_matches_committed_canonical_bytes(name, tmp_path):
    rebuilt = Pack(make_golden.build(name, tmp_path))
    assert rebuilt.canonical_bytes() == committed(name).canonical_bytes()


@pytest.mark.parametrize("name", NAMES)
def test_committed_pack_is_valid(name):
    committed(name).check()


@pytest.mark.parametrize("name", NAMES)
def test_reader_round_trip_matches_json(name):
    expected = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    assert committed(name).to_json() == json.loads(json.dumps(expected))


def test_header_fields():
    p = committed("t_junction")
    assert (p.version_major, p.version_minor) == (1, 0)
    assert p.osm_timestamp == 1767225600
    assert p.cell_size == 50000
    assert "OpenStreetMap contributors" in p.attribution and "ODbL" in p.attribution


def test_t_junction_simplifies_collinear_point_and_keeps_bend():
    p = committed("t_junction")
    es = edges(p)
    assert p.junction_count == 4 and len(es) == 3
    by_points = sorted(len(e[5]) for e in es)
    assert by_points == [0, 0, 2]


def test_oneway_pair_forward_and_backward():
    ow = sorted(e[3] for e in edges(committed("oneway_pair")))
    assert ow == [ONEWAY_BOTH, ONEWAY_BOTH, ONEWAY_FORWARD, ONEWAY_BACKWARD]


def test_roundabout_ring_is_implied_oneway():
    es = edges(committed("roundabout"))
    ring = [e for e in es if e[3] == ONEWAY_FORWARD]
    arms = [e for e in es if e[3] == ONEWAY_BOTH]
    assert len(ring) == 4 and len(arms) == 4
    # Following the ring from any edge returns to the start after four edges.
    nxt = {e[0]: e[1] for e in ring}
    j = ring[0][0]
    for _ in range(4):
        j = nxt[j]
    assert j == ring[0][0]


def test_cell_boundary_negative_cells_and_cross_cell_edges():
    p = committed("cell_boundary")
    keys = [(e[0], e[1]) for e in p.index]
    assert (-679, 368) in keys and (-678, 368) in keys
    assert (1030, -1) in keys and (1030, 0) in keys
    assert (939, 170) in keys and (940, 170) in keys
    first = {i: p.junction_range(i) for i in range(p.cell_count)}

    def cell_index(j):
        return next(i for i, (lo, hi) in first.items() if lo <= j < hi)

    assert all(cell_index(e[0]) != cell_index(e[1]) for e in edges(p))
    assert any(e[1] < e[0] for e in edges(p))  # negative junction delta


def test_parallel_streets_connected_only_at_west_end():
    p = committed("parallel_street")
    assert p.junction_count == 4 and p.edge_count == 3


def test_filters():
    es = edges(committed("filters"))
    got = sorted((e[2], e[3]) for e in es)
    assert got == sorted([
        (CLASS_ID["motorway"], ONEWAY_FORWARD),
        (CLASS_ID["motorway"], ONEWAY_BOTH),
        (CLASS_ID["service"], ONEWAY_BOTH),
        (CLASS_ID["residential"], ONEWAY_BOTH),
        (CLASS_ID["residential"], ONEWAY_BOTH),
        (CLASS_ID["motorway_link"], ONEWAY_BACKWARD),
        (CLASS_ID["unclassified"], ONEWAY_BOTH),
        (CLASS_ID["service"], ONEWAY_FORWARD),
    ])


def test_empty_pack():
    p = committed("empty")
    assert (p.cell_count, p.junction_count, p.edge_count) == (0, 0, 0)
    assert (p.min_lat, p.min_lon, p.max_lat, p.max_lon) == (0, 0, 0, 0)
