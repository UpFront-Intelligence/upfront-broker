#!/usr/bin/env python3
"""
One-time backfill: geocode every Property with an address but no lat/lng
(Nominatim/OpenStreetMap — free, no API key; the same service the live
create/update Property endpoints already use via routers/properties.py's
_geocode()). Bulk imports (routers/imports.py, routers/import_properties_parties.py)
never called that function before this fix, so most imported properties were
missing coordinates — this catches up everything already in the database.

Nominatim's public usage policy caps requests at 1/second — there's no batch
endpoint like the Census geocoder Accounts/Contacts use, so this is a plain
loop with a sleep between requests. Expect ~1 second per property.

Idempotent — only ever selects rows with lat IS NULL, so re-running only
catches what's new since the last run; never re-geocodes a done row.

Usage:
    cd /opt/render/project/src
    python scripts/backfill_property_geocoding.py

DATABASE_URL is read from the environment (Render sets it automatically).
For local dev it falls back to backend/.env.
"""
import os
import re
import sys
import time
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "UpFrontBroker/1.0 (credetroit@gmail.com)"
RATE_LIMIT_SECONDS = 1.0


# ── DB connection ─────────────────────────────────────────────────────────────

def get_db_url() -> str:
    url = os.getenv('DATABASE_URL', '')
    if not url:
        env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
        if os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if line.startswith('DATABASE_URL='):
                    url = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


# ── Nominatim single-address geocode ──────────────────────────────────────────

def geocode_one(address, city, state):
    """Mirrors routers/properties.py's _geocode() exactly — same endpoint,
    params, User-Agent, and range-address normalization — so backfilled rows
    behave identically to ones geocoded live. Returns (lat, lng) or None."""
    # Normalize range house-numbers: "29551-29583 5 Mile Rd" → "29551 5 Mile Rd"
    # Same regex as _geocode() in routers/properties.py.
    geocode_addr = re.sub(r'^(\d+)-\d+(\s)', r'\1\2', address or '')
    q = ', '.join(filter(None, [geocode_addr, city, state, 'USA']))
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={'q': q, 'format': 'json', 'limit': 1, 'countrycodes': 'us'},
            headers={'User-Agent': USER_AGENT},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as exc:
        print(f'    request failed for {q!r}: {exc}')
        return None
    if not results:
        return None
    try:
        return round(float(results[0]['lat']), 6), round(float(results[0]['lon']), 6)
    except (KeyError, ValueError, IndexError):
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_url = get_db_url()
    if not db_url:
        sys.exit('ERROR: DATABASE_URL not set.\n'
                  'Run: DATABASE_URL=postgresql://... python scripts/backfill_property_geocoding.py')

    print(f'[{datetime.now():%H:%M:%S}] Connecting to database…')
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, address, city, state
        FROM   properties
        WHERE  address IS NOT NULL AND address <> ''
          AND  lat IS NULL
        ORDER  BY id
    """)
    properties = cur.fetchall()
    print(f'[{datetime.now():%H:%M:%S}] {len(properties)} properties have an address but no lat/lng')
    if properties:
        eta_min = len(properties) * RATE_LIMIT_SECONDS / 60
        print(f'    Nominatim allows ~1 request/second — estimated {eta_min:.1f} minutes\n')

    if not properties:
        print('Nothing to do.')
        conn.close()
        return

    success, fail = 0, 0
    for i, p in enumerate(properties, 1):
        coords = geocode_one(p['address'], p['city'], p['state'])
        if coords:
            cur.execute("UPDATE properties SET lat = %s, lng = %s WHERE id = %s",
                        (coords[0], coords[1], p['id']))
            conn.commit()
            success += 1
        else:
            fail += 1
        if i % 25 == 0 or i == len(properties):
            print(f'[{datetime.now():%H:%M:%S}] {i}/{len(properties)} processed '
                  f'({success} geocoded, {fail} no-match)')
        if i < len(properties):
            time.sleep(RATE_LIMIT_SECONDS)

    conn.close()
    print('=' * 60)
    print(f'Done at {datetime.now():%H:%M:%S}')
    print(f'  Properties with address, no lat/lng : {len(properties)}')
    print(f'  Successfully geocoded                : {success}')
    print(f'  No match / unmatchable                : {fail}')


if __name__ == '__main__':
    main()
