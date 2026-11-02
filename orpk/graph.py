"""Split road ways into a junction graph (FORMAT.md section 9)."""

from collections import Counter

from .simplify import douglas_peucker


class Graph:
    def __init__(self):
        self.junctions = {}  # node id -> (lat_e6, lon_e6)
        self.edges = []  # (a node id, b node id, class, oneway, [(lat_e6, lon_e6), ...] interior)
        self.ways = 0


def build_graph(ways, eps_m=2.0):
    """ways: iterable of (class, oneway, [(node_id, lat_e6, lon_e6), ...])."""
    ways = list(ways)
    use = Counter()
    for _, _, pts in ways:
        last = len(pts) - 1
        for i, (nid, _, _) in enumerate(pts):
            use[nid] += 2 if i in (0, last) else 1

    g = Graph()
    g.ways = len(ways)
    for cls, oneway, pts in ways:
        start = 0
        last = len(pts) - 1
        for i in range(1, last + 1):
            if i < last and use[pts[i][0]] < 2:
                continue
            seg = pts[start:i + 1]
            start = i
            a, b = seg[0], seg[-1]
            inner = douglas_peucker([(p[1], p[2]) for p in seg], eps_m)[1:-1]
            if a[0] == b[0] and not inner:
                continue
            g.junctions[a[0]] = (a[1], a[2])
            g.junctions[b[0]] = (b[1], b[2])
            g.edges.append((a[0], b[0], cls, oneway, inner))
    return g
