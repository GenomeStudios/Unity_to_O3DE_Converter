"""Probe: per-Geometry vertex bounds/centroid from a binary FBX.

Reveals WHERE a mesh's geometry actually sits in the FBX (node-local vs
modeled-in-place), which O3DE bakes into the .azmodel but Unity neutralizes
via the GO/instance placement. The centroid is the candidate source for an
automatic per-model centering compensation. See
`mem:transform_truth/transform_truth_plan`.

  python tools/fbx_geometry_bounds.py <file.fbx> [scale]
  (scale default 0.01 — FBX cm → Unity metres)
"""

import struct
import sys
import zlib
from pathlib import Path


def _read_array_doubles(data, pos):
    """Read an FBX 'd' double-array property payload (after the type byte)."""
    length, encoding, comp_len = struct.unpack("<III", data[pos:pos+12])
    pos += 12
    payload = data[pos:pos+comp_len]; pos += comp_len
    if encoding == 1:
        payload = zlib.decompress(payload)
    vals = struct.unpack(f"<{length}d", payload[:length*8])
    return list(vals), pos


def _scan_geometries(path, scale=0.01):
    data = Path(path).read_bytes()
    if data[:21] != b"Kaydara FBX Binary  \x00":
        return []
    version = struct.unpack("<I", data[23:27])[0]
    large = version >= 7500
    off_fmt, off_sz = ("<Q", 8) if large else ("<I", 4)

    results = []

    def read_props(pos, num, want_vertices):
        verts = None
        for _ in range(num):
            typ = chr(data[pos]); pos += 1
            if typ in "YCIFDL":
                pos += {"Y": 2, "C": 1, "I": 4, "F": 4, "D": 8, "L": 8}[typ]
            elif typ in "fdlib":
                if typ == "d" and want_vertices and verts is None:
                    verts, pos = _read_array_doubles(data, pos)
                else:
                    length, enc, comp = struct.unpack("<III", data[pos:pos+12])
                    pos += 12 + comp
            elif typ in "SR":
                ln = struct.unpack("<I", data[pos:pos+4])[0]; pos += 4 + ln
            else:
                raise ValueError(typ)
        return verts, pos

    def read_record(pos, parent_is_geometry=False):
        end_off = struct.unpack(off_fmt, data[pos:pos+off_sz])[0]; pos += off_sz
        num_prop = struct.unpack(off_fmt, data[pos:pos+off_sz])[0]; pos += off_sz
        pos += off_sz
        name_len = data[pos]; pos += 1
        name = data[pos:pos+name_len].decode("utf-8", "ignore"); pos += name_len
        if end_off == 0:
            return None, pos
        is_geom = (name == "Geometry")
        # node label (for Geometry, props[1] is the name)
        verts, pos = read_props(pos, num_prop, want_vertices=(name == "Vertices"))
        label = None
        # Peek first string prop for Geometry naming
        sentinel = 25 if large else 13
        local_verts = None
        if name == "Geometry":
            # props already consumed; re-read label cheaply from raw is messy —
            # instead capture child "Vertices".
            pass
        while pos < end_off - sentinel:
            child, pos = read_record(pos, parent_is_geometry=is_geom)
            if child is None:
                break
            if child.get("vertices") is not None and is_geom:
                local_verts = child["vertices"]
        out = {"name": name, "vertices": verts}
        if name == "Geometry" and local_verts:
            xs = local_verts[0::3]; ys = local_verts[1::3]; zs = local_verts[2::3]
            n = len(xs)
            def stat(a):
                return (min(a) * scale, max(a) * scale, (sum(a) / n) * scale)
            results.append({
                "verts": n,
                "x": stat(xs), "y": stat(ys), "z": stat(zs),
            })
        return out, end_off

    pos = 27
    try:
        while pos < len(data) - (25 if large else 13):
            rec, pos = read_record(pos)
            if rec is None:
                break
    except (ValueError, struct.error, IndexError):
        pass
    return results


def dump(path, scale=0.01):
    print(f"\n=== {Path(path).name}  (vertex bounds, metres @ scale {scale}) ===")
    geos = _scan_geometries(path, scale)
    if not geos:
        print("  (no geometry / not binary)")
        return
    for i, g in enumerate(geos):
        cx, cy, cz = g["x"][2], g["y"][2], g["z"][2]
        print(f"  geom[{i}] verts={g['verts']:6}  "
              f"centroid=({cx:+.3f}, {cy:+.3f}, {cz:+.3f})  "
              f"x[{g['x'][0]:+.2f},{g['x'][1]:+.2f}] "
              f"y[{g['y'][0]:+.2f},{g['y'][1]:+.2f}] "
              f"z[{g['z'][0]:+.2f},{g['z'][1]:+.2f}]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); raise SystemExit(2)
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0.01
    dump(sys.argv[1], scale)
