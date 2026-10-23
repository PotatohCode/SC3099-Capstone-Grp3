# Bundled data

## `dbip-country-lite.mmdb`

IP-to-country database used by `app/services/singapore_check.py` for the
Singapore-only check-in rule. Bundled (not downloaded at build time) so the
check works offline and the Docker build doesn't depend on DB-IP's
month-stamped download URL still existing.

- Source: DB-IP "IP to Country Lite", 2026-10 edition
  (`https://download.db-ip.com/free/dbip-country-lite-2026-10.mmdb.gz`)
- Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) —
  IP geolocation by [DB-IP](https://db-ip.com)
- Refresh: download the current month's `.mmdb.gz`, gunzip, and replace this
  file (same name). No code change needed.

## `sg-neighbour-land.json`

Malaysian and Indonesian land that falls inside the Singapore GPS bounding
box (Johor Bahru, Pasir Gudang, Pengerang, Batam's north coast). The GPS part
of the Singapore-only rule rejects points on this land
(`app/services/singapore_check.py`). 4 polygons, ~2,300 vertices, clipped to
the box.

- Source: [geoBoundaries](https://www.geoboundaries.org) gbOpen ADM0 for MYS
  and IDN, build `9469f09`, derived from OpenStreetMap
- Licence: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) —
  © OpenStreetMap contributors, via geoBoundaries. This extract is shared
  under the same licence.
- Rebuild: download the two `geoBoundaries-{MYS,IDN}-ADM0.geojson` files
  (URLs in the script), then run
  `python scripts/build_sg_neighbour_land.py MYS.geojson IDN.geojson app/data/sg-neighbour-land.json`
  inside the backend container (it imports `app`). The script refuses to
  write the file unless the clipped data matches the full data on a ~220 m
  grid.
