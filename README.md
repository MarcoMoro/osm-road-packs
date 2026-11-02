<p align="center"><img src="assets/banner.svg" alt="OSM Road Packs" width="100%"></p>

# osm-road-packs

[![Country packs](https://github.com/MarcoMoro/osm-road-packs/actions/workflows/build.yml/badge.svg)](https://github.com/MarcoMoro/osm-road-packs/actions/workflows/build.yml)

Compact, routable road packs built from OpenStreetMap country extracts.

A pack holds the drivable road network of one country as a junction graph (junctions, road segments with simplified geometry, road class and oneway direction), split into 0.05 degree cells that are compressed individually. A reader can memory-map a pack and decode only the cells around a position, without unpacking the whole file. The format is called `ORPK` (OSM road pack) and is specified in [FORMAT.md](FORMAT.md).

## Packs

Packs are built monthly by GitHub Actions and attached to a dated release (`YYYY-MM-DD`). Each release contains one `<country>.orpk` per configured country and a `packs.json` manifest (FORMAT.md section 13). A manual run may rebuild only some countries; the others are carried over from the previous release, so every release is complete. A run fails instead of publishing a partial release (for example, a country newly added to `countries.json` must be part of the run).

| Country | Id | Source extract | Size (2026-11) |
|---|---|---|---|
| Austria | `at` | Geofabrik `europe/austria` | ~15 MB |
| France | `fr` | Geofabrik `europe/france` | ~100 MB |
| Germany | `de` | Geofabrik `europe/germany` | ~71 MB |
| Italy | `it` | Geofabrik `europe/italy` | ~60 MB |
| Liechtenstein | `li` | Geofabrik `europe/liechtenstein` | ~50 KB |
| Switzerland | `ch` | Geofabrik `europe/switzerland` | ~10 MB |

Countries are configured in [`countries.json`](countries.json) (id, display name, Geofabrik path).

## Content

Roads with `highway` = `motorway`, `trunk`, `primary`, `secondary`, `tertiary` (each with `_link`), `unclassified`, `residential`, `living_street` and `service` (without parking aisles, driveways and drive-throughs). Ways tagged `access=no` or `access=private` are left out unless `motor_vehicle=yes/designated`; other restriction tags (`motor_vehicle=no`, `vehicle=no`, ...) are not evaluated. `area=yes` ways are left out. Oneway direction comes from `oneway`, implied for motorways and roundabouts unless `oneway=no`. Geometry is simplified with [Douglas-Peucker](https://en.wikipedia.org/wiki/Ramer%E2%80%93Douglas%E2%80%93Peucker_algorithm) at 2 m. Details: FORMAT.md section 9.

## Usage

Requires Python 3.14 (verified with 3.14.10). Run commands from the repository root.

```sh
python -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt     # Windows: .venv\Scripts\pip

# Download an extract and verify it
curl -LO https://download.geofabrik.de/europe/switzerland-latest.osm.pbf
curl -LO https://download.geofabrik.de/europe/switzerland-latest.osm.pbf.md5
md5sum -c switzerland-latest.osm.pbf.md5

python -m orpk build switzerland-latest.osm.pbf -o ch.orpk --stats ch.stats.json
python -m orpk check ch.orpk            # decode every cell and validate all invariants
python -m orpk dump ch.orpk -o ch.json  # decoded JSON (large for a whole country)
python -m orpk manifest --release 2026-11-02 --pack-dir . -o packs.json
```

The builder reads the extract twice and keeps node locations only for road nodes, so memory stays low: on a desktop PC Switzerland takes about 40 s and 2 GB of RAM, France (5.1 GB extract) about 5 min and 4.2 GB. That fits a standard GitHub-hosted runner.

## Tests and golden files

`tests/golden/` holds small packs built from synthetic OSM data (T junction, dual carriageway, roundabout, cell boundary crossings including negative coordinates, two parallel streets 150 m apart, one way per filter rule, loop edges and a simplification overshoot, an empty pack) plus their decoded JSON. They are the reference for other reader implementations.

```sh
python -m pytest                      # rebuild goldens and compare, reader round trip, codec tests
python -m tests.golden.make_golden    # regenerate goldens after an intended change
```

Rebuilt packs are compared in canonical form (header, index without offsets, inflated cell payloads), because DEFLATE output differs between zlib implementations.

## Versions

Verified 2026-11-02. Python dependencies are pinned with hashes in `requirements.txt` (including transitive ones); Dependabot proposes monthly updates for them and for the actions.

| Component | Version | Source |
|---|---|---|
| Python | 3.14.10 | python.org, actions/python-versions manifest |
| osmium (pyosmium) | 4.3.2 (2026-10-18) | PyPI |
| numpy | 2.5.4 (2026-10-10) | PyPI |
| pytest | 9.2.0 (2026-10-27) | PyPI |
| actions/checkout | v7.0.1, `3d3c42e5aac5ba805825da76410c181273ba90b1` | GitHub release tag |
| actions/setup-python | v7.1.0, `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | GitHub release tag |

## Licence

Code: MIT, see [LICENSE](LICENSE).

Data: the packs are derived from OpenStreetMap and licensed under the Open Database License 1.0.

> Data © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright

Extracts by [Geofabrik](https://download.geofabrik.de/). See [NOTICE](NOTICE). The golden test packs use synthetic coordinates and contain no OpenStreetMap data.
