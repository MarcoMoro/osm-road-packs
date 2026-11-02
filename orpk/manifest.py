"""packs.json release manifest (FORMAT.md section 13)."""

import datetime as dt
import hashlib
import json
from pathlib import Path

from .codec import FORMAT_NAME, TIME_FORMAT
from .reader import Pack

GEOFABRIK = "https://download.geofabrik.de"


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")


def source_url(country):
    """Geofabrik extract URL for a countries.json entry."""
    return f"{GEOFABRIK}/{country['geofabrik']}-latest.osm.pbf"


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(TIME_FORMAT) if ts else None


def pack_entry(path, cid, country):
    data = Path(path).read_bytes()
    pack = Pack(data)
    return {
        "country": cid,
        "name": country["name"],
        "file": Path(path).name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "osm_timestamp": iso(pack.osm_timestamp),
        "format": FORMAT_NAME,
        "format_version": f"{pack.version_major}.{pack.version_minor}",
        "junctions": pack.junction_count,
        "edges": pack.edge_count,
        "source": source_url(country),
    }


def write_manifest(out, release, countries, pack_dir):
    """countries: {id: {"name", "geofabrik"}}; every <pack_dir>/<id>.orpk must exist (releases are complete)."""
    missing = [cid for cid in sorted(countries) if not (Path(pack_dir) / f"{cid}.orpk").exists()]
    if missing:
        raise FileNotFoundError(f"packs missing in {pack_dir}: {', '.join(missing)}")
    packs = [pack_entry(Path(pack_dir) / f"{cid}.orpk", cid, countries[cid]) for cid in sorted(countries)]
    doc = {"release": release, "license": "ODbL-1.0", "packs": packs}
    write_json(out, doc)
    return doc
