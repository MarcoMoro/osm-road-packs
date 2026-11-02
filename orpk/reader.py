"""Reference reader and validator for ORPK v1 (FORMAT.md sections 3-7, 11)."""

import json
import re
import zlib

from .codec import HEADER, INDEX_ENTRY, MAGIC, VERSION_MAJOR, Cursor, cell_of


class PackError(ValueError):
    pass


def dump_json(doc):
    """Indented JSON with arrays of plain numbers kept on one line."""
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    text = re.sub(r"\[[\s\d,\-]*\]", lambda m: "[" + ", ".join(re.findall(r"-?\d+", m.group())) + "]", text)
    return text + "\n"


def inflate_raw(data):
    d = zlib.decompressobj(-15)
    out = d.decompress(data) + d.flush()
    if not d.eof or d.unused_data:
        raise PackError("cell block is not exactly one complete deflate stream")
    return out


class Cell:
    def __init__(self, cell_lat, cell_lon, first_junction, junctions, edges, payload):
        self.cell_lat = cell_lat
        self.cell_lon = cell_lon
        self.first_junction = first_junction
        self.junctions = junctions  # [(lat_e6, lon_e6)]
        self.edges = edges  # [(a, b, class, oneway, flags, [(lat_e6, lon_e6)])]
        self.payload = payload


