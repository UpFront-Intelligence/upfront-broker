#!/usr/bin/env python3
"""Six-county filtered Regrid ingest into production parcels_regrid.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/ingest_regrid_metro.py

Reads PROD_DATABASE_URL (falls back to DATABASE_URL) from environment only
— never hardcoded, never printed.

Builds on the proven pattern from scripts/ingest_regrid_oakland.py's STEP 1
(stream-decompress + psycopg2.extras.execute_values batch UPSERT) — that
ingest path was already validated against a real 245k-row Oakland file
(zero parse errors, ~350 rows/s). The difference here: every row is passed
through backend/services/regrid_usecode_filter.py's filter_row() BEFORE
being queued for upsert, so only the counties that need filtering
(standard/detroit strategies) actually get filtered — Macomb's
'macomb_unfiltered' strategy keeps every row and tags it instead, per
CLAUDE.md's PARCELS_REGRID note on why Macomb can't be reliably filtered
yet (92.8% null usecode, concentrated by municipality).

Column-mapping constants and _first_present() are imported directly from
services/regrid.py rather than re-copied, per this repo's "one real
function, not two copies" convention (see CLAUDE.md's naming.py note) —
these are the same names ingest_csv() already uses, confirmed against the
real mi_oakland.csv.gz header on 2026-06-29.

CRITICAL detail (per explicit instruction): filter_row() returns
(keep, tags). tags is NOT a CSV column — it's synthesized by the filter
module (e.g. {'source_note': 'macomb_unfiltered'}) and must be merged into
raw_data explicitly, or the Macomb tag silently never lands anywhere. Done
below immediately after filter_row() returns, before raw_data is
JSON-serialized.

reconciliation_status / matched_account_id / matched_property_id are
deliberately absent from the UPSERT's DO UPDATE SET clause — same rule as
ingest_csv(): a re-run of this script (idempotent by design) must never
silently undo a reconciliation a broker has already confirmed.
"""
import csv
import gzip
import io
import json
import os
import sys
import time
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import psycopg2
import psycopg2.extras

from services.regrid import (
    _PARCEL_ID_KEYS, _OWNER_KEYS, _ADDRESS_KEYS, _CITY_KEYS,
    _STATE_KEYS, _ZIP_KEYS, _COUNTY_KEYS, _GEOMETRY_KEYS,
    _ALL_CRITICAL_KEYS, _first_present,
)
from services.naming import normalize_name
from services.regrid_usecode_filter import filter_row

DATA_DIR = "/Users/michaelsw/Desktop/REGRID DATA DONT MOVE/"
BATCH_SIZE = 1000
MAX_ERRORS = 50
PROGRESS_EVERY_SECS = 10

# (filename in DATA_DIR, source_county value to store) — in the order requested.
FILES = [
    ("mi_oakland.csv.gz", "oakland"),
    ("mi_washtenaw.csv.gz", "washtenaw"),
    ("mi_livingston.csv.gz", "livingston"),
    ("mi_wayne.csv.gz", "wayne"),
    ("mi_wayne_detroit.csv.gz", "wayne_detroit"),
    ("mi_genesee.csv.gz", "genesee"),
    ("mi_macomb.csv.gz", "macomb"),
]

# From the verified filter-only audit (2026-07-02) — "kept by usecode filter
# alone", NOT adjusted for rows missing parcel_id. Used only to flag
# divergence in the final report; actual upserted counts may be a hair
# lower if any kept-by-filter row also lacks a usable parcel_id.
EXPECTED_KEPT = {
    "mi_oakland.csv.gz": 30_783,
    "mi_washtenaw.csv.gz": 13_558,
    "mi_livingston.csv.gz": 9_704,
    "mi_wayne.csv.gz": 66_631,
    "mi_wayne_detroit.csv.gz": 101_888,
    "mi_genesee.csv.gz": 16_210,
    "mi_macomb.csv.gz": 332_871,
}

UPSERT_SQL = """
INSERT INTO parcels_regrid
  (parcel_id, owner_raw, owner_normalized, address, city, state, zip, county,
   geometry_wkt, raw_data, source_county, reconciliation_status)
VALUES %s
ON CONFLICT (parcel_id, source_county) DO UPDATE SET
  owner_raw         = EXCLUDED.owner_raw,
  owner_normalized  = EXCLUDED.owner_normalized,
  address           = EXCLUDED.address,
  city              = EXCLUDED.city,
  state             = EXCLUDED.state,
  zip               = EXCLUDED.zip,
  county            = EXCLUDED.county,
  geometry_wkt      = EXCLUDED.geometry_wkt,
  raw_data          = EXCLUDED.raw_data
"""


