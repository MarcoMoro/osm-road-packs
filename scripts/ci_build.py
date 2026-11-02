"""CI glue: download extracts with md5 check, build and validate packs, write release notes.

  python scripts/ci_build.py build [--countries "ch at"]   (empty = all in countries.json)
  python scripts/ci_build.py notes dist/packs.json > notes.md
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orpk.filter import osm_timestamp, read_ways  # noqa: E402
from orpk.graph import build_graph  # noqa: E402
from orpk.reader import Pack  # noqa: E402
from orpk.writer import encode  # noqa: E402

GEOFABRIK = "https://download.geofabrik.de"
USER_AGENT = "osm-road-packs (+https://github.com/MarcoMoro/osm-road-packs)"


def fetch(url, dest):
    """Stream url to dest; return the md5 hex digest of the content."""
    md5 = hashlib.md5()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            md5.update(chunk)
            f.write(chunk)
    return md5.hexdigest()


def select(countries, wanted):
    ids = wanted.split() if wanted and wanted.strip() else sorted(countries)
    for cid in ids:
        if not re.fullmatch(r"[a-z]{2,8}", cid) or cid not in countries:
            sys.exit(f"unknown country id {cid!r}; configured: {', '.join(sorted(countries))}")
    return ids


def cmd_build(args):
    countries = json.loads((ROOT / "countries.json").read_text(encoding="utf-8"))
    downloads, dist = Path(args.downloads), Path(args.dist)
    downloads.mkdir(exist_ok=True)
    dist.mkdir(exist_ok=True)
    for cid in select(countries, args.countries):
        url = f"{GEOFABRIK}/{countries[cid]['geofabrik']}-latest.osm.pbf"
        md5_path = downloads / f"{cid}.osm.pbf.md5"
        fetch(url + ".md5", md5_path)
        expected = md5_path.read_text(encoding="ascii").split()[0].lower()
        pbf = downloads / f"{cid}.osm.pbf"
        actual = fetch(url, pbf)
        if actual != expected:
            sys.exit(f"{cid}: md5 mismatch for {url}: {actual} != {expected}")
        print(f"{cid}: downloaded {pbf.stat().st_size} bytes, md5 ok", flush=True)
        data, stats = encode(build_graph(read_ways(pbf)), osm_timestamp(pbf))
        out = dist / f"{cid}.orpk"
        out.write_bytes(data)
        Pack(data).check()
        (dist / f"{cid}.stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        print(f"{cid}: {json.dumps(stats)}, check ok", flush=True)
        pbf.unlink()


def cmd_notes(args):
    sys.stdout.reconfigure(encoding="utf-8")
    doc =json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    lines = [f"Road packs built from OpenStreetMap extracts ({doc['release']}).", "",
             "| Country | File | Size | OSM data as of | Edges | SHA-256 |", "|---|---|---|---|---|---|"]
    for p in doc["packs"]:
        lines.append(f"| {p['name']} | `{p['file']}` | {p['size'] / 1e6:.1f} MB | {p['osm_timestamp']} "
                     f"| {p['edges']:,} | `{p['sha256']}` |")
    lines += ["", "Format: `ORPK` " + ", ".join(sorted({p["format_version"] for p in doc["packs"]}))
              + ", see FORMAT.md. Manifest: `packs.json`.", "",
              "Data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0, "
              "https://www.openstreetmap.org/copyright. Extracts by Geofabrik (https://download.geofabrik.de/)."]
    sys.stdout.write("\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--countries", default="")
    b.add_argument("--downloads", default="downloads")
    b.add_argument("--dist", default="dist")
    n = sub.add_parser("notes")
    n.add_argument("manifest")
    args = p.parse_args()
    {"build": cmd_build, "notes": cmd_notes}[args.cmd](args)


if __name__ == "__main__":
    main()
