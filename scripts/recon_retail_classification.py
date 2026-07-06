#!/usr/bin/env python3
"""Read-only recon: can we detect "Retail" as a distinct parcels_regrid
property_type, and with what signal? No writes, no schema changes.

Context: parcel_classcode_to_property_type() (backend/services/
property_category.py) maps exactly 8 standard-Michigan 3-digit codes to
Office/Industrial/Multifamily/Land. There is no Retail output. 201/202/203
("Commercial"/"Commercial Condo"/"Commercial Other") all collapse into
"Office" today — if MI's own classcode is too coarse to separate a strip
mall from a law office, some secondary signal is needed. This script checks,
empirically, which signal (if any) actually exists and is populated.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/recon_retail_classification.py

Checks, in order:
  0. Which counties are actually present right now (Macomb was deliberately
     never ingested — confirm that's still true rather than assume it).
  1. Every distinct usecode value across all counties, with row counts and
     one sample usedesc per code — the full universe, not just the 8 the
     classifier already knows about.
  2. Within usecode 201/202/203 specifically (today's "Office" bucket):
     distinct `land_use` values (this column is populated from the raw
     CSV's `lbcs_activity` field per scripts/ingest_regrid_metro.py — a
     numeric LBCS Activity code, e.g. "2000" for the Sales/Service/Business/
     Trade major group, potentially subdividing further into retail-specific
     codes like "21xx" at a finer grain — untested here, this is what we're
     checking) and distinct `zoning` values, to see if either disambiguates
     retail from other commercial uses within the same MI usecode.
  3. Raw_data key sample for a handful of 201/202/203 rows, specifically
     hunting for zoning_description / zoning_type / zoning_subtype /
     lbcs_activity_desc keys. These are NOT confirmed real Regrid columns
     in this codebase today — zoning_description/zoning_type/zoning_subtype
     only appear in scripts/generate_regrid_fixture.py's SYNTHETIC test
     fixture, never in the real ingest mapping (only a bare `zoning` column
     was confirmed and promoted to a dedicated column). lbcs_activity_desc
     is mentioned in ingest_regrid_metro.py as "the human label, not
     requested as the source" for land_use — meaning IF it exists as a real
     column, it should still be sitting in raw_data (the ingest's catch-all
     dumps every non-critical, non-empty column). This step checks whether
     any of these actually show up, rather than assuming the premise.
  4. Sanity check that the standard/Detroit SFR-drop codes are actually
     near-zero (confirms the ingest filter worked as documented).
  5. Real classification breakdown for parcel_usedesc_to_property_type_detroit()
     (backend/services/property_category.py) against every wayne_detroit
     row — imports and runs the actual function (not a re-implementation),
     so these counts are exactly what finder.py's display path produces.
     Also prints the top unmatched usedesc values as candidates for
     expanding the keyword list.
"""
import json
import os
import sys
from collections import Counter


