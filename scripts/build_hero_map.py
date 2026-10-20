#!/usr/bin/env python3
"""Build decorative regional map from Natural Earth's public-domain 1:50m polygons.

Source: https://github.com/nvkelso/natural-earth-vector
Terms: https://www.naturalearthdata.com/about/terms-of-use/
No incident coordinates are inferred by this map. Route is illustrative only.
"""
import json
import math
import urllib.request
from pathlib import Path
from html import escape

SOURCE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson'
WEST, EAST, SOUTH, NORTH = 20, 65, 8, 50
WIDTH, HEIGHT = 1100, 600
# Equirectangular projection, true scale at 30 degrees north, fitted and centered.
SCALE = min(WIDTH / ((EAST-WEST)*math.cos(math.radians(30))), HEIGHT/(NORTH-SOUTH))
XOFF = (WIDTH-(EAST-WEST)*math.cos(math.radians(30))*SCALE)/2
VIEW_WEST = WEST-XOFF/(math.cos(math.radians(30))*SCALE)
VIEW_EAST = EAST+XOFF/(math.cos(math.radians(30))*SCALE)

def point(lon, lat):
    return XOFF+(lon-WEST)*math.cos(math.radians(30))*SCALE, (NORTH-lat)*SCALE

def coords(points):
    return ' '.join(f'{x:.2f},{y:.2f}' for x,y in (point(*p) for p in points))

def path(points):
    return 'M'+' L'.join(f'{x:.2f} {y:.2f}' for x,y in (point(*p) for p in points))

