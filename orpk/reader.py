"""Reference reader and validator for ORPK v1 (FORMAT.md sections 3-7, 11)."""

import json
import zlib
from typing import NamedTuple

from .codec import (
    FORMAT_NAME, HEADER, INDEX_ENTRY, MAGIC, VERSION_MAJOR, Cursor, Extent, PackError, cell_of, unpack_flags,
)

__all__ = ["Cell", "Edge", "Pack", "PackError", "dump_json"]


def inflate_raw(data):
    d = zlib.decompressobj(-15)
    try:
        out = d.decompress(data) + d.flush()
    except zlib.error as e:
        raise PackError(f"cell block does not inflate: {e}") from e
    if not d.eof or d.unused_data:
        raise PackError("cell block is not exactly one complete deflate stream")
    return out


def dump_json(doc):
    """Indented JSON (one space per level) with lists of integers kept on one line."""
    out = []

    def emit(v, depth):
        pad = " " * (depth + 1)
        if isinstance(v, dict):
            if not v:
                out.append("{}")
                return
            out.append("{\n")
            for k, (key, val) in enumerate(v.items()):
                out.append(pad + json.dumps(key, ensure_ascii=False) + ": ")
                emit(val, depth + 1)
                out.append(",\n" if k < len(v) - 1 else "\n")
            out.append(" " * depth + "}")
        elif isinstance(v, list):
            if all(type(x) is int for x in v):
                out.append("[" + ", ".join(map(str, v)) + "]")
                return
            out.append("[\n")
            for k, val in enumerate(v):
                out.append(pad)
                emit(val, depth + 1)
                out.append(",\n" if k < len(v) - 1 else "\n")
            out.append(" " * depth + "]")
        else:
            out.append(json.dumps(v, ensure_ascii=False))

    emit(doc, 0)
    return "".join(out) + "\n"


class Edge(NamedTuple):
    a: int
    b: int
    cls: int
    oneway: int
    private: bool  # access=private without a motor_vehicle=yes|designated override (format 1.1)
    points: list  # [(lat_e6, lon_e6)] interior points


class Cell(NamedTuple):
    cell_lat: int
    cell_lon: int
    first_junction: int
    junctions: list  # [(lat_e6, lon_e6)]
    edges: list  # [Edge]
    payload: bytes


class Pack:
    def __init__(self, data):
        self.data = data
        if len(data) < HEADER.size:
            raise PackError("file shorter than header")
        (magic, self.version_major, self.version_minor, _flags, self.osm_timestamp,
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
        try:
            self.attribution = data[HEADER.size:HEADER.size + attr_len].decode("utf-8")
        except UnicodeDecodeError as e:
            raise PackError(f"attribution is not UTF-8: {e}") from e
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
        junctions = cur.points(cur.uvarint(), (clat * self.cell_size, clon * self.cell_size))
        edges = []
        a = first
        for _ in range(cur.uvarint()):
            a += cur.uvarint()
            b = a + cur.svarint()
            cls, oneway, private = unpack_flags(cur.u8())
            if not first <= a < first + len(junctions):
                raise PackError(f"cell {i}: edge start {a} outside cell junctions")
            pts = cur.points(cur.uvarint(), junctions[a - first])
            edges.append(Edge(a, b, cls, oneway, private, pts))
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
        extent = Extent()
        n_j = n_e = 0
        for i in range(self.cell_count):
            c = self.cell(i)
            first, end = self.junction_range(i)
            if len(c.junctions) != end - first:
                raise PackError(f"cell {i}: {len(c.junctions)} junctions, id range {end - first}")
            for lat, lon in c.junctions:
                if cell_of(lat, lon, self.cell_size) != (c.cell_lat, c.cell_lon):
                    raise PackError(f"cell {i}: junction ({lat}, {lon}) outside cell")
            cell_pts = list(c.junctions)
            for e in c.edges:
                if not 0 <= e.b < self.junction_count:
                    raise PackError(f"cell {i}: edge end {e.b} out of range")
                if e.a == e.b and not e.points:
                    raise PackError(f"cell {i}: loop edge without interior points")
                cell_pts.extend(e.points)
            extent.add(cell_pts)
            n_j += len(c.junctions)
            n_e += len(c.edges)
        if n_j != self.junction_count or n_e != self.edge_count:
            raise PackError(f"counts {n_j}/{n_e} vs header {self.junction_count}/{self.edge_count}")
        bbox = (self.min_lat, self.min_lon, self.max_lat, self.max_lon)
        if bbox != extent.bbox():
            raise PackError(f"header bbox {bbox} differs from data extent {extent.bbox()}")

    def canonical_bytes(self):
        """Header, index without offset/length, inflated payloads: independent of the deflate implementation."""
        out = bytearray(self.data[:self.index_offset])
        for clat, clon, _, _, first in self.index:
            out += INDEX_ENTRY.pack(clat, clon, 0, 0, first)
        for c in self.cells():
            out += len(c.payload).to_bytes(4, "little") + c.payload
        return bytes(out)

    def to_json(self):
        return {
            "format": FORMAT_NAME,
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
                        {"a": e.a, "b": e.b, "class": e.cls, "oneway": e.oneway, "private": e.private,
                         "points": [list(p) for p in e.points]}
                        for e in c.edges
                    ],
                }
                for c in self.cells()
            ],
        }
