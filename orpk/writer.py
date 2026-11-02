"""Encode a junction graph as an ORPK v1 file (FORMAT.md sections 2-8)."""

import zlib

from .codec import (
    ATTRIBUTION, CELL_SIZE_E6, HEADER, INDEX_ENTRY, MAGIC, VERSION_MAJOR, VERSION_MINOR,
    cell_of, put_svarint, put_uvarint,
)


def deflate_raw(data, level):
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def encode(graph, osm_timestamp=0, attribution=ATTRIBUTION, level=9):
    """Return (pack bytes, stats dict)."""
    cs = CELL_SIZE_E6
    jcell = {nid: cell_of(lat, lon) for nid, (lat, lon) in graph.junctions.items()}
    order = sorted(graph.junctions, key=lambda nid: (jcell[nid], graph.junctions[nid], nid))
    jid = {nid: i for i, nid in enumerate(order)}

    cells = []  # (cell, first_junction, [junction coords], [edges])
    for i, nid in enumerate(order):
        c = jcell[nid]
        if not cells or cells[-1][0] != c:
            cells.append((c, i, [], []))
        cells[-1][2].append(graph.junctions[nid])
    cell_pos = {c[0]: k for k, c in enumerate(cells)}
    for a, b, cls, oneway, inner in graph.edges:
        cells[cell_pos[jcell[a]]][3].append((jid[a], jid[b], cls | (oneway << 4), inner))

    lats = [lat for lat, _ in graph.junctions.values()]
    lons = [lon for _, lon in graph.junctions.values()]
    for e in graph.edges:
        lats.extend(p[0] for p in e[4])
        lons.extend(p[1] for p in e[4])
    bbox = (min(lats), min(lons), max(lats), max(lons)) if lats else (0, 0, 0, 0)

    blocks = []
    raw_total = 0
    for (clat, clon), first, jcoords, edges in cells:
        out = bytearray()
        put_uvarint(len(jcoords), out)
        plat, plon = clat * cs, clon * cs
        for lat, lon in jcoords:
            put_svarint(lat - plat, out)
            put_svarint(lon - plon, out)
            plat, plon = lat, lon
        edges.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
        put_uvarint(len(edges), out)
        prev_a = first
        for a, b, flags, inner in edges:
            put_uvarint(a - prev_a, out)
            put_svarint(b - a, out)
            prev_a = a
            out.append(flags)
            put_uvarint(len(inner), out)
            plat, plon = jcoords[a - first]
            for lat, lon in inner:
                put_svarint(lat - plat, out)
                put_svarint(lon - plon, out)
                plat, plon = lat, lon
        raw_total += len(out)
        blocks.append(deflate_raw(bytes(out), level))

    attr = attribution.encode("utf-8")
    index_offset = HEADER.size + len(attr)
    header = HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, 0, osm_timestamp, *bbox, cs,
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
        "interior_points": sum(len(e[4]) for e in graph.edges),
        "cells": len(cells),
        "payload_raw_bytes": raw_total,
        "file_bytes": len(data),
    }
    return data, stats
