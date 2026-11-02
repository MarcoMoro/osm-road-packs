"""Command line: python -m orpk {build,check,dump,manifest} ..."""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .build import build_pack, write_json
from .manifest import write_manifest
from .reader import Pack, PackError, dump_json


def cmd_build(args):
    ts = None
    if args.osm_timestamp:
        when = dt.datetime.fromisoformat(args.osm_timestamp)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        ts = int(when.timestamp())
    data, stats = build_pack(args.extract, args.simplify, ts)
    Path(args.output).write_bytes(data)
    print(json.dumps(stats))
    if args.stats:
        write_json(args.stats, stats)


def cmd_check(args):
    ok = True
    for path in args.packs:
        try:
            pack = Pack.open(path)
            pack.check()
            print(f"{path}: ok, {pack.cell_count} cells, {pack.junction_count} junctions, {pack.edge_count} edges")
        except (PackError, OSError) as e:
            print(f"{path}: FAILED: {e}", file=sys.stderr)
            ok = False
    return 0 if ok else 1


def cmd_dump(args):
    text = dump_json(Pack.open(args.pack).to_json())
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)


def cmd_manifest(args):
    countries = json.loads(Path(args.countries).read_text(encoding="utf-8"))
    doc = write_manifest(args.output, args.release, countries, args.pack_dir)
    print(json.dumps(doc, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="orpk", description="Build and inspect ORPK road packs.")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a pack from an OSM extract")
    b.add_argument("extract")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--simplify", type=float, default=2.0, help="Douglas-Peucker tolerance in metres")
    b.add_argument("--osm-timestamp", help="override the extract timestamp (ISO 8601, e.g. 2026-01-01T00:00:00Z)")
    b.add_argument("--stats", help="write build statistics as JSON")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="decode and validate packs")
    c.add_argument("packs", nargs="+")
    c.set_defaults(func=cmd_check)
    d = sub.add_parser("dump", help="decode a pack to JSON")
    d.add_argument("pack")
    d.add_argument("-o", "--output")
    d.set_defaults(func=cmd_dump)
    m = sub.add_parser("manifest", help="write packs.json for a release")
    m.add_argument("--countries", default="countries.json")
    m.add_argument("--pack-dir", default="dist")
    m.add_argument("--release", required=True)
    m.add_argument("-o", "--output", default="dist/packs.json")
    m.set_defaults(func=cmd_manifest)
    args = p.parse_args(argv)
    try:
        return args.func(args) or 0
    except (PackError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
