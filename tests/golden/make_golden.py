"""Generate the golden packs: tiny synthetic OSM files run through the full builder.

Usage: python tests/golden/make_golden.py   (rewrites tests/golden/*.orpk and *.json)
"""

import sys
import tempfile
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from orpk.filter import osm_timestamp, read_ways  # noqa: E402
from orpk.graph import build_graph  # noqa: E402
from orpk.reader import Pack, dump_json  # noqa: E402
from orpk.writer import encode  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent
TIMESTAMP = "2026-01-01T00:00:00Z"

# Each scenario: nodes {id: (lat, lon)} with at most 7 decimals, ways [(id, [node ids], {tags})].
SCENARIOS = {
    # Straight street with a nearly collinear point (dropped by simplification) and a bent branch.
    "t_junction": (
        {1: (47.37, 8.54), 10: (47.3700005, 8.54066), 2: (47.37, 8.54132), 3: (47.37, 8.54264),
         11: (47.37045, 8.54132), 12: (47.3709, 8.54198), 4: (47.37135, 8.54132)},
        [(1, [1, 10, 2, 3], {"highway": "residential"}),
         (2, [2, 11, 12, 4], {"highway": "tertiary"})],
    ),
    # Dual carriageway: one half drawn with oneway=yes, the other drawn the same way with oneway=-1.
    "oneway_pair": (
        {0: (47.4, 8.49868), 1: (47.4, 8.5), 2: (47.40009, 8.50132), 3: (47.40009, 8.50396),
         4: (47.4, 8.50528), 5: (47.39991, 8.50132), 6: (47.39991, 8.50396), 7: (47.4, 8.5066)},
        [(1, [0, 1], {"highway": "primary"}),
         (2, [1, 2, 3, 4], {"highway": "primary", "oneway": "yes"}),
         (3, [1, 5, 6, 4], {"highway": "primary", "oneway": "-1"}),
         (4, [4, 7], {"highway": "primary"})],
    ),
    # Closed roundabout ring (oneway implied) with four two-way arms.
    "roundabout": (
        {100: (47.45027, 8.55), 101: (47.45019, 8.55028), 102: (47.45, 8.5504), 103: (47.44981, 8.55028),
         104: (47.44973, 8.55), 105: (47.44981, 8.54972), 106: (47.45, 8.5496), 107: (47.45019, 8.54972),
         200: (47.4512, 8.55), 202: (47.45, 8.5519), 204: (47.4488, 8.55), 206: (47.45, 8.5481)},
        [(1, [100, 107, 106, 105, 104, 103, 102, 101, 100], {"highway": "secondary", "junction": "roundabout"}),
         (2, [200, 100], {"highway": "secondary"}),
         (3, [202, 102], {"highway": "secondary"}),
         (4, [204, 104], {"highway": "secondary"}),
         (5, [206, 106], {"highway": "secondary"})],
    ),
    # Edges crossing a latitude cell line, the prime meridian (negative cells) and a southern cell line.
    "cell_boundary": (
        {1: (46.999, 8.525), 2: (47.0, 8.526), 3: (47.001, 8.525),
         4: (51.5, -0.001), 5: (51.5, 0.001), 6: (51.5, 0.0),
         7: (-33.9, 18.425), 8: (-33.901, 18.425)},
        [(1, [1, 2, 3], {"highway": "residential"}),
         (2, [4, 6, 5], {"highway": "primary"}),
         (3, [6, 6], {"highway": "primary"}),
         (4, [7, 8], {"highway": "tertiary", "oneway": "yes"})],
    ),
    # Two parallel streets 150 m apart, joined only at the west end.
    "parallel_street": (
        {1: (47.38, 8.52), 2: (47.38, 8.5266), 3: (47.38135, 8.52), 4: (47.38135, 8.5266)},
        [(1, [1, 2], {"highway": "residential"}),
         (2, [3, 4], {"highway": "residential"}),
         (3, [1, 3], {"highway": "residential"})],
    ),
    # One way per filter rule; kept ways are marked in the comments.
    "filters": (
        {n: (47.35 + 0.0002 * (n // 2), 8.5 + 0.00132 * (n % 2)) for n in range(40)},
        [(1, [0, 1], {"highway": "motorway"}),  # kept, implied forward
         (2, [2, 3], {"highway": "motorway", "oneway": "no"}),  # kept, both
         (3, [4, 5], {"highway": "footway"}),
         (4, [6, 7], {"highway": "service", "service": "parking_aisle"}),
         (5, [8, 9], {"highway": "service", "service": "driveway"}),
         (6, [10, 11], {"highway": "service"}),  # kept
         (7, [12, 13], {"highway": "residential", "access": "private"}),
         (8, [14, 15], {"highway": "residential", "access": "private", "motor_vehicle": "yes"}),  # kept
         (9, [16, 17, 19, 18, 16], {"highway": "residential", "area": "yes"}),
         (10, [20, 21], {"highway": "track"}),
         (11, [22, 23], {"highway": "residential", "access": "no", "motor_vehicle": "designated"}),  # kept
         (12, [24, 25], {"highway": "motorway_link", "oneway": "-1"}),  # kept, backward
         (13, [26, 26, 27], {"highway": "unclassified"}),  # kept, duplicate node collapsed
         (14, [28], {"highway": "residential"}),
         (15, [30, 99999], {"highway": "residential"}),  # missing node: fewer than two nodes
         (16, [32, 33], {"highway": "service", "service": "drive-through"}),
         (17, [34, 35], {"highway": "service", "area": "no", "oneway": "true"})],  # kept, forward
    ),
    # No drivable road at all.
    "empty": (
        {1: (47.0, 8.0), 2: (47.001, 8.0)},
        [(1, [1, 2], {"highway": "footway"})],
    ),
}


def write_osm(path, nodes, ways):
    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", TIMESTAMP)
    with osmium.SimpleWriter(str(path), header=header, overwrite=True) as w:
        for nid in sorted(nodes):
            lat, lon = nodes[nid]
            w.add_node(osmium.osm.mutable.Node(id=nid, location=osmium.osm.Location(lon, lat)))
        for wid, refs, tags in ways:
            w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags))


def build(name, workdir):
    """Build scenario `name` through the full pipeline; return pack bytes."""
    nodes, ways = SCENARIOS[name]
    src = Path(workdir) / f"{name}.osm.pbf"
    write_osm(src, nodes, ways)
    data, _ = encode(build_graph(read_ways(src)), osm_timestamp(src))
    return data


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for name in SCENARIOS:
            data = build(name, tmp)
            pack = Pack(data)
            pack.check()
            (GOLDEN_DIR / f"{name}.orpk").write_bytes(data)
            (GOLDEN_DIR / f"{name}.json").write_text(dump_json(pack.to_json()), encoding="utf-8", newline="\n")
            print(f"{name}: {len(data)} bytes, {pack.junction_count} junctions, {pack.edge_count} edges")


if __name__ == "__main__":
    main()
