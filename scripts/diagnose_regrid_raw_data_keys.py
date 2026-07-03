#!/usr/bin/env python3
"""Read-only recon: what keys actually exist in parcels_regrid.raw_data
right now, in production? No writes, no schema changes.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/diagnose_regrid_raw_data_keys.py

Checks for BOTH possible naming conventions rather than assuming one:
  - the "bonus" clean keys scripts/ingest_regrid_metro.py's enhanced version
    was designed to add (bldg_sqft, year_built, num_units) -- IF that
    enhanced ingest has actually been run against production since it was
    built two turns ago (unconfirmed from this session -- no DB access here
    to check directly)
  - the raw original Regrid CSV column names the catch-all always includes
    regardless (area_building, ll_bldg_footprint_sqft, yearbuilt, numunits)
    -- these would be present even under the OLDER ingest run, if the
    enhanced version hasn't actually been run yet

Also confirms parcels_regrid's new columns (usecode, assessed_value, etc.)
actually have real values in production -- another thing this session
can't verify without a DB connection.
"""
import os
import sys
from collections import Counter

import psycopg2
import psycopg2.extras


def _get_db_url():
    url = (os.environ.get("PROD_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        sys.exit("ERROR: set PROD_DATABASE_URL (or DATABASE_URL) as an env var for this invocation.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


CANDIDATE_KEYS = [
    "bldg_sqft", "year_built", "num_units",              # new "bonus" keys, if the enhanced ingest ran
    "area_building", "ll_bldg_footprint_sqft",            # raw building-SF candidates
    "yearbuilt", "numunits",                              # raw year/units candidates
]


def main():
    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = True
    pg = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=" * 78)
    print("0. Sanity: do the new dedicated columns (migration 97ff9ec4ed1c) have real values?")
    print("=" * 78)
    pg.execute("""
        SELECT COUNT(*) AS total,
               COUNT(usecode) AS n_usecode,
               COUNT(assessed_value) AS n_assessed_value,
               COUNT(lot_acres) AS n_lot_acres,
               COUNT(centroid_lat) AS n_centroid_lat
        FROM parcels_regrid
    """)
    r = pg.fetchone()
    print(f"  {r}")
    if r["total"] and r["n_usecode"] == 0:
        print("  ⚠️  usecode is 0/", r["total"], "-- the enhanced ingest (with the new columns)")
        print("      has NOT been run against this database yet. raw_data bonus keys below")
        print("      almost certainly won't exist either -- only the raw CSV column names will.")

    print("\n" + "=" * 78)
    print("1. Sample raw_data blobs -- 2 per county, full key dump")
    print("=" * 78)
    pg.execute("SELECT DISTINCT source_county FROM parcels_regrid ORDER BY source_county")
    counties = [r["source_county"] for r in pg.fetchall()]
    print(f"  Counties present: {counties}")

    for county in counties:
        pg.execute("""
            SELECT parcel_id, address, raw_data FROM parcels_regrid
            WHERE source_county = %s AND raw_data IS NOT NULL
            LIMIT 2
        """, (county,))
        for row in pg.fetchall():
            print(f"\n  --- {county} / parcel_id={row['parcel_id']} address={row['address']!r} ---")
            rd = row["raw_data"] or {}
            for k in sorted(rd.keys()):
                print(f"    {k!r}: {rd[k]!r}")

    print("\n" + "=" * 78)
    print("2. Candidate key population rate across a larger sample (500 rows, all counties)")
    print("=" * 78)
    pg.execute("SELECT raw_data FROM parcels_regrid WHERE raw_data IS NOT NULL LIMIT 500")
    total = 0
    key_counter = Counter()
    for row in pg.fetchall():
        total += 1
        rd = row["raw_data"] or {}
        for k in CANDIDATE_KEYS:
            if rd.get(k) not in (None, ''):
                key_counter[k] += 1
    print(f"  Sampled {total} rows:")
    for k in CANDIDATE_KEYS:
        c = key_counter.get(k, 0)
        print(f"    {k:25s} {c:>4}/{total}  ({100*c/total:.1f}%)" if total else f"    {k}: n/a")

    conn.close()
    print("\nDone. No writes were made.")


if __name__ == "__main__":
    main()
