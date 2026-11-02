import json

import pytest

from orpk.codec import CLASS_ID, ONEWAY_BACKWARD, ONEWAY_BOTH, ONEWAY_FORWARD
from orpk.reader import Pack
from tests.golden import make_golden

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
    assert committed(name).to_json() == expected


def test_header_fields():
    p = committed("t_junction")
    assert (p.version_major, p.version_minor) == (1, 1)
    assert p.osm_timestamp == 1767225600
    assert p.cell_size == 50000
    assert "© OpenStreetMap contributors, ODbL 1.0" in p.attribution


def test_t_junction_simplifies_collinear_point_and_keeps_bend():
    p = committed("t_junction")
    es = edges(p)
    assert p.junction_count == 4 and len(es) == 3
    assert sorted(len(e.points) for e in es) == [0, 0, 2]


def test_oneway_pair_forward_and_backward():
    ow = sorted(e.oneway for e in edges(committed("oneway_pair")))
    assert ow == [ONEWAY_BOTH, ONEWAY_BOTH, ONEWAY_FORWARD, ONEWAY_BACKWARD]


def test_roundabout_ring_is_implied_oneway():
    es = edges(committed("roundabout"))
    ring = [e for e in es if e.oneway == ONEWAY_FORWARD]
    arms = [e for e in es if e.oneway == ONEWAY_BOTH]
    assert len(ring) == 4 and len(arms) == 4
    # Following the ring from any edge returns to the start after four edges.
    nxt = {e.a: e.b for e in ring}
    j = ring[0].a
    for _ in range(4):
        j = nxt[j]
    assert j == ring[0].a


def test_cell_boundary_negative_cells_and_cross_cell_edges():
    p = committed("cell_boundary")
    keys = [(e[0], e[1]) for e in p.index]
    assert (-679, 368) in keys and (-678, 368) in keys
    assert (1030, -1) in keys and (1030, 0) in keys
    assert (939, 170) in keys and (940, 170) in keys
    ranges = [p.junction_range(i) for i in range(p.cell_count)]

    def cell_index(j):
        return next(i for i, (lo, hi) in enumerate(ranges) if lo <= j < hi)

    assert all(cell_index(e.a) != cell_index(e.b) for e in edges(p))
    assert any(e.b < e.a for e in edges(p))  # negative junction delta


def test_parallel_streets_connected_only_at_west_end():
    p = committed("parallel_street")
    assert p.junction_count == 4 and p.edge_count == 3


def test_filters():
    got = sorted((e.cls, e.oneway, e.private) for e in edges(committed("filters")))
    assert got == sorted([
        (CLASS_ID["motorway"], ONEWAY_FORWARD, False),
        (CLASS_ID["motorway"], ONEWAY_BOTH, False),
        (CLASS_ID["service"], ONEWAY_BOTH, False),
        (CLASS_ID["residential"], ONEWAY_BOTH, True),
        (CLASS_ID["residential"], ONEWAY_BOTH, False),
        (CLASS_ID["residential"], ONEWAY_BOTH, False),
        (CLASS_ID["motorway_link"], ONEWAY_BACKWARD, False),
        (CLASS_ID["unclassified"], ONEWAY_BOTH, False),
        (CLASS_ID["service"], ONEWAY_FORWARD, False),
        (CLASS_ID["tertiary"], ONEWAY_BOTH, False),
        (CLASS_ID["tertiary"], ONEWAY_FORWARD, False),
    ])


def test_geometry_loops_and_overshoot():
    es = edges(committed("geometry"))
    loops = [e for e in es if e.a == e.b]
    assert sorted(len(e.points) for e in loops) == [2, 3]  # figure-eight lobe, closed ring
    assert len(es) == 5  # ring, figure eight split into three, overshoot
    overshoot = [e for e in es if e.cls == CLASS_ID["service"]]
    assert len(overshoot) == 1 and overshoot[0].points == [(47320000, 8603900)]


def test_empty_pack():
    p = committed("empty")
    assert (p.cell_count, p.junction_count, p.edge_count) == (0, 0, 0)
    assert (p.min_lat, p.min_lon, p.max_lat, p.max_lon) == (0, 0, 0, 0)
