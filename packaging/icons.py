"""The one icon, read from packaging/paperpull.ico for every package.

The .ico holds plain DIB entries rather than PNGs, and Pillow is not in the
build environment, so the largest entry is read pixel by pixel and written as
a PNG by hand. Every platform's icon assets start from that PNG.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def ico_largest_png(ico: Path) -> bytes:
    """The largest image in a .ico, as PNG bytes. The entries are plain DIBs
    (32-bit BGRA, bottom-up, followed by a mask that is ignored), so this
    reads the pixels and writes a PNG by hand rather than needing Pillow in
    the build environment."""
    d = ico.read_bytes()
    count = struct.unpack("<H", d[4:6])[0]
    best = None
    for i in range(count):
        w, h, _cc, _r, _pl, bpp, size, off = struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i])
        w, h = w or 256, h or 256
        if best is None or w > best[0]:
            best = (w, h, bpp, size, off)
    w, h, bpp, size, off = best
    blob = d[off:off + size]
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return blob
    hdr = struct.unpack("<IiiHHII", blob[:24])
    if hdr[3] != 1 or hdr[4] != 32:
        raise SystemExit("icon entry is not 32-bit, cannot convert without Pillow")
    px = blob[hdr[0]:]
    row = w * 4
    raw = bytearray()
    for y in range(h - 1, -1, -1):
        raw.append(0)
        line = px[y * row:(y + 1) * row]
        for x in range(0, row, 4):
            b, g, r, a = line[x:x + 4]
            raw += bytes((r, g, b, a))

    def chunk(kind, body):
        c = struct.pack(">I", len(body)) + kind + body
        return c + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))