def _get_db_url():
    url = (os.environ.get("PROD_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        sys.exit("ERROR: set PROD_DATABASE_URL (or DATABASE_URL) as an env var for this invocation.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _dedupe_batch(batch):
    """Collapses rows within a single batch that share the same
    (parcel_id, source_county) key. psycopg2's execute_values with
    ON CONFLICT DO UPDATE cannot affect the same row twice in one
    statement (raises CardinalityViolation) -- Washtenaw's source file has
    duplicate parcelnumb values within a 1000-row window, Oakland's didn't.

    Keeps the LAST occurrence for a given key (simple, deterministic).
    Cross-batch duplicates are NOT handled here and don't need to be: the
    UPSERT is idempotent on (parcel_id, source_county), so a duplicate
    landing in a later batch just harmlessly re-updates the row a prior
    batch already inserted. This function only needs to catch same-batch
    collisions, which are the only ones that crash.

    Returns (deduped_rows: list, n_collapsed: int). n_collapsed is a lower
    bound on the source file's total duplication -- it only counts
    duplicates that happen to land within the same 1000-row batch.
    """
    deduped = {}
    for row in batch:
        key = (row[0], row[10])  # (parcel_id, source_county)
        deduped[key] = row
    return list(deduped.values()), len(batch) - len(deduped)


def _flush(pg, batch):
    if not batch:
        return 0, 0
    deduped, n_collapsed = _dedupe_batch(batch)
    psycopg2.extras.execute_values(pg, UPSERT_SQL, deduped, page_size=len(deduped))
    return len(deduped), n_collapsed


def ingest_one_file(conn, filename, source_county):
    path = os.path.join(DATA_DIR, filename)
    print("\n" + "=" * 70)
    print(f"{filename}  ->  source_county={source_county!r}  ({datetime.now():%H:%M:%S})")
    print("=" * 70)

    pg = conn.cursor()

    rows_read = 0
    rows_filtered_out = 0     # dropped by regrid_usecode_filter.filter_row()
    rows_skipped_no_id = 0    # kept by filter but no usable parcel_id
    rows_upserted = 0
    rows_duplicates_collapsed = 0  # same (parcel_id, source_county) seen twice in one batch
    errors = []
    batch = []
    t0 = time.time()
    last_print = t0

    with gzip.open(path, "rb") as gz:
        text_stream = io.TextIOWrapper(gz, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_stream)

        for row_num, raw in enumerate(reader, start=2):  # row 1 = header
            rows_read += 1
            row = {(k or "").strip().lower(): v for k, v in raw.items() if k is not None}

            keep, tags = filter_row(row, filename)
            if not keep:
                rows_filtered_out += 1
                continue

            parcel_id = _first_present(row, _PARCEL_ID_KEYS)
            if not parcel_id:
                rows_skipped_no_id += 1
                if len(errors) < MAX_ERRORS:
                    errors.append(f"Row {row_num}: kept by filter but missing parcel_id")
                continue

            owner_raw = _first_present(row, _OWNER_KEYS)
            address = _first_present(row, _ADDRESS_KEYS)
            city = _first_present(row, _CITY_KEYS)
            state = _first_present(row, _STATE_KEYS)
            zip_code = _first_present(row, _ZIP_KEYS)
            county = _first_present(row, _COUNTY_KEYS)
            geometry = _first_present(row, _GEOMETRY_KEYS)

            try:
                owner_norm = normalize_name(owner_raw) if owner_raw else None
            except Exception:
                owner_norm = None

            raw_data_dict = {k: v for k, v in row.items() if k not in _ALL_CRITICAL_KEYS and v}
            raw_data_dict.update(tags)  # e.g. {'source_note': 'macomb_unfiltered'} — lands in raw_data
            raw_data = json.dumps(raw_data_dict)

            batch.append((
                parcel_id, owner_raw, owner_norm, address, city, state,
                zip_code, county, geometry, raw_data, source_county, "pending",
            ))

            if len(batch) >= BATCH_SIZE:
                n_upserted, n_collapsed = _flush(pg, batch)
                rows_upserted += n_upserted
                rows_duplicates_collapsed += n_collapsed
                conn.commit()
                batch.clear()
                now = time.time()
                if now - last_print >= PROGRESS_EVERY_SECS:
                    elapsed = now - t0
                    rate = rows_read / elapsed if elapsed else 0
                    print(f"  …read={rows_read:,}  filtered_out={rows_filtered_out:,}  "
                          f"skipped_no_id={rows_skipped_no_id:,}  upserted={rows_upserted:,}  "
                          f"dupes_collapsed={rows_duplicates_collapsed:,}  "
                          f"{elapsed:.0f}s ({rate:.0f} rows/s)")
                    last_print = now

        if batch:
            n_upserted, n_collapsed = _flush(pg, batch)
            rows_upserted += n_upserted
            rows_duplicates_collapsed += n_collapsed
            conn.commit()

    elapsed = time.time() - t0
    pg.execute("SELECT COUNT(*) FROM parcels_regrid WHERE source_county = %s", (source_county,))
    (count_in_db,) = pg.fetchone()
    pg.close()

    print(f"\n  Rows read:          {rows_read:,}")
    print(f"  Filtered out (usecode): {rows_filtered_out:,}")
    print(f"  Skipped (no parcel_id): {rows_skipped_no_id:,}")
    print(f"  Duplicates collapsed (intra-batch, same parcel_id): {rows_duplicates_collapsed:,}")
    print(f"  Upserted:           {rows_upserted:,}")
    print(f"  DB count now ({source_county}): {count_in_db:,}")
    print(f"  Elapsed:            {elapsed:.1f}s  ({rows_read/elapsed:.0f} rows/s)" if elapsed else "")
    if errors:
        print(f"  First {min(len(errors),5)} of {len(errors)} skip reasons:")
        for e in errors[:5]:
            print(f"    {e}")

    expected = EXPECTED_KEPT.get(filename)
    kept_by_filter = rows_read - rows_filtered_out
    if expected is not None and kept_by_filter != expected:
        print(f"  ⚠️  DIVERGENCE: kept-by-filter this run = {kept_by_filter:,}, "
              f"expected (prior audit) = {expected:,}  (diff = {kept_by_filter - expected:+,})")

    return {
        "filename": filename, "source_county": source_county,
        "rows_read": rows_read, "rows_filtered_out": rows_filtered_out,
        "rows_skipped_no_id": rows_skipped_no_id, "rows_upserted": rows_upserted,
        "rows_duplicates_collapsed": rows_duplicates_collapsed,
        "count_in_db": count_in_db, "elapsed": elapsed,
    }


def main():
    db_url = _get_db_url()

    print("=" * 70)
    print(f"Regrid six-county filtered ingest — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Data dir: {DATA_DIR}")
    print(f"Batch size: {BATCH_SIZE}")
    print("=" * 70)

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    results = []
    running_upserted = 0
    try:
        for filename, source_county in FILES:
            r = ingest_one_file(conn, filename, source_county)
            results.append(r)
            running_upserted += r["rows_upserted"]
            print(f"  Running grand total upserted so far: {running_upserted:,}")
    finally:
        conn.close()

    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"{'source_county':16s} {'read':>10s} {'filtered':>10s} {'no_id':>8s} "
          f"{'dupes':>8s} {'upserted':>10s} {'expected':>10s} {'match':>6s}")
    grand_read = grand_filtered = grand_no_id = grand_dupes = grand_upserted = 0
    for r in results:
        expected = EXPECTED_KEPT.get(r["filename"], 0)
        kept_by_filter = r["rows_read"] - r["rows_filtered_out"]
        match = "OK" if kept_by_filter == expected else "DIVERGE"
        print(f"{r['source_county']:16s} {r['rows_read']:>10,} {r['rows_filtered_out']:>10,} "
              f"{r['rows_skipped_no_id']:>8,} {r['rows_duplicates_collapsed']:>8,} "
              f"{r['rows_upserted']:>10,} {expected:>10,} {match:>6s}")
        grand_read += r["rows_read"]
        grand_filtered += r["rows_filtered_out"]
        grand_no_id += r["rows_skipped_no_id"]
        grand_dupes += r["rows_duplicates_collapsed"]
        grand_upserted += r["rows_upserted"]

    print("-" * 88)
    print(f"{'TOTAL':16s} {grand_read:>10,} {grand_filtered:>10,} {grand_no_id:>8,} "
          f"{grand_dupes:>8,} {grand_upserted:>10,}")
    print(f"\nGrand total rows read across all 7 files:  {grand_read:,}")
    print(f"Grand total duplicate parcel_ids collapsed (intra-batch, lower bound): {grand_dupes:,}")
    print(f"Grand total rows upserted into parcels_regrid: {grand_upserted:,}")
    print(f"  (of which Macomb, unfiltered/tagged: "
          f"{next((r['rows_upserted'] for r in results if r['source_county']=='macomb'), 0):,})")
    print(f"Expected total (prior filter-only audit): {sum(EXPECTED_KEPT.values()):,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
