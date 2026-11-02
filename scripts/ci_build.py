"""CI glue: download extracts with md5 check, build and validate packs, publish a release.

Run from the repository root:
  python -m scripts.ci_build list [--countries "ch at"]    (JSON list of validated ids; empty = all)
  python -m scripts.ci_build build [--countries "ch at"]   (empty = all in countries.json)
  python -m scripts.ci_build release [--built "ch at"]     (needs gh and GH_TOKEN)
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from orpk.codec import ATTRIBUTION, FORMAT_NAME
from orpk.manifest import source_url, write_json, write_manifest
from orpk.reader import Pack

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "osm-road-packs (+https://github.com/MarcoMoro/osm-road-packs)"
FETCH_ATTEMPTS = 2  # a second try covers a mirror file replaced during the download


def load_countries():
    return json.loads((ROOT / "countries.json").read_text(encoding="utf-8"))


def open_url(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60)


def fetch(url, dest):
    """Stream url to dest; return (final URL after redirects, md5 hex digest of the content)."""
    md5 = hashlib.md5()
    with open_url(url) as r, open(dest, "wb") as f:
        final = r.geturl()
        while chunk := r.read(1 << 20):
            md5.update(chunk)
            f.write(chunk)
    return final, md5.hexdigest()


def fetch_verified(url, dest):
    """Download url and check it against the .md5 next to the file it redirected to; retry once on mismatch.

    Geofabrik redirects -latest to a dated file or a mirror, and not every -latest has its own .md5.
    """
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        final, actual = fetch(url, dest)
        with open_url(final + ".md5") as r:
            expected = r.read().decode("ascii").split()[0].lower()
        if actual == expected:
            return final
        print(f"md5 mismatch for {final} (attempt {attempt}): {actual} != {expected}", flush=True)
    sys.exit(f"md5 check failed for {url}")


def select(countries, wanted):
    ids = list(dict.fromkeys(wanted.split())) if wanted and wanted.strip() else sorted(countries)
    for cid in ids:
        if not re.fullmatch(r"[a-z]{2,8}", cid) or cid not in countries:
            sys.exit(f"unknown country id {cid!r}; configured: {', '.join(sorted(countries))}")
    return ids


def cmd_list(args):
    print(json.dumps(select(load_countries(), args.countries)))


def cmd_build(args):
    from orpk.build import build_pack  # imported here so list and release work without osmium and numpy

    countries = load_countries()
    downloads, dist = Path(args.downloads), Path(args.dist)
    downloads.mkdir(exist_ok=True)
    dist.mkdir(exist_ok=True)
    for cid in select(countries, args.countries):
        url = source_url(countries[cid])
        pbf = downloads / f"{cid}.osm.pbf"
        final = fetch_verified(url, pbf)
        print(f"{cid}: downloaded {final}, {pbf.stat().st_size} bytes, md5 ok", flush=True)
        data, stats = build_pack(pbf)
        (dist / f"{cid}.orpk").write_bytes(data)
        Pack(data).check()
        write_json(dist / f"{cid}.stats.json", stats)
        print(f"{cid}: {json.dumps(stats)}, check ok", flush=True)
        pbf.unlink()


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"gh {args[0]} {args[1]} failed: {r.stderr.strip()}")
    return r


def free_tag():
    base = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    tag, n = base, 2
    while gh("release", "view", tag, check=False).returncode == 0:
        tag, n = f"{base}-{n}", n + 1
    return tag


def carry_over(countries, dist):
    """Copy packs not built in this run from the latest release, so every release is complete.

    Any failure (no previous release, pack missing there, gh error) stops the run: a country new in
    countries.json needs a build run that includes it.
    """
    missing = [cid for cid in sorted(countries) if not (dist / f"{cid}.orpk").exists()]
    if not missing:
        return None, []
    tag = gh("release", "view", "--json", "tagName", "-q", ".tagName").stdout.strip()
    for cid in missing:
        gh("release", "download", tag, "-p", f"{cid}.orpk", "-D", str(dist))
    return tag, missing


def require_built(dist, built):
    """Every pack built in this run must be in dist; otherwise carry_over would fill the gap with older packs."""
    missing = [cid for cid in built if not (dist / f"{cid}.orpk").exists()]
    if missing:
        sys.exit(f"packs built in this run missing from {dist}: {', '.join(missing)}")


def notes(doc, carried_from, carried):
    if not doc["packs"]:
        sys.exit("no packs to release")
    lines = [f"Road packs built from OpenStreetMap extracts ({doc['release']}).", "",
             "| Country | File | OSM data as of | Edges | SHA-256 |", "|---|---|---|---|---|"]
    for p in doc["packs"]:
        lines.append(f"| {p['name']} | `{p['file']}` | {p['osm_timestamp'] or 'unknown'} | {p['edges']:,} "
                     f"| `{p['sha256']}` |")
    if carried:
        lines += ["", f"Carried over unchanged from release {carried_from}: {', '.join(carried)}."]
    versions = ", ".join(sorted({p["format_version"] for p in doc["packs"]}))
    lines += ["", f"Format: `{FORMAT_NAME}` {versions}, see FORMAT.md. Manifest: `packs.json`.", "",
              f"{ATTRIBUTION}. Extracts by Geofabrik (https://download.geofabrik.de/)."]
    return "\n".join(lines) + "\n"


def cmd_release(args):
    countries = load_countries()
    dist = Path(args.dist)
    require_built(dist, select(countries, args.built) if args.built.strip() else [])
    tag = free_tag()
    carried_from, carried = carry_over(countries, dist)
    for cid in sorted(countries):
        Pack.open(dist / f"{cid}.orpk").check()
    doc = write_manifest(dist / "packs.json", tag, countries, dist)
    (dist / "notes.md").write_text(notes(doc, carried_from, carried), encoding="utf-8", newline="\n")
    files = [str(dist / p["file"]) for p in doc["packs"]] + [str(dist / "packs.json")]
    gh("release", "create", tag, *files, "--title", tag, "--notes-file", str(dist / "notes.md"),
       "--target", args.target)
    print(f"released {tag}: {', '.join(p['country'] for p in doc['packs'])}", flush=True)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--countries", default="")
    ls.set_defaults(func=cmd_list)
    b = sub.add_parser("build")
    b.add_argument("--countries", default="")
    b.add_argument("--downloads", default="downloads")
    b.add_argument("--dist", default="dist")
    b.set_defaults(func=cmd_build)
    r = sub.add_parser("release")
    r.add_argument("--dist", default="dist")
    r.add_argument("--built", default="", help="country ids built in this run; each must be in --dist")
    r.add_argument("--target", required=True, help="commit SHA the release tag points to")
    r.set_defaults(func=cmd_release)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
