"""Encode a junction graph as an ORPK v1 file (FORMAT.md sections 2-8)."""

import zlib

from .codec import (
    ATTRIBUTION, CELL_SIZE_E6, HEADER, INDEX_ENTRY, MAGIC, VERSION_MAJOR, VERSION_MINOR,
    Extent, cell_of, pack_flags, put_points, put_svarint, put_uvarint,
)


def deflate_raw(data, level):
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def encode(graph, osm_timestamp=0, attribution=ATTRIBUTION, level=9):
    """Return (pack bytes, stats dict)."""
    order = sorted((cell_of(lat, lon), lat, lon, nid) for nid, (lat, lon) in graph.junctions.items())
    jid = {key[3]: i for i, key in enumerate(order)}

    cells = []  # (cell, first_junction, [junction coords], [edges])
    for i, (c, lat, lon, _) in enumerate(order):
        if not cells or cells[-1][0] != c:
            cells.append((c, i, [], []))
        cells[-1][2].append((lat, lon))
    cell_pos = {c[0]: k for k, c in enumerate(cells)}
    for a, b, cls, oneway, inner in graph.edges:
        ja = jid[a]
        cells[cell_pos[order[ja][0]]][3].append((ja, jid[b], pack_flags(cls, oneway), inner))

    extent = Extent()
    blocks = []
    raw_total = interior = 0
    for (clat, clon), first, jcoords, edges in cells:
        out = bytearray()
        put_uvarint(len(jcoords), out)
        put_points(jcoords, (clat * CELL_SIZE_E6, clon * CELL_SIZE_E6), out)
        cell_pts = list(jcoords)
        edges.sort()
        put_uvarint(len(edges), out)
        prev_a = first
        for a, b, flags, inner in edges:
            put_uvarint(a - prev_a, out)
            put_svarint(b - a, out)
            prev_a = a
            out.append(flags)
            put_uvarint(len(inner), out)
            put_points(inner, jcoords[a - first], out)
            cell_pts.extend(inner)
            interior += len(inner)
        extent.add(cell_pts)
        raw_total += len(out)
        blocks.append(deflate_raw(out, level))

    attr = attribution.encode("utf-8")
    index_offset = HEADER.size + len(attr)
    header = HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, 0, osm_timestamp, *extent.bbox(), CELL_SIZE_E6,
                         len(cells), len(order), len(graph.edges), index_offset, len(attr)) + attr
    offset = index_offset + INDEX_ENTRY.size * len(cells)
    index = bytearray()
    for ((clat, clon), first, _, _), block in zip(cells, blocks):
        index += INDEX_ENTRY.pack(clat, clon, offset, len(block), first)
        offset += len(block)
    data = header + bytes(index) + b"".join(blocks)
    stats = {
        "ways": graph.ways,
        "junctions": len(order),
        "edges": len(graph.edges),
        "interior_points": interior,
        "cells": len(cells),
        "payload_raw_bytes": raw_total,
        "file_bytes": len(data),
    }
    return data, stats
