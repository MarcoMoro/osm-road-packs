"""Encode a junction graph as an ORPK v1 file (FORMAT.md sections 2-8)."""

import zlib

import numpy as np

from .codec import (
    ATTRIBUTION, CELL_SIZE_E6, HEADER, INDEX_ENTRY, MAGIC, MAX_PAYLOAD, VERSION_MAJOR, VERSION_MINOR,
    cell_of, put_points, put_svarint, put_uvarint,
)


def deflate_raw(data, level):
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def inner_points(graph, start, count):
    return list(zip(graph.inner_lat[start:start + count].tolist(), graph.inner_lon[start:start + count].tolist()))


def edge_order(graph, ja, jb, inner_start):
    """Edge indices sorted by (a, b, flags, interior points).

    FORMAT.md section 7 requires the order by a; the rest keeps the output deterministic.
    """
    order = np.lexsort((graph.edge_flags, jb, ja))
    a, b, f = ja[order], jb[order], graph.edge_flags[order]
    ties = np.flatnonzero((a[1:] == a[:-1]) & (b[1:] == b[:-1]) & (f[1:] == f[:-1]))
    if len(ties):
        for run in np.split(ties, np.flatnonzero(np.diff(ties) != 1) + 1):
            lo, hi = run[0], run[-1] + 2
            order[lo:hi] = sorted(order[lo:hi].tolist(),
                                  key=lambda k: inner_points(graph, inner_start[k], graph.inner_count[k]))
    return order


def bbox(graph):
    """(min_lat, min_lon, max_lat, max_lon) over junctions and interior points, all zero when empty."""
    if not len(graph.junction_lat):
        return 0, 0, 0, 0
    lats = np.concatenate((graph.junction_lat, graph.inner_lat))
    lons = np.concatenate((graph.junction_lon, graph.inner_lon))
    return int(lats.min()), int(lons.min()), int(lats.max()), int(lons.max())


def encode(graph, osm_timestamp=0, attribution=ATTRIBUTION, level=9):
    """Return (pack bytes, stats dict)."""
    clat, clon = cell_of(graph.junction_lat, graph.junction_lon)
    order = np.lexsort((graph.junction_ids, graph.junction_lon, graph.junction_lat, clon, clat))
    jid = np.empty_like(order)
    jid[order] = np.arange(len(order))
    ja = jid[np.searchsorted(graph.junction_ids, graph.edge_a)]
    jb = jid[np.searchsorted(graph.junction_ids, graph.edge_b)]
    inner_start = np.cumsum(graph.inner_count) - graph.inner_count
    eorder = edge_order(graph, ja, jb, inner_start)
    ja, jb, flags = ja[eorder], jb[eorder], graph.edge_flags[eorder]
    inner_start, inner_count = inner_start[eorder], graph.inner_count[eorder]

    clat, clon, jlat, jlon = clat[order], clon[order], graph.junction_lat[order], graph.junction_lon[order]
    firsts = np.flatnonzero(np.r_[True, (clat[1:] != clat[:-1]) | (clon[1:] != clon[:-1])]) if len(order) else order
    bounds = np.append(firsts, len(order)).tolist()
    edge_bounds = np.searchsorted(ja, bounds).tolist()
    cell_lats, cell_lons = clat[firsts].tolist(), clon[firsts].tolist()

    blocks = []
    raw_total = 0
    for k, (cell_lat, cell_lon) in enumerate(zip(cell_lats, cell_lons)):
        first, end = bounds[k], bounds[k + 1]
        jcoords = list(zip(jlat[first:end].tolist(), jlon[first:end].tolist()))
        out = bytearray()
        put_uvarint(len(jcoords), out)
        put_points(jcoords, (cell_lat * CELL_SIZE_E6, cell_lon * CELL_SIZE_E6), out)
        lo, hi = edge_bounds[k], edge_bounds[k + 1]
        put_uvarint(hi - lo, out)
        prev_a = first
        for a, b, f, o, c in zip(ja[lo:hi].tolist(), jb[lo:hi].tolist(), flags[lo:hi].tolist(),
                                 inner_start[lo:hi].tolist(), inner_count[lo:hi].tolist()):
            put_uvarint(a - prev_a, out)
            put_svarint(b - a, out)
            prev_a = a
            out.append(f)
            put_uvarint(c, out)
            put_points(inner_points(graph, o, c), jcoords[a - first], out)
        if len(out) > MAX_PAYLOAD:
            raise ValueError(f"cell ({cell_lat}, {cell_lon}) payload of {len(out)} bytes exceeds {MAX_PAYLOAD}")
        raw_total += len(out)
        blocks.append(deflate_raw(out, level))

    attr = attribution.encode("utf-8")
    index_offset = HEADER.size + len(attr)
    header = HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, 0, osm_timestamp, *bbox(graph), CELL_SIZE_E6,
                         len(blocks), len(order), len(graph.edge_a), index_offset, len(attr)) + attr
    offset = index_offset + INDEX_ENTRY.size * len(blocks)
    index = bytearray()
    for cell_lat, cell_lon, first, block in zip(cell_lats, cell_lons, bounds, blocks):
        index += INDEX_ENTRY.pack(cell_lat, cell_lon, offset, len(block), first)
        offset += len(block)
    data = header + bytes(index) + b"".join(blocks)
    stats = {
        "ways": graph.ways,
        "junctions": len(order),
        "edges": len(graph.edge_a),
        "interior_points": len(graph.inner_lat),
        "cells": len(blocks),
        "payload_raw_bytes": raw_total,
        "file_bytes": len(data),
    }
    return data, stats
