# ORPK: OSM road pack format, version 1.0

Status: normative. A reader or writer that follows this document is compatible with the packs and the golden files in `tests/golden/`.

An `ORPK` file holds the drivable road network of one region as a junction graph: junctions (graph nodes) and edges (road segments between junctions, with simplified interior geometry). The file is split into geographic cells so a reader can memory-map it and decode only the cells it needs.

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

## 1. Conventions

- Byte order: little-endian for all fixed-width integers.
- Fixed-width types: `u8`, `u16`, `u32`, `u64` unsigned; `i32`, `i64` two's complement signed.
- `uvarint`: unsigned LEB128. Seven value bits per byte, least significant group first; bit 7 (0x80) set on every byte except the last. A value MUST be encoded in the minimum number of bytes and MUST fit in 64 bits (at most 10 bytes).
- `svarint`: a signed 64-bit value `n` zigzag-mapped to `(n << 1) ^ (n >> 63)` (arithmetic shift), then written as `uvarint`. Decoding: `(u >>> 1) ^ -(u & 1)`.
- Coordinates: integer micro-degrees (`lat_e6 = latitude * 10^6`, `lon_e6 = longitude * 10^6`), WGS84. Latitude in [-90000000, 90000000], longitude in [-180000000, 180000000].
- Text: UTF-8, no terminator.
- Compression: raw DEFLATE (RFC 1951) without zlib or gzip wrapper (Java: `Inflater(true)`; Python: `zlib.decompressobj(-15)`).

## 2. File layout

```
+--------------------+  offset 0
| header             |
+--------------------+  index_offset
| cell index         |  cell_count entries of 24 bytes
+--------------------+  index_offset + 24 * cell_count
| cell block 0       |  raw DEFLATE
| cell block 1       |
| ...                |
+--------------------+  end of file
```

Cell blocks follow the index directly, contiguous and in index order, with no gaps. The file ends at the end of the last block.

## 3. Header

| Offset | Type | Field | Value in 1.0 |
|---|---|---|---|
| 0 | 4 bytes | `magic` | ASCII `ORPK` (`4F 52 50 4B`) |
| 4 | u16 | `version_major` | 1 |
| 6 | u16 | `version_minor` | 0 |
| 8 | u32 | `flags` | 0 (reserved) |
| 12 | i64 | `osm_timestamp` | OSM data timestamp, Unix seconds UTC; 0 if unknown |
| 20 | i32 | `min_lat_e6` | bounding box of all coordinates in the file (junctions and interior points), inclusive |
| 24 | i32 | `min_lon_e6` | |
| 28 | i32 | `max_lat_e6` | |
| 32 | i32 | `max_lon_e6` | |
| 36 | i32 | `cell_size_e6` | 50000 (0.05 degrees) |
| 40 | u32 | `cell_count` | number of index entries |
| 44 | u32 | `junction_count` | total junctions |
| 48 | u32 | `edge_count` | total edges |
| 52 | u32 | `index_offset` | absolute offset of the cell index |
| 56 | u16 | `attribution_len` | byte length of `attribution` |
| 58 | bytes | `attribution` | UTF-8 data attribution and licence notice |

In 1.0, `index_offset = 58 + attribution_len`. `osm_timestamp` is the `osmosis_replication_timestamp` of the source extract. An empty pack (no roads) has `cell_count = 0`, `junction_count = 0`, `edge_count = 0` and a bounding box of all zeros.

The attribution string of packs built by this repository is:

```
Data (c) OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright
```

with the copyright sign U+00A9 in place of `(c)`. Applications displaying road data from a pack SHOULD show this string.

## 4. Cells

Cell coordinates of a point are computed with integer floor division (rounding towards negative infinity):

```
cell_lat = floor(lat_e6 / cell_size_e6)
cell_lon = floor(lon_e6 / cell_size_e6)
```

Example: `lat_e6 = 47012345` gives `cell_lat = 940`; `lon_e6 = -1` gives `cell_lon = -1`. The cell's origin (south-west corner) is `(cell_lat * cell_size_e6, cell_lon * cell_size_e6)`.

A junction belongs to the cell of its own coordinate. An edge belongs to the cell of its start junction `a`. Interior points of an edge MAY lie in other cells; a reader that needs all edges crossing a cell MUST also read the neighbouring cells as far as its use case requires (edges are never split at cell boundaries).

The index has one entry per cell that contains at least one junction. Cells without junctions have no entry.

## 5. Cell index

`cell_count` entries, each 24 bytes:

| Offset | Type | Field |
|---|---|---|
| 0 | i32 | `cell_lat` |
| 4 | i32 | `cell_lon` |
| 8 | u64 | `offset`: absolute file offset of the cell block |
| 16 | u32 | `length`: compressed byte length of the cell block |
| 20 | u32 | `first_junction`: id of the first junction in this cell |

Entries are sorted ascending by `(cell_lat, cell_lon)` as signed integers, with no duplicates. Lookup of a cell is a binary search on this key.

## 6. Junction ids

Junctions are numbered `0 .. junction_count - 1`, grouped by cell in index order: the junctions of index entry `i` have ids `first_junction[i] .. first_junction[i+1] - 1` (for the last entry, up to `junction_count - 1`). Hence `first_junction[0] = 0`, and every cell has at least one junction.

The cell of any junction id `j` is the last index entry with `first_junction <= j` (binary search).

Within a cell, writers in this repository order junctions by `(lat_e6, lon_e6, OSM node id)`; readers MUST NOT rely on that order.

## 7. Cell block

Each block is one raw DEFLATE stream. Its inflated payload is:

```
uvarint  junction_count_in_cell        (equals the id range size from section 6)
repeat junction_count_in_cell:
  svarint  d_lat                       (see below)
  svarint  d_lon
uvarint  edge_count_in_cell
repeat edge_count_in_cell:
  uvarint  d_a                         a = prev_a + d_a; prev_a starts at first_junction
  svarint  d_b                         b = a + d_b
  u8       flags                       bits 0-3 class, bits 4-5 oneway, bits 6-7 reserved (0)
  uvarint  point_count                 number of interior points
  repeat point_count:
    svarint  d_lat
    svarint  d_lon
```

The payload MUST end exactly after the last edge; trailing bytes are an error.

**Junction coordinates** are delta-coded: the first junction's deltas are relative to the cell origin `(cell_lat * cell_size_e6, cell_lon * cell_size_e6)`, each following junction relative to the previous junction of the same cell.

**Edges** are sorted by start junction `a` (non-decreasing), so `d_a >= 0`. Every edge in the block starts at a junction of this cell: `first_junction <= a < first_junction + junction_count_in_cell`. The end junction `b` is any id in `0 .. junction_count - 1`, possibly in another cell, possibly equal to `a` (a closed loop, which then has at least one interior point).

**Interior points** are delta-coded: the first point relative to the coordinate of junction `a`, each following point relative to the previous point. The full edge geometry is `a`, the interior points in order, then `b`. The geometry follows the travel direction of the source OSM way from `a` to `b`.

Edge ids are implicit: edges are numbered in index order and, within a cell, in block order. The total over all cells equals `edge_count`.

## 8. Edge flags

Bits 0-3, road class:

| Value | OSM `highway` |
|---|---|
| 0 | `motorway` |
| 1 | `motorway_link` |
| 2 | `trunk` |
| 3 | `trunk_link` |
| 4 | `primary` |
| 5 | `primary_link` |
| 6 | `secondary` |
| 7 | `secondary_link` |
| 8 | `tertiary` |
| 9 | `tertiary_link` |
| 10 | `unclassified` |
| 11 | `residential` |
| 12 | `living_street` |
| 13 | `service` |
| 14, 15 | reserved |

Bits 4-5, oneway:

| Value | Meaning |
|---|---|
| 0 | both directions |
| 1 | forward only (`a` to `b`) |
| 2 | backward only (`b` to `a`) |
| 3 | reserved |

## 9. Content (builder behaviour, informative)

Packs in this repository are built from Geofabrik OSM extracts with these rules; they do not change the binary format.

- Ways with `highway` in the class table above. `service` ways are dropped when `service` is `parking_aisle`, `driveway` or `drive-through`.
- Ways with `area=yes` are dropped (areas are not centrelines).
- Ways with `access=no` or `access=private` are dropped unless `motor_vehicle` is `yes` or `designated`.
- Oneway: `oneway=yes|1|true` gives forward, `oneway=-1` gives backward, `oneway=no|0|false` gives both; when `oneway` is absent or has another value, `highway=motorway` and `junction=roundabout|circular` imply forward, all other ways are both.
- Nodes without a valid location are skipped, consecutive duplicate nodes collapsed; ways with fewer than two nodes are dropped.
- A node becomes a junction if it is the first or last node of a way or is used more than once (by several ways, or twice by one way). Ways are split at junctions into edges.
- Each edge is simplified with Douglas-Peucker at 2 m tolerance on a local equirectangular projection; the end points are always kept.
- Coordinates are rounded from the OSM 10^-7 degree grid to 10^-6 degrees (half to even).
- Edges with `a == b` and no interior point after simplification are dropped.

## 10. Versioning

- `version_major` changes on any incompatible change. A reader MUST reject a file whose `version_major` it does not know.
- `version_minor` changes on backwards-compatible additions only, for example new header fields after `attribution` (before the index, which `index_offset` points to), or a meaning for reserved flag bits that older readers may ignore. A 1.0 reader MUST accept any 1.x file: it seeks to `index_offset`, ignores header bytes it does not know and ignores bits 6-7 of the edge flags.
- Class values 14-15 and oneway value 3 are reserved for future minor versions. A 1.0 reader encountering them SHOULD treat the edge as class unknown / both directions rather than failing.
- `flags` in the header is reserved; writers of 1.0 write 0, readers ignore it.

## 11. Validation

A reader SHOULD check, and the reference reader (`python -m orpk check`) checks:

1. `magic`, `version_major == 1`, `cell_size_e6 > 0`, `index_offset + 24 * cell_count <= file size`.
2. Index entries strictly ascending by `(cell_lat, cell_lon)`; blocks contiguous from `index_offset + 24 * cell_count` to end of file; `first_junction[0] == 0` and strictly increasing.
3. Each block inflates completely, its junction count matches the id range, and the payload has no trailing bytes.
4. Every junction lies in the cell of its index entry.
5. Every edge starts in its block's cell, `b < junction_count`, `d_a >= 0`, and `a == b` only with interior points.
6. Sums of junctions and edges equal `junction_count` and `edge_count`.
7. Every coordinate lies within the header bounding box, and the box is tight (each bound is reached by some coordinate).

## 12. Golden files

`tests/golden/` contains small packs built from synthetic OSM data by `tests/golden/make_golden.py`, each with its decoded form as JSON (`<name>.json`, produced by `python -m orpk dump`). A new reader implementation SHOULD decode every golden pack and compare against its JSON. Because DEFLATE output may differ between zlib implementations, byte comparison of rebuilt packs uses the canonical form: the header, the index entries without `offset` and `length`, and the inflated cell payloads.
