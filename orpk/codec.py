"""Constants and primitive encodings shared by writer and reader (FORMAT.md sections 1, 3, 5, 7, 8)."""

import struct

MAGIC = b"ORPK"
FORMAT_NAME = MAGIC.decode("ascii")
VERSION_MAJOR = 1
VERSION_MINOR = 1
CELL_SIZE_E6 = 50_000
MAX_PAYLOAD = 1 << 24  # inflated bytes per cell block (FORMAT.md section 7)
ATTRIBUTION = "Data © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

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


class PackError(ValueError):
    """Malformed or invalid pack."""


def cell_of(lat_e6, lon_e6, cell_size_e6=CELL_SIZE_E6):
    """Cell coordinates by floor division (Python // rounds towards negative infinity)."""
    return lat_e6 // cell_size_e6, lon_e6 // cell_size_e6


def pack_flags(cls, oneway, private=False):
    return cls | (oneway << 4) | (int(private) << 6)


def unpack_flags(flags):
    """(class, oneway, private); reserved bit 7 is ignored."""
    return flags & 0x0F, (flags >> 4) & 0x03, bool(flags & 0x40)


class Extent:
    """Running bounding box over (lat_e6, lon_e6) points."""

    def __init__(self):
        self.box = None

    def add(self, pts):
        if not pts:
            return
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        box = (min(lats), min(lons), max(lats), max(lons))
        if self.box:
            box = (min(box[0], self.box[0]), min(box[1], self.box[1]),
                   max(box[2], self.box[2]), max(box[3], self.box[3]))
        self.box = box

    def bbox(self):
        """(min_lat, min_lon, max_lat, max_lon), all zero when empty."""
        return self.box or (0, 0, 0, 0)


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


def put_points(pts, origin, out):
    """Delta-code points, the first relative to origin, each next relative to the previous point."""
    plat, plon = origin
    for lat, lon in pts:
        put_svarint(lat - plat, out)
        put_svarint(lon - plon, out)
        plat, plon = lat, lon


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
                raise PackError("truncated varint")
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
            if shift >= 70:
                raise PackError("varint longer than 10 bytes")
        if self.pos - start > 1 and b == 0:
            raise PackError("non-minimal varint")
        if result >= 1 << 64:
            raise PackError("varint exceeds 64 bits")
        return result

    def svarint(self):
        u = self.uvarint()
        return (u >> 1) ^ -(u & 1)

    def points(self, n, origin):
        """Inverse of put_points for n points."""
        lat, lon = origin
        pts = []
        for _ in range(n):
            lat += self.svarint()
            lon += self.svarint()
            pts.append((lat, lon))
        return pts

    def u8(self):
        if self.pos >= len(self.data):
            raise PackError("truncated payload")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def at_end(self):
        return self.pos == len(self.data)
