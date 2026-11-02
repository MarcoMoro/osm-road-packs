"""Douglas-Peucker line simplification on micro-degree coordinates."""

import math

M_PER_DEG_LAT = 110_540
M_PER_DEG_LON_EQUATOR = 111_320


def douglas_peucker(pts, eps_m):
    """Simplify [(lat_e6, lon_e6), ...] keeping both end points; tolerance in metres."""
    if len(pts) < 3 or eps_m <= 0:
        return list(pts)
    kx = M_PER_DEG_LON_EQUATOR * math.cos(math.radians(pts[0][0] / 1e6)) / 1e6
    ky = M_PER_DEG_LAT / 1e6
    xy = [(lon * kx, lat * ky) for lat, lon in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, best_i = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if length > 0:
                d = abs(dy * (px - ax) - dx * (py - ay)) / length
            else:
                d = math.hypot(px - ax, py - ay)
            if d > best:
                best, best_i = d, i
        if best > eps_m:
            keep[best_i] = True
            stack.append((a, best_i))
            stack.append((best_i, b))
    return [p for p, k in zip(pts, keep) if k]
