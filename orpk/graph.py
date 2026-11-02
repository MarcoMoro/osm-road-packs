"""Split road ways into a junction graph (FORMAT.md section 9)."""

from array import array
from dataclasses import dataclass

import numpy as np

from .codec import pack_flags
from .simplify import douglas_peucker


@dataclass
class Graph:
    """Flat arrays, since a large country has tens of millions of points."""
    junction_ids: np.ndarray  # sorted unique node ids (int64)
    junction_lat: np.ndarray  # int32, same order as junction_ids
    junction_lon: np.ndarray
    edge_a: np.ndarray  # node id of the start and end junction of each edge (int64)
    edge_b: np.ndarray
    edge_flags: np.ndarray  # pack_flags(class, oneway, private) (uint8)
    inner_count: np.ndarray  # interior points per edge, stored edge after edge in inner_lat/inner_lon (int64)
    inner_lat: np.ndarray  # int32
    inner_lon: np.ndarray
    ways: int


def build_graph(ways, eps_m=2.0):
    """ways: iterable of (class, oneway, private, [(node_id, lat_e6, lon_e6), ...])."""
    ids, lats, lons = array("q"), array("i"), array("i")
    starts, flags = array("q"), array("B")
    for cls, oneway, private, pts in ways:
        starts.append(len(ids))
        flags.append(pack_flags(cls, oneway, private))
        i, la, lo = zip(*pts)
        ids.extend(i)
        lats.extend(la)
        lons.extend(lo)
    ids, lats, lons = np.frombuffer(ids, np.int64), np.frombuffer(lats, np.int32), np.frombuffer(lons, np.int32)
    first = np.frombuffer(starts, np.int64)
    last = np.append(first, len(ids))[1:] - 1

    # A point splits its way if its node occurs twice or more, or ends a way (end nodes are always junctions).
    order = np.argsort(ids)
    srt = ids[order]
    shared = srt[1:] == srt[:-1]
    split = np.zeros(len(ids), bool)
    split[order[1:][shared]] = True
    split[order[:-1][shared]] = True
    del order, srt, shared
    split[first] = True
    split[last] = True
    pos = np.flatnonzero(split)

    # Edges run between consecutive split points of the same way.
    way = np.searchsorted(first, pos, side="right") - 1
    same = way[1:] == way[:-1]
    s, e, way = pos[:-1][same], pos[1:][same], way[:-1][same]

    inner_count = np.zeros(len(s), np.int64)
    inner_lat, inner_lon = array("i"), array("i")
    long_edges = np.flatnonzero(e - s > 1)
    for k, a, b in zip(long_edges.tolist(), s[long_edges].tolist(), e[long_edges].tolist()):
        inner = douglas_peucker(list(zip(lats[a:b + 1].tolist(), lons[a:b + 1].tolist())), eps_m)[1:-1]
        if inner:
            inner_count[k] = len(inner)
            la, lo = zip(*inner)
            inner_lat.extend(la)
            inner_lon.extend(lo)

    a_ids, b_ids = ids[s], ids[e]
    keep = (a_ids != b_ids) | (inner_count > 0)
    ends = np.concatenate((s[keep], e[keep]))
    junction_ids, at = np.unique(ids[ends], return_index=True)
    return Graph(
        junction_ids=junction_ids,
        junction_lat=lats[ends[at]],
        junction_lon=lons[ends[at]],
        edge_a=a_ids[keep],
        edge_b=b_ids[keep],
        edge_flags=np.frombuffer(flags, np.uint8)[way[keep]],
        inner_count=inner_count[keep],
        inner_lat=np.frombuffer(inner_lat, np.int32),
        inner_lon=np.frombuffer(inner_lon, np.int32),
        ways=len(first),
    )
