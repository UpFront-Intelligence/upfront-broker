#!/usr/bin/env python3
"""Read-only recon for the Property Finder / parcel-prospecting feature.
No writes, no schema changes.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/diagnose_parcels_regrid_searchability.py

Answers, from real production data:
  1. Actual Postgres column type of raw_data (json vs jsonb -- determines
     whether it's indexable at all without a schema change).
  2. Actual indexes on parcels_regrid (confirmed against pg_indexes, not
     just the migration file).
  3. A real raw_data JSON sample + key-frequency survey across a larger
     sample, so we know which fields are actually populated in practice.
  4. A real geometry_wkt sample (format, coordinate order) to assess
     centroid computation.
  5. Scale sanity: distinct city/zip/county counts.
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


def main():
    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = True
    pg = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=" * 78)
    print("1. raw_data COLUMN TYPE (json vs jsonb)")
    print("=" * 78)
    pg.execute("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'parcels_regrid' AND column_name = 'raw_data'
    """)
    print(f"  {pg.fetchone()}")

    print("\n" + "=" * 78)
    print("2. ACTUAL INDEXES on parcels_regrid")
    print("=" * 78)
    pg.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'parcels_regrid'")
    for r in pg.fetchall():
        print(f"  {r['indexname']}: {r['indexdef']}")

    print("\n" + "=" * 78)
    print("3. RAW_DATA sample (3 real rows) + key-frequency survey (sample of 300)")
    print("=" * 78)
    pg.execute("""
        SELECT parcel_id, owner_raw, address, raw_data
        FROM parcels_regrid WHERE source_county = 'oakland' AND raw_data IS NOT NULL
        LIMIT 3
    """)
    for r in pg.fetchall():
        print(f"\n  --- parcel_id={r['parcel_id']} owner={r['owner_raw']!r} address={r['address']!r} ---")
        rd = r['raw_data']
        for k in sorted(rd.keys()):
            print(f"    {k!r}: {rd[k]!r}")

    pg.execute("""
        SELECT raw_data FROM parcels_regrid
        WHERE source_county = 'oakland' AND raw_data IS NOT NULL
        LIMIT 300
    """)
    key_counter = Counter()
    total = 0
    for r in pg.fetchall():
        total += 1
        for k, v in (r['raw_data'] or {}).items():
            if v not in (None, ''):
                key_counter[k] += 1
    print(f"\n  Key population rate across {total} sampled rows (key: count, %):")
    for k, c in key_counter.most_common(40):
        print(f"    {k:30s} {c:>4}/{total}  ({100*c/total:.0f}%)")

    print("\n" + "=" * 78)
    print("4. geometry_wkt SAMPLE (format + coordinate order check)")
    print("=" * 78)
    pg.execute("""
        SELECT parcel_id, address, geometry_wkt FROM parcels_regrid
        WHERE source_county = 'oakland' AND geometry_wkt IS NOT NULL
        LIMIT 3
    """)
    for r in pg.fetchall():
        wkt = r['geometry_wkt'] or ''
        print(f"\n  parcel_id={r['parcel_id']}  address={r['address']!r}")
        print(f"  geometry type prefix: {wkt.split('(')[0].strip() if '(' in wkt else wkt[:20]!r}")
        print(f"  first 200 chars: {wkt[:200]!r}")
        print(f"  total length: {len(wkt)} chars")

    print("\n" + "=" * 78)
    print("5. SCALE sanity")
    print("=" * 78)
    pg.execute("SELECT source_county, COUNT(*) AS n FROM parcels_regrid GROUP BY source_county ORDER BY n DESC")
    for r in pg.fetchall():
        print(f"  {r['source_county']:15s} {r['n']:>8,} rows")
    pg.execute("SELECT COUNT(DISTINCT city) AS n FROM parcels_regrid")
    print(f"  distinct cities (all counties): {pg.fetchone()['n']:,}")
    pg.execute("SELECT COUNT(DISTINCT zip) AS n FROM parcels_regrid")
    print(f"  distinct zips (all counties): {pg.fetchone()['n']:,}")

    conn.close()
    print("\n" + "=" * 78)
    print("Done. No writes were made.")
    print("=" * 78)


if __name__ == "__main__":
    main()
