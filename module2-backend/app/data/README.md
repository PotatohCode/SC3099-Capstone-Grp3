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