def main():
    with urllib.request.urlopen(SOURCE) as response:
        data=json.load(response)
    out=['''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 600" aria-hidden="true" focusable="false" class="maritime-geography">
<!-- Geographic source: Natural Earth 1:50m Admin 0 countries (public domain).
https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_50m_admin_0_countries.geojson
https://www.naturalearthdata.com/about/terms-of-use/
Viewport: approximately 2°W–87°E, 8–50°N. Focus: Black Sea, Red Sea, Strait of Hormuz.
Equirectangular projection, standard parallel 30°N.
Region markers identify monitored seas, never individual attacks. Route is illustrative. -->
<defs><clipPath id="hero-map-clip"><rect x="0" y="0" width="1100" height="600" rx="24"/></clipPath></defs>
<g clip-path="url(#hero-map-clip)">
<rect class="map-water" width="1100" height="600" fill="#dce9e7"/>
<g class="map-grid" fill="none" stroke="#a8c5c3" stroke-width=".6" opacity=".5">''']
    for lon in range(math.ceil(VIEW_WEST/5)*5,math.floor(VIEW_EAST/5)*5+1,5):
        out.append(f'<path d="{path([(lon,SOUTH),(lon,NORTH)])}"/>')
    for lat in range(10,51,5):
        out.append(f'<path d="{path([(VIEW_WEST,lat),(VIEW_EAST,lat)])}"/>')
    out.append('</g><g class="map-land-group" fill="#ece9d9" stroke="#b6c6bc" stroke-width=".7" stroke-linejoin="round">')
    for feature in sorted(data['features'], key=lambda f:f['properties'].get('ADMIN','')):
        geom=feature['geometry']
        polys = geom['coordinates'] if geom['type']=='MultiPolygon' else [geom['coordinates']]
        for rings in polys:
            flat=[p for ring in rings for p in ring]
            if not flat or max(p[0] for p in flat)<VIEW_WEST or min(p[0] for p in flat)>VIEW_EAST or max(p[1] for p in flat)<SOUTH or min(p[1] for p in flat)>NORTH:
                continue
            d=' '.join(path(ring)+' Z' for ring in rings)
            out.append(f'<path class="map-land" data-country="{escape(feature["properties"].get("ADMIN",""),quote=True)}" fill-rule="evenodd" d="{d}"/>')
    out.append('</g><g class="map-country" fill="#72877b" font-family="sans-serif" font-size="10" letter-spacing="2" text-anchor="middle">')
    for name,lon,lat in [('UKRAINE',31.5,48),('TÜRKİYE',34.3,39),('EGYPT',29,26.5),('SAUDI ARABIA',44,24),('IRAN',54,33),('OMAN',57,20.5),('YEMEN',46.8,15.5),('SUDAN',30.5,16.5),('ERITREA',38.4,15.2),('ROMANIA',25,46)]:
        x,y=point(lon,lat)
        out.append(f'<text x="{x:.2f}" y="{y:.2f}">{name}</text>')
    out.append('</g>')
    # Waypoints follow open sea and the Suez Canal; do not curve a shortcut over land.
    route=[(34.5,43),(30.5,42),(29.1,41.3),(29.0,41.05),(28.95,40.9),(28.3,40.65),(27.5,40.65),(26.7,40.4),(26.4,40.05),(26.2,39.85),(25.5,39.2),(25,37.4),(26.5,35.2),(29,33.3),(32.30,31.30),(32.31,31.05),(32.33,30.80),(32.31,30.60),(32.40,30.40),(32.52,30.28),(32.57,30.05),(32.55,29.90),(33.1,28.7),(33.8,27.7),(34.5,26.5),(35.7,24.5),(37,22.5),(38.2,20.5),(39.7,18.4),(41.1,16.2),(42.5,14.5),(43.3,12.7),(43.5,12.5),(45,12),(48.5,12.5),(51.5,14),(54,17),(58,20),(60,23),(59,24.5),(57.5,25.3),(56.5,25.8),(56.3,26.5)]
    d=path(route)
    out.append(f'<path id="hero-route-path" class="map-route" d="{d}" fill="none" stroke="#628c8b" stroke-width="2" stroke-dasharray="3 7"/>')
    out.append(f'<path id="hero-trail" d="{d}" fill="none" stroke="#ca734b" stroke-width="2.5" opacity=".7"/>')
    x,y=point(*route[0])
    out.append(f'<g id="hero-vessel" transform="translate({x:.2f} {y:.2f})" fill="#254c4c" stroke="#fffaf0" stroke-width="1.4"><path d="M19 0 L8 -6 L-14 -6 L-18 -3 L-18 3 L-14 6 L8 6 Z"/><path class="hero-vessel-deck" d="M-8 -3 H5 V3 H-8 Z" fill="#eacb96" stroke="none"/></g>')
    for slug,label,lon,lat,dx,dy in [('Black Sea','BLACK SEA',34.5,43,32,-22),('Red Sea','RED SEA',38,20.3,-100,-20),('Strait of Hormuz','STRAIT OF HORMUZ',56.3,26.5,32,-23)]:
        x,y=point(lon,lat)
        out.append(f'<g class="map-region" data-region="{slug}" transform="translate({x:.2f} {y:.2f})"><circle class="map-region-halo" r="20" fill="#cf7648" opacity=".13"/><circle class="map-region-ring map-marker-ring" r="10" fill="none" stroke="#b86b46" stroke-width="1"/><circle class="map-region-core map-marker" r="4" fill="#b86b46"/><path class="map-region-leader map-leader" d="M 9 -7 L {dx} {dy+5}" stroke="#a86b4d" fill="none"/><text class="map-region-label map-label" x="{dx}" y="{dy}" fill="#284d4c" font-family="sans-serif" font-size="12" font-weight="700" letter-spacing="1.8">{label}</text><text class="map-region-coordinates map-label-small" x="{dx}" y="{dy+17}" fill="#647e77" font-family="monospace" font-size="9">{lat:.1f}°N / {lon:.1f}°E</text></g>')
    out.append('</g><text x="28" y="572" class="map-caption" fill="#647e77" font-family="sans-serif" font-size="10">Illustrative maritime route · Regional markers are not vessel positions</text><text x="1072" y="590" text-anchor="end" class="map-attribution" fill="#7d9188" font-family="sans-serif" font-size="9">Geography: Natural Earth · Public domain</text></svg>')
    target=Path(__file__).resolve().parents[1]/'site'/'maritime-map.svg'
    target.write_text('\n'.join(out)+'\n')
    print(f'Wrote {target} ({target.stat().st_size:,} bytes)')

if __name__=='__main__':
    main()
