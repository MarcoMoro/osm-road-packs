"""Constants and primitive encodings shared by writer and reader (FORMAT.md sections 1, 3, 5, 8)."""

import struct

MAGIC = b"ORPK"
VERSION_MAJOR = 1
VERSION_MINOR = 0
CELL_SIZE_E6 = 50_000
ATTRIBUTION = "Data © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright"

# magic, major, minor, flags, osm_timestamp, bbox (4), cell_size, cell_count, junction_count, edge_count,
# index_offset, attribution_len
HEADER = struct.Struct("<4sHHIqiiiiiIIIIH")
INDEX_ENTRY = struct.Struct("<iiQII")

CLASSES = (
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service",
)
CLASS_ID = {name: i for i, name in enumerate(CLASSES)}

ONEWAY_BOTH, ONEWAY_FORWARD, ONEWAY_BACKWARD = 0, 1, 2


def cell_of(lat_e6, lon_e6, cell_size_e6=CELL_SIZE_E6):
    """Cell coordinates by floor division (Python // rounds towards negative infinity)."""
    return lat_e6 // cell_size_e6, lon_e6 // cell_size_e6


def put_uvarint(n, out):
    if n < 0:
        raise ValueError(f"uvarint of negative value {n}")
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def put_svarint(n, out):
    put_uvarint((n << 1) ^ (n >> 63), out)


class Cursor:
    """Sequential decoder over an inflated cell payload."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def uvarint(self):
        result = shift = 0
        start = self.pos
        while True:
            if self.pos >= len(self.data):
                raise ValueError("truncated varint")
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
            if shift >= 70:
                raise ValueError("varint longer than 10 bytes")
        if self.pos - start > 1 and b == 0:
            raise ValueError("non-minimal varint")
        if result >= 1 << 64:
            raise ValueError("varint exceeds 64 bits")
        return result

    def svarint(self):
        u = self.uvarint()
        return (u >> 1) ^ -(u & 1)

    def u8(self):
        if self.pos >= len(self.data):
            raise ValueError("truncated payload")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def at_end(self):
        return self.pos == len(self.data)
