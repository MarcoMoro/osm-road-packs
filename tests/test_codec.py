import zlib

import pytest

from orpk.codec import Cursor, cell_of, put_svarint, put_uvarint
from orpk.filter import e7_to_e6
from orpk.graph import build_graph
from orpk.reader import Pack, PackError
from orpk.simplify import douglas_peucker
from orpk.writer import encode


@pytest.mark.parametrize("n", [0, 1, 127, 128, 300, 2**32, 2**63 - 1])
def test_uvarint_round_trip(n):
    out = bytearray()
    put_uvarint(n, out)
    assert Cursor(bytes(out)).uvarint() == n


@pytest.mark.parametrize("n", [0, -1, 1, -64, 64, -(2**31), 2**31, -(2**63)])
def test_svarint_round_trip(n):
    out = bytearray()
    put_svarint(n, out)
    assert Cursor(bytes(out)).svarint() == n


def test_varint_bytes():
    out = bytearray()
    put_uvarint(300, out)
    assert bytes(out) == b"\xac\x02"
    out = bytearray()
    put_svarint(-1, out)
    assert bytes(out) == b"\x01"


def test_non_minimal_varint_rejected():
    with pytest.raises(ValueError):
        Cursor(b"\x80\x00").uvarint()


def test_cell_of_floors_towards_negative_infinity():
    assert cell_of(47012345, 8540000) == (940, 170)
    assert cell_of(47000000, 0) == (940, 0)
    assert cell_of(-1, -1) == (-1, -1)
    assert cell_of(-50000, -50001) == (-1, -2)


def test_e7_to_e6_half_to_even():
    assert e7_to_e6(15) == 2
    assert e7_to_e6(25) == 2
    assert e7_to_e6(-15) == -2
    assert e7_to_e6(-25) == -2
    assert e7_to_e6(14) == 1
    assert e7_to_e6(-16) == -2


def test_douglas_peucker_keeps_ends_and_drops_small_deviation():
    pts = [(47000000, 8000000), (47000010, 8000500), (47000000, 8001000)]  # ~1.1 m off
    assert douglas_peucker(pts, 2.0) == [pts[0], pts[2]]
    pts = [(47000000, 8000000), (47000050, 8000500), (47000000, 8001000)]  # ~5.5 m off
    assert douglas_peucker(pts, 2.0) == pts


def small_pack():
    ways = [(11, 0, [(1, 47000000, 8000000), (2, 47000000, 8001000)]),
            (11, 0, [(2, 47000000, 8001000), (3, 47001000, 8001000)])]
    return encode(build_graph(ways), 0)[0]


def test_check_detects_corruption():
    data = bytearray(small_pack())
    Pack(bytes(data)).check()
    with pytest.raises(PackError):
        Pack(b"XRPK" + bytes(data[4:]))
    with pytest.raises(PackError):
        Pack(bytes(data) + b"\x00").check()
    bad_version = bytearray(data)
    bad_version[4] = 2
    with pytest.raises(PackError):
        Pack(bytes(bad_version))


def test_check_detects_trailing_payload_bytes():
    p = Pack(small_pack())
    clat, clon, offset, length, first = p.index[0]
    payload = p.cell(0).payload + b"\x00"
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    block = c.compress(payload) + c.flush()
    data = bytearray(p.data[:offset]) + block
    data[p.index_offset + 16:p.index_offset + 20] = len(block).to_bytes(4, "little")
    with pytest.raises(PackError):
        Pack(bytes(data)).check()
