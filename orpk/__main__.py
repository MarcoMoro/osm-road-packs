"""Command line: python -m orpk {build,check,dump,manifest} ..."""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from .filter import osm_timestamp, read_ways
from .graph import build_graph
from .manifest import write_manifest
from .reader import Pack, PackError, dump_json
from .writer import encode


def cmd_build(args):
    t0 = time.time()
    ts = args.osm_timestamp
    if ts is None:
        ts = osm_timestamp(args.extract)
    else:
        ts = int(dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp())
    graph = build_graph(read_ways(args.extract), args.simplify)
    data, stats = encode(graph, ts)
    Path(args.output).write_bytes(data)
    stats["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(stats))
    if args.stats:
        Path(args.stats).write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


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
    b.add_argument("--osm-timestamp", help="override the extract timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    b.add_argument("--stats", help="write build statistics as JSON")
    c = sub.add_parser("check", help="decode and validate packs")
    c.add_argument("packs", nargs="+")
    d = sub.add_parser("dump", help="decode a pack to JSON")
    d.add_argument("pack")
    d.add_argument("-o", "--output")
    m = sub.add_parser("manifest", help="write packs.json for a release")
    m.add_argument("--countries", default="countries.json")
    m.add_argument("--pack-dir", default="dist")
    m.add_argument("--release", required=True)
    m.add_argument("-o", "--output", default="dist/packs.json")
    args = p.parse_args(argv)
    handler = {"build": cmd_build, "check": cmd_check, "dump": cmd_dump, "manifest": cmd_manifest}[args.cmd]
    return handler(args) or 0


if __name__ == "__main__":
    sys.exit(main())