class Pack:
    def __init__(self, data):
        self.data = data
        if len(data) < HEADER.size:
            raise PackError("file shorter than header")
        (magic, self.version_major, self.version_minor, self.flags, self.osm_timestamp,
         self.min_lat, self.min_lon, self.max_lat, self.max_lon, self.cell_size,
         self.cell_count, self.junction_count, self.edge_count, self.index_offset,
         attr_len) = HEADER.unpack_from(data, 0)
        if magic != MAGIC:
            raise PackError(f"bad magic {magic!r}")
        if self.version_major != VERSION_MAJOR:
            raise PackError(f"unsupported major version {self.version_major}")
        if self.cell_size <= 0:
            raise PackError("cell size must be positive")
        if HEADER.size + attr_len > len(data):
            raise PackError("attribution exceeds file")
        self.attribution = data[HEADER.size:HEADER.size + attr_len].decode("utf-8")
        if self.index_offset < HEADER.size + attr_len:
            raise PackError("index overlaps header")
        if self.index_offset + INDEX_ENTRY.size * self.cell_count > len(data):
            raise PackError("index exceeds file")
        self.index = [INDEX_ENTRY.unpack_from(data, self.index_offset + INDEX_ENTRY.size * i)
                      for i in range(self.cell_count)]

    @classmethod
    def open(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def junction_range(self, i):
        first = self.index[i][4]
        end = self.index[i + 1][4] if i + 1 < self.cell_count else self.junction_count
        return first, end

    def cell(self, i):
        clat, clon, offset, length, first = self.index[i]
        payload = inflate_raw(self.data[offset:offset + length])
        cur = Cursor(payload)
        n_j = cur.uvarint()
        lat, lon = clat * self.cell_size, clon * self.cell_size
        junctions = []
        for _ in range(n_j):
            lat += cur.svarint()
            lon += cur.svarint()
            junctions.append((lat, lon))
        edges = []
        a = first
        for _ in range(cur.uvarint()):
            d_a = cur.uvarint()
            a += d_a
            b = a + cur.svarint()
            flags = cur.u8()
            if not first <= a < first + n_j:
                raise PackError(f"cell {i}: edge start {a} outside cell junctions")
            lat, lon = junctions[a - first]
            pts = []
            for _ in range(cur.uvarint()):
                lat += cur.svarint()
                lon += cur.svarint()
                pts.append((lat, lon))
            edges.append((a, b, flags & 0x0F, (flags >> 4) & 0x03, flags, pts))
        if not cur.at_end():
            raise PackError(f"cell {i}: trailing bytes in payload")
        return Cell(clat, clon, first, junctions, edges, payload)

    def cells(self):
        for i in range(self.cell_count):
            yield self.cell(i)

    def check(self):
        """Validate all invariants of FORMAT.md section 11; raise PackError on the first violation."""
        expect = self.index_offset + INDEX_ENTRY.size * self.cell_count
        prev_key = None
        prev_first = -1
        n_j = n_e = 0
        lo_lat = lo_lon = hi_lat = hi_lon = None
        for i, (clat, clon, offset, length, first) in enumerate(self.index):
            if prev_key is not None and (clat, clon) <= prev_key:
                raise PackError(f"index entry {i} not strictly ascending")
            prev_key = (clat, clon)
            if offset != expect:
                raise PackError(f"cell {i}: block offset {offset}, expected {expect}")
            expect += length
            if (i == 0 and first != 0) or first <= prev_first:
                raise PackError(f"cell {i}: bad first_junction {first}")
            prev_first = first
        if expect != len(self.data):
            raise PackError(f"blocks end at {expect}, file size {len(self.data)}")
        if self.cell_count and self.index[-1][4] >= self.junction_count:
            raise PackError("last cell has no junctions")
        for i in range(self.cell_count):
            c = self.cell(i)
            first, end = self.junction_range(i)
            if len(c.junctions) != end - first:
                raise PackError(f"cell {i}: {len(c.junctions)} junctions, id range {end - first}")
            for lat, lon in c.junctions:
                if cell_of(lat, lon, self.cell_size) != (c.cell_lat, c.cell_lon):
                    raise PackError(f"cell {i}: junction ({lat}, {lon}) outside cell")
            coords = list(c.junctions)
            prev_a = first
            for a, b, _, _, _, pts in c.edges:
                if a < prev_a:
                    raise PackError(f"cell {i}: edges not sorted by start junction")
                prev_a = a
                if not 0 <= b < self.junction_count:
                    raise PackError(f"cell {i}: edge end {b} out of range")
                if a == b and not pts:
                    raise PackError(f"cell {i}: loop edge without interior points")
                coords.extend(pts)
            for lat, lon in coords:
                if lo_lat is None:
                    lo_lat = hi_lat = lat
                    lo_lon = hi_lon = lon
                lo_lat, hi_lat = min(lo_lat, lat), max(hi_lat, lat)
                lo_lon, hi_lon = min(lo_lon, lon), max(hi_lon, lon)
            n_j += len(c.junctions)
            n_e += len(c.edges)
        if n_j != self.junction_count or n_e != self.edge_count:
            raise PackError(f"counts {n_j}/{n_e} vs header {self.junction_count}/{self.edge_count}")
        bbox = (self.min_lat, self.min_lon, self.max_lat, self.max_lon)
        actual = (lo_lat, lo_lon, hi_lat, hi_lon) if lo_lat is not None else (0, 0, 0, 0)
        if bbox != actual:
            raise PackError(f"header bbox {bbox} differs from data extent {actual}")

    def canonical_bytes(self):
        """Header, index without offset/length, inflated payloads: independent of the deflate implementation."""
        out = bytearray(self.data[:self.index_offset])
        for i, (clat, clon, _, _, first) in enumerate(self.index):
            out += INDEX_ENTRY.pack(clat, clon, 0, 0, first)
        for c in self.cells():
            out += len(c.payload).to_bytes(4, "little") + c.payload
        return bytes(out)

    def to_json(self):
        return {
            "format": "ORPK",
            "version": f"{self.version_major}.{self.version_minor}",
            "osm_timestamp": self.osm_timestamp,
            "bbox": [self.min_lat, self.min_lon, self.max_lat, self.max_lon],
            "cell_size_e6": self.cell_size,
            "attribution": self.attribution,
            "junction_count": self.junction_count,
            "edge_count": self.edge_count,
            "cells": [
                {
                    "cell_lat": c.cell_lat,
                    "cell_lon": c.cell_lon,
                    "first_junction": c.first_junction,
                    "junctions": [list(j) for j in c.junctions],
                    "edges": [
                        {"a": a, "b": b, "class": cls, "oneway": ow, "points": [list(p) for p in pts]}
                        for a, b, cls, ow, _, pts in c.edges
                    ],
                }
                for c in self.cells()
            ],
        }
