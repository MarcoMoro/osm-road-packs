"""Encode a junction graph as an ORPK v1 file (FORMAT.md sections 2-8)."""

import zlib

import numpy as np

from .codec import (
    ATTRIBUTION, CELL_SIZE_E6, HEADER, INDEX_ENTRY, MAGIC, VERSION_MAJOR, VERSION_MINOR,
    Extent, put_points, put_svarint, put_uvarint,
)


def deflate_raw(data, level):
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def inner_points(graph, start, count):
    return list(zip(graph.inner_lat[start:start + count].tolist(), graph.inner_lon[start:start + count].tolist()))


def edge_order(graph, ja, jb):
    """Edge indices sorted by (a, b, flags, interior points), the order of FORMAT.md section 6."""
    order = np.lexsort((graph.edge_flags, jb, ja))
    a, b, f = ja[order], jb[order], graph.edge_flags[order]
    ties = np.flatnonzero((a[1:] == a[:-1]) & (b[1:] == b[:-1]) & (f[1:] == f[:-1]))
    for run in np.split(ties, np.flatnonzero(np.diff(ties) != 1) + 1):
        if len(run):
            lo, hi = run[0], run[-1] + 2
            order[lo:hi] = sorted(order[lo:hi].tolist(), key=lambda k: inner_points(graph, int(graph.inner_start[k]), int(graph.inner_count[k])))
    return order


def encode(graph, osm_timestamp=0, attribution=ATTRIBUTION, level=9):
    """Return (pack bytes, stats dict)."""
    g = graph
    clat, clon = g.junction_lat // CELL_SIZE_E6, g.junction_lon // CELL_SIZE_E6
    order = np.lexsort((g.junction_ids, g.junction_lon, g.junction_lat, clon, clat))
    jid = np.empty_like(order)
    jid[order] = np.arange(len(order))
    ja, jb = jid[np.searchsorted(g.junction_ids, g.edge_a)], jid[np.searchsorted(g.junction_ids, g.edge_b)]
    eorder = edge_order(g, ja, jb)
    ja, jb, flags = ja[eorder], jb[eorder], g.edge_flags[eorder]
    inner_start, inner_count = g.inner_start[eorder], g.inner_count[eorder]

    clat, clon, jlat, jlon = clat[order], clon[order], g.junction_lat[order], g.junction_lon[order]
    firsts = np.flatnonzero(np.r_[True, (clat[1:] != clat[:-1]) | (clon[1:] != clon[:-1])]) if len(order) else order
    bounds = np.append(firsts, len(order))
    edge_bounds = np.searchsorted(ja, bounds).tolist()

    extent = Extent()
    blocks = []
    cells = []  # (cell lat, cell lon, first junction)
    raw_total = 0
    for k, first in enumerate(firsts.tolist()):
        end = int(bounds[k + 1])
        cell = int(clat[first]), int(clon[first])
        cells.append((*cell, first))
        jcoords = list(zip(jlat[first:end].tolist(), jlon[first:end].tolist()))
        out = bytearray()
        put_uvarint(len(jcoords), out)
        put_points(jcoords, (cell[0] * CELL_SIZE_E6, cell[1] * CELL_SIZE_E6), out)
        cell_pts = list(jcoords)
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
            inner = inner_points(g, o, c)
            put_points(inner, jcoords[a - first], out)
            cell_pts.extend(inner)
        extent.add(cell_pts)
        raw_total += len(out)
        blocks.append(deflate_raw(out, level))

    attr = attribution.encode("utf-8")
    index_offset = HEADER.size + len(attr)
    header = HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, 0, osm_timestamp, *extent.bbox(), CELL_SIZE_E6,
                         len(cells), len(order), len(g.edge_a), index_offset, len(attr)) + attr
    offset = index_offset + INDEX_ENTRY.size * len(cells)
    index = bytearray()
    for (cell_lat, cell_lon, first), block in zip(cells, blocks):
        index += INDEX_ENTRY.pack(cell_lat, cell_lon, offset, len(block), first)
        offset += len(block)
    data = header + bytes(index) + b"".join(blocks)
    stats = {
        "ways": g.ways,
        "junctions": len(order),
        "edges": len(g.edge_a),
        "interior_points": len(g.inner_lat),
        "cells": len(cells),
        "payload_raw_bytes": raw_total,
        "file_bytes": len(data),
    }
    return data, stats
