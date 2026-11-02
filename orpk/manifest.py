"""packs.json manifest for a release."""

import datetime as dt
import hashlib
import json
from pathlib import Path

from .reader import Pack


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def pack_entry(path, country, name, source):
    data = Path(path).read_bytes()
    pack = Pack(data)
    return {
        "country": country,
        "name": name,
        "file": Path(path).name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "osm_timestamp": iso(pack.osm_timestamp),
        "format": "ORPK",
        "format_version": f"{pack.version_major}.{pack.version_minor}",
        "junctions": pack.junction_count,
        "edges": pack.edge_count,
        "source": source,
    }


def write_manifest(out, release, countries, pack_dir):
    """countries: {id: {"name", "geofabrik"}}; packs are <pack_dir>/<id>.orpk."""
    packs = []
    for cid in sorted(countries):
        path = Path(pack_dir) / f"{cid}.orpk"
        if path.exists():
            c = countries[cid]
            source = f"https://download.geofabrik.de/{c['geofabrik']}-latest.osm.pbf"
            packs.append(pack_entry(path, cid, c["name"], source))
    doc = {"release": release, "license": "ODbL-1.0", "packs": packs}
    Path(out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc
