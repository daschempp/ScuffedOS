#!/usr/bin/env python3
"""Crop a PNG to its non-white content bounding box.

Used by build-app.sh's icon step: `qlmanage -t` thumbnails an SVG onto a
fixed square canvas but does not scale vector content to fill that canvas
(observed: a 48x48 logo-mark.svg renders into only the top-left corner of a
requested 1024x1024 thumbnail, padded with opaque white). This script finds
the bounding box of non-white pixels and writes a cropped PNG containing just
that content, so a subsequent `sips -z` upscale fills the icon frame.

Pure stdlib (zlib + struct) - no Pillow dependency, since the vendored build
environment does not have it installed system-wide.

Usage: _png_autocrop.py <in.png> <out.png>
Exits non-zero (with a message on stderr) if the image looks fully blank,
so the caller can fall back to a placeholder icon instead of shipping an
empty square.
"""
import struct
import sys
import zlib


def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    i = 8
    width = height = None
    colortype = None
    idat = bytearray()
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        ctype = data[i + 4 : i + 8]
        chunk = data[i + 8 : i + 8 + length]
        if ctype == b"IHDR":
            width, height, bitdepth, colortype = struct.unpack(">IIBB", chunk[:10])
            if bitdepth != 8 or colortype not in (2, 6):
                raise ValueError(
                    f"unsupported PNG format bitdepth={bitdepth} colortype={colortype}"
                    " (expected 8-bit RGB/RGBA)"
                )
        elif ctype == b"IDAT":
            idat += chunk
        i += 8 + length + 4
    raw = zlib.decompress(bytes(idat))
    bpp = 4 if colortype == 6 else 3
    stride = width * bpp
    prev = bytearray(stride)
    pos = 0
    pixels = bytearray(width * height * 4)
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        row = bytearray(raw[pos : pos + stride])
        pos += stride
        out = bytearray(stride)
        for x in range(stride):
            a = out[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            val = row[x]
            if ftype == 0:
                rec = val
            elif ftype == 1:
                rec = (val + a) & 0xFF
            elif ftype == 2:
                rec = (val + b) & 0xFF
            elif ftype == 3:
                rec = (val + ((a + b) // 2)) & 0xFF
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                rec = (val + pr) & 0xFF
            else:
                rec = val
            out[x] = rec
        prev = out
        # Normalize to RGBA regardless of source colortype.
        row_rgba_start = y * width * 4
        if bpp == 4:
            pixels[row_rgba_start : row_rgba_start + stride] = out
        else:
            for x in range(width):
                r, g, b = out[x * 3], out[x * 3 + 1], out[x * 3 + 2]
                o = row_rgba_start + x * 4
                pixels[o : o + 4] = bytes((r, g, b, 255))
    return width, height, pixels


def write_png(path, width, height, pixels):
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None) per row
        raw.extend(pixels[y * stride : (y + 1) * stride])
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <in.png> <out.png>", file=sys.stderr)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    w, h, px = read_png(src)
    minx, maxx, miny, maxy = w, 0, h, 0
    for y in range(h):
        row_start = y * w * 4
        for x in range(w):
            o = row_start + x * 4
            r, g, b = px[o], px[o + 1], px[o + 2]
            if not (r > 250 and g > 250 and b > 250):
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    if minx > maxx or miny > maxy:
        print(f"error: {src} appears fully blank (no non-white content found)", file=sys.stderr)
        return 1
    cw, ch = maxx - minx + 1, maxy - miny + 1
    cropped = bytearray(cw * ch * 4)
    for y in range(ch):
        src_start = ((miny + y) * w + minx) * 4
        dst_start = y * cw * 4
        cropped[dst_start : dst_start + cw * 4] = px[src_start : src_start + cw * 4]
    write_png(dst, cw, ch, cropped)
    print(f"cropped {src} ({w}x{h}) -> {dst} ({cw}x{ch}) bbox=({minx},{miny})-({maxx},{maxy})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
