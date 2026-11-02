# osm-road-packs

Compact, routable road packs built from OpenStreetMap country extracts.

A pack holds the drivable road network of one country as a junction graph (junctions, road segments with simplified geometry, road class and oneway direction), split into 0.05 degree cells that are compressed individually. A reader can memory-map a pack and decode only the cells around a position, without unpacking the whole file. The format is called `ORPK` (OSM road pack) and is specified in [FORMAT.md](FORMAT.md).

## Packs

Packs are built monthly by GitHub Actions and attached to a dated release (`YYYY-MM-DD`). Each release contains one `<country>.orpk` per configured country and a `packs.json` manifest:

```json
{
  "release": "2026-11-02",
  "license": "ODbL-1.0",
  "packs": [
    {"country": "ch", "name": "Switzerland", "file": "ch.orpk", "size": 9317976,
     "sha256": "...", "osm_timestamp": "2026-11-01T21:21:36Z",
     "format": "ORPK", "format_version": "1.0", "junctions": 843387, "edges": 953279,
     "source": "https://download.geofabrik.de/europe/switzerland-latest.osm.pbf"}
  ]
}
```

| Country | Id | Source extract | Size (2026-11-02) |
|---|---|---|---|
| Switzerland | `ch` | Geofabrik `europe/switzerland` | 9.3 MB |

Countries are configured in [`countries.json`](countries.json) (id, display name, Geofabrik path).

## Content

Roads with `highway` = `motorway`, `trunk`, `primary`, `secondary`, `tertiary` (each with `_link`), `unclassified`, `residential`, `living_street` and `service` (without parking aisles, driveways and drive-throughs). Roads closed to motor vehicles (`access=no/private` without `motor_vehicle=yes/designated`) and `area=yes` are left out. Oneway direction comes from `oneway`, implied for motorways and roundabouts. Geometry is simplified with Douglas-Peucker at 2 m. Details: FORMAT.md section 9.

## Usage

Requires Python 3.14 (verified with 3.14.10).

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip

# Download an extract and verify it
curl -LO https://download.geofabrik.de/europe/switzerland-latest.osm.pbf
curl -LO https://download.geofabrik.de/europe/switzerland-latest.osm.pbf.md5
md5sum -c switzerland-latest.osm.pbf.md5

python -m orpk build switzerland-latest.osm.pbf -o ch.orpk --stats ch.stats.json
python -m orpk check ch.orpk          # decode every cell and validate all invariants
python -m orpk dump ch.orpk -o ch.json  # decoded JSON (large for a whole country)
python -m orpk manifest --release 2026-11-02 --pack-dir . -o packs.json
```

Building Switzerland takes about 40 s and a few GB of RAM on a desktop PC.

## Tests and golden files

`tests/golden/` holds small packs built from synthetic OSM data (a T junction, a dual carriageway, a roundabout, cell boundary crossings including negative coordinates, two parallel streets 150 m apart, one way per filter rule, an empty pack) plus their decoded JSON. They are the reference for other reader implementations.

```sh
python -m pytest                       # rebuild goldens and compare, reader round trip, codec tests
python tests/golden/make_golden.py     # regenerate goldens after an intended change
```

Rebuilt packs are compared in canonical form (header, index without offsets, inflated cell payloads), because DEFLATE output differs between zlib implementations.

## Versions

Verified 2026-11-02:

| Component | Version | Source |
|---|---|---|
| Python | 3.14.10 | python.org, actions/python-versions manifest |
| osmium (pyosmium) | 4.3.2 (2026-10-18) | PyPI |
| pytest | 9.2.0 (2026-10-27) | PyPI |
| actions/checkout | v7.0.1, `3d3c42e5aac5ba805825da76410c181273ba90b1` | GitHub release tag |
| actions/setup-python | v7.1.0, `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | GitHub release tag |

## Licence

Code: MIT, see [LICENSE](LICENSE).

Data: the packs are derived from OpenStreetMap and licensed under the Open Database License 1.0.

> Data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0.
> https://www.openstreetmap.org/copyright

Extracts by [Geofabrik](https://download.geofabrik.de/). See [NOTICE](NOTICE). The golden test packs use synthetic coordinates and contain no OpenStreetMap data.
