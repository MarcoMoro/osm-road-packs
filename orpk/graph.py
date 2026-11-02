"""Split road ways into a junction graph (FORMAT.md section 9)."""

from collections import Counter
from dataclasses import dataclass, field

from .simplify import douglas_peucker


@dataclass
class Graph:
    junctions: dict = field(default_factory=dict)  # node id -> (lat_e6, lon_e6)
    edges: list = field(default_factory=list)  # (a node id, b node id, class, oneway, [(lat_e6, lon_e6)] interior)
    ways: int = 0


def build_graph(ways, eps_m=2.0):
    """ways: iterable of (class, oneway, [(node_id, lat_e6, lon_e6), ...])."""
    ways = list(ways)
    use = Counter()
    for _, _, pts in ways:
        last = len(pts) - 1
        for i, (nid, _, _) in enumerate(pts):
            use[nid] += 2 if i in (0, last) else 1

    g = Graph(ways=len(ways))
    for cls, oneway, pts in ways:
        start = 0
        last = len(pts) - 1
        for i in range(1, last + 1):
            if i < last and use[pts[i][0]] < 2:
                continue
            a, b = pts[start], pts[i]
            if i - start > 1:
                inner = douglas_peucker([(p[1], p[2]) for p in pts[start:i + 1]], eps_m)[1:-1]
            else:
                inner = []
            start = i
            if a[0] == b[0] and not inner:
                continue
            g.junctions[a[0]] = (a[1], a[2])
            g.junctions[b[0]] = (b[1], b[2])
            g.edges.append((a[0], b[0], cls, oneway, inner))
    return g
