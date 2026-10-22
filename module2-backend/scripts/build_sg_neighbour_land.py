#!/usr/bin/env python3
"""
Build app/data/sg-neighbour-land.json: Malaysian and Indonesian land inside
the Singapore GPS bounding box, used by services/singapore_check.py.

The box (lat 1.15-1.48, lon 103.59-104.10) also covers Johor Bahru, Pasir
Gudang, Pengerang and Batam's north coast, so a point inside the box isn't
necessarily in Singapore. The check rejects points that fall on this land.

Input: geoBoundaries gbOpen ADM0 GeoJSON for MYS and IDN (OpenStreetMap,
ODbL 1.0), e.g. build 9469f09:
  https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/MYS/ADM0/geoBoundaries-MYS-ADM0.geojson
  https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IDN/ADM0/geoBoundaries-IDN-ADM0.geojson

Usage:
  python scripts/build_sg_neighbour_land.py MYS.geojson IDN.geojson app/data/sg-neighbour-land.json

Each polygon ring is clipped to the box (Sutherland-Hodgman, so only the
part inside the box is kept) and rounded to 5 decimals (~1 m). The script
then checks the clipped data against the full data on a grid and refuses to
write the file if any point disagrees.
"""
import json
import sys

from app.services.singapore_check import SG_LAT_MAX, SG_LAT_MIN, SG_LON_MAX, SG_LON_MIN, point_in_polygons

PAD = 0.01  # clip slightly outside the box so its edges are covered


def clip_ring(ring, lo_x, hi_x, lo_y, hi_y):
    """Sutherland-Hodgman clip of one ring ([lon, lat] points) to a rectangle."""
    def clip(points, inside, cross):
        out = []
        for i, cur in enumerate(points):
            prev = points[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def at_x(x):
        return lambda a, b: [x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])]

    def at_y(y):
        return lambda a, b: [a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y]

    pts = ring[:-1] if ring and ring[0] == ring[-1] else ring
    for inside, cross in ((lambda p: p[0] >= lo_x, at_x(lo_x)), (lambda p: p[0] <= hi_x, at_x(hi_x)),
                          (lambda p: p[1] >= lo_y, at_y(lo_y)), (lambda p: p[1] <= hi_y, at_y(hi_y))):
        if not pts:
            break
        pts = clip(pts, inside, cross)
    return [[round(x, 5), round(y, 5)] for x, y in pts]


def polygons(path):
    out = []
    for feature in json.load(open(path, encoding="utf-8"))["features"]:
        geom = feature["geometry"]
        out += geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return out


def main(mys, idn, dest):
    box = (SG_LON_MIN - PAD, SG_LON_MAX + PAD, SG_LAT_MIN - PAD, SG_LAT_MAX + PAD)
    full, clipped = [], []
    for path in (mys, idn):
        for poly in polygons(path):
            outer = clip_ring(poly[0], *box)
            if len(outer) < 3:
                continue
            holes = [h for h in (clip_ring(r, *box) for r in poly[1:]) if len(h) >= 3]
            full.append(poly)
            clipped.append([outer] + holes)

    # Verify: clipped data must give the same answer as the full data everywhere in the box.
    step, mismatches, n = 0.002, 0, 0  # ~220 m grid
    lat = SG_LAT_MIN
    while lat <= SG_LAT_MAX:
        lon = SG_LON_MIN
        while lon <= SG_LON_MAX:
            n += 1
            if point_in_polygons(lat, lon, full) != point_in_polygons(lat, lon, clipped):
                mismatches += 1
            lon += step
        lat += step
    if mismatches:
        sys.exit(f"refusing to write: {mismatches}/{n} grid points disagree with the full data")

    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({
            "about": "Malaysian and Indonesian land inside the Singapore GPS box; see app/data/README.md",
            "source": "geoBoundaries gbOpen ADM0 MYS + IDN (build 9469f09), from OpenStreetMap",
            "licence": "ODbL 1.0 - (c) OpenStreetMap contributors, via geoBoundaries",
            "polygons": clipped,
        }, fh, separators=(",", ":"))
    vertices = sum(len(r) for p in clipped for r in p)
    print(f"wrote {dest}: {len(clipped)} polygons, {vertices} vertices; grid check {n} points, 0 mismatches")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