def _get_db_url():
    url = (os.environ.get("PROD_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        sys.exit("ERROR: set PROD_DATABASE_URL (or DATABASE_URL) as an env var for this invocation.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


# The 8 codes parcel_classcode_to_property_type() already knows, for
# side-by-side comparison against what's actually in the table.
KNOWN_CODES = {
    "201": "Office", "202": "Office", "203": "Office", "207": "Land",
    "301": "Industrial", "302": "Industrial", "403": "Multifamily", "407": "Land",
}

# Candidate zoning-detail keys to hunt for in raw_data — see module
# docstring step 3 for why these are unconfirmed, not assumed real.
CANDIDATE_ZONING_KEYS = [
    "zoning_description", "zoning_type", "zoning_subtype", "zoning_code_link",
    "lbcs_activity_desc",
]


def main():
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = True
    pg = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=" * 78)
    print("0. Counties actually present in parcels_regrid right now")
    print("=" * 78)
    pg.execute("SELECT source_county, COUNT(*) AS n FROM parcels_regrid GROUP BY source_county ORDER BY n DESC")
    for r in pg.fetchall():
        print(f"  {r['source_county']:20s} {r['n']:>8,}")

    print("\n" + "=" * 78)
    print("1. Every distinct usecode across ALL counties — count + one sample usedesc")
    print("   ('*' = already in parcel_classcode_to_property_type(); its current output shown)")
    print("=" * 78)
    pg.execute("""
        SELECT usecode, COUNT(*) AS n,
               (ARRAY_AGG(usedesc) FILTER (WHERE usedesc IS NOT NULL))[1] AS sample_usedesc
        FROM parcels_regrid
        GROUP BY usecode
        ORDER BY n DESC
    """)
    rows = pg.fetchall()
    total = sum(r["n"] for r in rows)
    for r in rows:
        code = (r["usecode"] or "").strip()
        known = KNOWN_CODES.get(code)
        marker = f"*  -> {known}" if known else "  "
        print(f"  {code or '(null)':10s} {r['n']:>8,}  ({100*r['n']/total:5.1f}%)  {marker:16s} usedesc={r['sample_usedesc']!r}")

    print("\n" + "=" * 78)
    print("2a. Within usecode 201/202/203 (today's 'Office' bucket) — distinct land_use values")
    print("    (land_use = raw CSV 'lbcs_activity', a numeric LBCS Activity code)")
    print("=" * 78)
    pg.execute("""
        SELECT usecode, land_use, COUNT(*) AS n
        FROM parcels_regrid
        WHERE usecode IN ('201', '202', '203')
        GROUP BY usecode, land_use
        ORDER BY usecode, n DESC
    """)
    for r in pg.fetchall():
        print(f"  usecode={r['usecode']:5s} land_use={str(r['land_use']):10s} n={r['n']:>7,}")

    print("\n" + "=" * 78)
    print("2b. Within usecode 201/202/203 — distinct zoning values (top 30 by count)")
    print("=" * 78)
    pg.execute("""
        SELECT zoning, COUNT(*) AS n
        FROM parcels_regrid
        WHERE usecode IN ('201', '202', '203') AND zoning IS NOT NULL
        GROUP BY zoning
        ORDER BY n DESC
        LIMIT 30
    """)
    for r in pg.fetchall():
        print(f"  zoning={r['zoning']!r:30s} n={r['n']:>7,}")

    print("\n" + "=" * 78)
    print("3. Hunting raw_data for zoning/LBCS detail keys not yet promoted to a")
    print("   dedicated column — sampling 200 rows with usecode IN (201,202,203)")
    print("=" * 78)
    pg.execute("""
        SELECT raw_data FROM parcels_regrid
        WHERE usecode IN ('201', '202', '203') AND raw_data IS NOT NULL
        LIMIT 200
    """)
    sample_rows = pg.fetchall()
    key_counter = Counter()
    value_samples = {}
    for row in sample_rows:
        rd = row["raw_data"] or {}
        if isinstance(rd, str):
            try:
                rd = json.loads(rd)
            except Exception:
                rd = {}
        for k in CANDIDATE_ZONING_KEYS:
            if rd.get(k) not in (None, ""):
                key_counter[k] += 1
                value_samples.setdefault(k, rd[k])
    n = len(sample_rows)
    print(f"  Sampled {n} rows with usecode in (201,202,203):")
    for k in CANDIDATE_ZONING_KEYS:
        c = key_counter.get(k, 0)
        sample_val = value_samples.get(k, "n/a")
        pct = f"{100*c/n:.1f}%" if n else "n/a"
        print(f"    {k:22s} {c:>4}/{n}  ({pct})   sample value: {sample_val!r}")
    if not key_counter:
        print("  -> NONE of the candidate zoning-detail keys appear in this sample.")
        print("     zoning_description/zoning_type/zoning_subtype are apparently NOT real")
        print("     Regrid columns for this schema (they only exist in the synthetic test")
        print("     fixture, scripts/generate_regrid_fixture.py) — do not build logic that")
        print("     assumes they exist. Fall back to `zoning` (2b above) and/or `land_use`")
        print("     (2a above) as the only real secondary signals.")

    print("\n" + "=" * 78)
    print("4. Sanity: are the 401/402/407 (standard) and 41110/00003 (Detroit) drop")
    print("   codes actually near-zero, confirming the ingest filter worked?")
    print("=" * 78)
    pg.execute("""
        SELECT usecode, COUNT(*) AS n FROM parcels_regrid
        WHERE usecode IN ('401', '402', '407', '41110', '00003')
        GROUP BY usecode
    """)
    drop_rows = pg.fetchall()
    if not drop_rows:
        print("  None present — filter appears to have worked as documented.")
    else:
        for r in drop_rows:
            print(f"  usecode={r['usecode']:8s} n={r['n']:>7,}  <-- should have been dropped at ingest, investigate")

    print("\n" + "=" * 78)
    print("5. Detroit classification breakdown — real parcel_usedesc_to_property_type_detroit()")
    print("   output across every wayne_detroit row (imports the actual function, not a copy)")
    print("=" * 78)
    SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
    BACKEND_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "backend")
    sys.path.insert(0, BACKEND_DIR)
    from services.property_category import parcel_usedesc_to_property_type_detroit

    pg.execute("SELECT usedesc FROM parcels_regrid WHERE source_county = 'wayne_detroit'")
    detroit_rows = pg.fetchall()
    output_counter = Counter()
    unmatched_usedesc_counter = Counter()
    for r in detroit_rows:
        usedesc = r["usedesc"]
        result = parcel_usedesc_to_property_type_detroit(usedesc)
        output_counter[result] += 1
        if result is None:
            unmatched_usedesc_counter[usedesc] += 1

    total_detroit = len(detroit_rows)
    print(f"  Total wayne_detroit rows: {total_detroit:,}")
    for category in ["Retail", "Office", "Industrial", "Multifamily", "Land", None]:
        c = output_counter.get(category, 0)
        pct = f"{100*c/total_detroit:.1f}%" if total_detroit else "n/a"
        label = category or "None (unmatched)"
        print(f"    {label:20s} {c:>7,}  ({pct})")

    print("\n  Top 20 unmatched usedesc values (candidates to add a keyword for):")
    for usedesc, c in unmatched_usedesc_counter.most_common(20):
        print(f"    {c:>6,}  {usedesc!r}")

    conn.close()
    print("\nDone. No writes were made.")


if __name__ == "__main__":
    main()
