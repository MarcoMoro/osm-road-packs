"""Read drivable road ways from an OSM file (FORMAT.md section 9)."""

import osmium
from osmium.replication.utils import get_replication_header

from .codec import CLASS_ID, ONEWAY_BACKWARD, ONEWAY_BOTH, ONEWAY_FORWARD

EXCLUDED_SERVICE = ("parking_aisle", "driveway", "drive-through")
MOTOR_VEHICLE_ALLOWED = ("yes", "designated")


def way_class(tags):
    """Class id of a way, or None if the way is not part of the pack."""
    cls = CLASS_ID.get(tags.get("highway"))
    if cls is None:
        return None
    if tags.get("area") == "yes":
        return None
    if tags.get("highway") == "service" and tags.get("service") in EXCLUDED_SERVICE:
        return None
    if tags.get("access") in ("no", "private") and tags.get("motor_vehicle") not in MOTOR_VEHICLE_ALLOWED:
        return None
    return cls


def way_oneway(tags):
    ow = tags.get("oneway")
    if ow in ("yes", "1", "true"):
        return ONEWAY_FORWARD
    if ow == "-1":
        return ONEWAY_BACKWARD
    if ow in ("no", "0", "false"):
        return ONEWAY_BOTH
    if tags.get("highway") == "motorway" or tags.get("junction") in ("roundabout", "circular"):
        return ONEWAY_FORWARD
    return ONEWAY_BOTH


def e7_to_e6(v):
    """10^-7 degree integer to 10^-6 degrees, rounding half to even."""
    q, r = divmod(v, 10)
    if r > 5 or (r == 5 and q & 1):
        q += 1
    return q


def osm_timestamp(path):
    """Replication timestamp of the extract as Unix seconds, 0 if absent."""
    ts = get_replication_header(str(path)).timestamp
    return int(ts.timestamp()) if ts else 0


def read_ways(path):
    """Yield (class, oneway, [(node_id, lat_e6, lon_e6), ...]) for every pack way, in file order."""
    fp = (osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY)
          .with_locations("flex_mem")
          .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
          .with_filter(osmium.filter.KeyFilter("highway")))
    for w in fp:
        cls = way_class(w.tags)
        if cls is None:
            continue
        pts = []
        for n in w.nodes:
            loc = n.location
            if not loc.valid():
                continue
            if pts and pts[-1][0] == n.ref:
                continue
            pts.append((n.ref, e7_to_e6(loc.y), e7_to_e6(loc.x)))
        if len(pts) < 2:
            continue
        yield cls, way_oneway(w.tags), pts
