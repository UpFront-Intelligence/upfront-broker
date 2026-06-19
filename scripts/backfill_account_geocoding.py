#!/usr/bin/env python3
"""
One-time backfill: geocode every Account with an address but no lat/lng
(US Census batch geocoder — free, no API key), then propagate the result
to inherited Contacts (no distinct address of their own, still missing
lat/lng).

Idempotent — only ever selects rows with lat IS NULL, so re-running only
catches what's new since the last run; never re-geocodes a done row.

Usage:
    cd /opt/render/project/src
    python scripts/backfill_account_geocoding.py

DATABASE_URL is read from the environment (Render sets it automatically).
For local dev it falls back to backend/.env.
"""
import csv
import io
import os
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras
import requests

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CENSUS_BENCHMARK = "Public_AR_Current"
BATCH_MAX = 10000


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


# ── Census batch geocoder ─────────────────────────────────────────────────────

def geocode_batch(records):
    """records: list of (id, address, city, state, zip).
    Returns {id: (lat, lng) | None}."""
    if not records:
        return {}
    if len(records) > BATCH_MAX:
        sys.exit(f'ERROR: {len(records)} records exceeds the Census batch limit '
                  f'of {BATCH_MAX} per request — chunk the input before retrying.')

    buf = io.StringIO()
    writer = csv.writer(buf)
    for rid, address, city, state, zip_code in records:
        writer.writerow([rid, address or '', city or '', state or '', zip_code or ''])

    resp = requests.post(
        CENSUS_BATCH_URL,
        files={'addressFile': ('batch.csv', buf.getvalue().encode('utf-8'), 'text/csv')},
        data={'benchmark': CENSUS_BENCHMARK},
        timeout=300,
    )
    resp.raise_for_status()

    results = {}
    for row in csv.reader(io.StringIO(resp.text)):
        if len(row) < 3:
            continue
        try:
            rid = int(row[0])
        except ValueError:
            continue
        if row[2] != 'Match' or len(row) < 6:
            results[rid] = None
            continue
        try:
            lon_str, lat_str = row[5].split(',')
            results[rid] = (round(float(lat_str), 6), round(float(lon_str), 6))
        except (ValueError, IndexError):
            results[rid] = None
    for rid, *_ in records:
        results.setdefault(rid, None)
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_url = get_db_url()
    if not db_url:
        sys.exit('ERROR: DATABASE_URL not set.\n'
                  'Run: DATABASE_URL=postgresql://... python scripts/backfill_account_geocoding.py')

    print(f'[{datetime.now():%H:%M:%S}] Connecting to database…')
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, address, city, state, zip
        FROM   accounts
        WHERE  merged_into_id IS NULL
          AND  address IS NOT NULL AND address <> ''
          AND  lat IS NULL
        ORDER  BY id
    """)
    accounts = cur.fetchall()
    print(f'[{datetime.now():%H:%M:%S}] {len(accounts)} accounts have an address but no lat/lng\n')

    if not accounts:
        print('Nothing to do.')
        conn.close()
        return

    records = [(a['id'], a['address'], a['city'], a['state'], a['zip']) for a in accounts]
    print(f'[{datetime.now():%H:%M:%S}] Sending batch geocode request to Census '
          f'({len(records)} records)…')
    results = geocode_batch(records)

    success, fail = 0, 0
    for a in accounts:
        coords = results.get(a['id'])
        if coords:
            cur.execute("UPDATE accounts SET lat = %s, lng = %s WHERE id = %s",
                        (coords[0], coords[1], a['id']))
            success += 1
        else:
            fail += 1
    conn.commit()
    print(f'[{datetime.now():%H:%M:%S}] Geocoded {success} accounts — {fail} no-match/skip '
          f'(non-US or otherwise unmatchable)\n')

    # ── Propagate to inherited Contacts ───────────────────────────────────────
    # A Contact can link to more than one Account — prefer the primary link
    # per contact, same as the live geocode_contact_if_address_changed/
    # geocode_account_if_address_changed pair in backend/services/accounts.py.
    cur.execute("""
        SELECT DISTINCT ON (c.id) c.id AS contact_id, a.lat, a.lng
        FROM   contacts c
        JOIN   contact_accounts ca ON ca.contact_id = c.id
        JOIN   accounts a         ON a.id = ca.account_id
        WHERE  c.lat IS NULL
          AND  a.lat IS NOT NULL
          AND  (
                (c.address IS NULL AND c.city IS NULL AND c.state IS NULL)
                OR (c.address = a.address AND c.city = a.city AND c.state = a.state)
          )
        ORDER  BY c.id, ca.is_primary DESC
    """)
    inheriting = cur.fetchall()
    for row in inheriting:
        cur.execute("UPDATE contacts SET lat = %s, lng = %s WHERE id = %s",
                    (row['lat'], row['lng'], row['contact_id']))
    conn.commit()
    conn.close()

    print('=' * 60)
    print(f'Done at {datetime.now():%H:%M:%S}')
    print(f'  Accounts with address, no lat/lng     : {len(accounts)}')
    print(f'  Successfully geocoded                  : {success}')
    print(f'  No match / non-US / skipped            : {fail}')
    print(f'  Contacts back-filled via inheritance    : {len(inheriting)}')


if __name__ == '__main__':
    main()
