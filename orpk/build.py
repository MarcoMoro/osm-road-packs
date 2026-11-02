"""Build pipeline: OSM extract -> filtered ways -> junction graph -> pack bytes."""

import time

from .filter import osm_timestamp, read_ways
from .graph import build_graph
from .writer import encode


def build_pack(extract, eps_m=2.0, timestamp=None):
    """Return (pack bytes, stats); timestamp (Unix seconds) defaults to the extract's replication timestamp."""
    t0 = time.time()
    if timestamp is None:
        timestamp = osm_timestamp(extract)
    data, stats = encode(build_graph(read_ways(extract), eps_m), timestamp)
    stats["seconds"] = round(time.time() - t0, 1)
    return data, stats
