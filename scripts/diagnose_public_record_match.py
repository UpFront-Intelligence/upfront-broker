#!/usr/bin/env python3
"""Read-only diagnosis: why does the Public Record tab's parcels_regrid
match miss for Oakland properties? No writes, no schema changes.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/diagnose_public_record_match.py

Picks properties that share a zip with the ingested Oakland parcels_regrid
rows (a fair test — properties outside Oakland's zip footprint would never
match regardless of any bug), then for each one:
  1. Shows the property's stored address/city/zip/parcel_id and what
     normalize_address() produces for it.
  2. Runs the exact same query the /finder/public-record/{id} endpoint
     runs (source_county='oakland', zip match, then normalize_address()
     compare) and shows every candidate row plus whether it matched.
  3. If no exact match, also runs a loose ILIKE search on the house number
     to show near-misses -- this is what tells us abbreviation/format
     mismatch (address exists, doesn't normalize-match) vs genuinely
     absent (nothing found at all).
"""
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

import psycopg2
import psycopg2.extras

from services.naming import normalize_address

N_PROPERTIES = 5


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
    print("STEP 0 — sanity: parcels_regrid Oakland row count + zip footprint")
    print("=" * 78)
    pg.execute("SELECT COUNT(*) AS n FROM parcels_regrid WHERE source_county = 'oakland'")
    print(f"  parcels_regrid rows with source_county='oakland': {pg.fetchone()['n']:,}")
    pg.execute("SELECT COUNT(DISTINCT zip) AS n FROM parcels_regrid WHERE source_county = 'oakland'")
    print(f"  distinct zips in that set: {pg.fetchone()['n']:,}")
    pg.execute("""SELECT zip, COUNT(*) AS n FROM parcels_regrid
                  WHERE source_county = 'oakland' GROUP BY zip ORDER BY n DESC LIMIT 5""")
    print("  top 5 zips by row count:")
    for r in pg.fetchall():
        print(f"    {r['zip']!r}  ({r['n']:,} rows)")

    print("\n" + "=" * 78)
    print(f"STEP 1-3 — {N_PROPERTIES} real properties sharing a zip with Oakland parcels_regrid")
    print("=" * 78)

    pg.execute("""
        SELECT p.id, p.name, p.address, p.city, p.zip, p.county, p.parcel_id
        FROM properties p
        WHERE p.zip IN (SELECT DISTINCT zip FROM parcels_regrid WHERE source_county = 'oakland')
        ORDER BY p.id DESC
        LIMIT %s
    """, (N_PROPERTIES,))
    props = pg.fetchall()

    if not props:
        print("  No properties found sharing a zip with Oakland parcels_regrid rows at all.")
        print("  That itself is diagnostic -- either no properties have a zip that overlaps")
        print("  Oakland's ingested footprint, or property.zip is mostly NULL/blank.")
        conn.close()
        return

    for p in props:
        print(f"\n--- Property id={p['id']}  {p['name']!r} ---")
        print(f"  stored address: {p['address']!r}")
        print(f"  stored city:    {p['city']!r}")
        print(f"  stored zip:     {p['zip']!r}   (repr to catch hidden whitespace/format)")
        print(f"  stored county:  {p['county']!r}")
        print(f"  stored parcel_id: {p['parcel_id']!r}")

        norm_prop_addr = normalize_address(p['address'] or '')
        print(f"  normalize_address(property.address) = {norm_prop_addr!r}")

        # Exact same query shape as the live endpoint: source_county filter added here
        # for diagnostic clarity (the endpoint itself does NOT filter by source_county --
        # separate bug, doesn't explain a miss, see report).
        pg.execute("""
            SELECT parcel_id, owner_raw, address, city, zip, county, source_county
            FROM parcels_regrid
            WHERE source_county = 'oakland' AND zip = %s
        """, (p['zip'],))
        candidates = pg.fetchall()
        print(f"  parcels_regrid candidates (source_county='oakland', zip={p['zip']!r}): {len(candidates)}")

        # Check EVERY candidate for a match -- exactly what the live endpoint
        # does (db.query(...).all() then a plain for-loop, no slice). A prior
        # version of this script capped this loop at candidates[:20] for
        # print brevity, which also capped match DETECTION and produced a
        # false "no match" for large candidate sets (Postgres returns rows
        # in no guaranteed order without ORDER BY, so a true match can be
        # anywhere in the list). Printing is capped below; matching is not.
        exact_match = None
        for c in candidates:
            norm_cand_addr = normalize_address(c['address'] or '')
            if norm_cand_addr == norm_prop_addr:
                exact_match = c
                break

        for i, c in enumerate(candidates[:15]):
            norm_cand_addr = normalize_address(c['address'] or '')
            marker = "  <== EXACT MATCH" if (exact_match is not None and c['parcel_id'] == exact_match['parcel_id']) else ""
            print(f"    regrid address={c['address']!r:45s} normalized={norm_cand_addr!r:45s}"
                  f" owner={c['owner_raw']!r}{marker}")
        if len(candidates) > 15:
            print(f"    ...and {len(candidates)-15} more candidates not shown (all were still checked for a match)")

        if exact_match:
            already_shown = any(c['parcel_id'] == exact_match['parcel_id'] for c in candidates[:15])
            if not already_shown:
                print(f"    (match is further down the list, not in the 15 printed above:"
                      f" address={exact_match['address']!r})")
            print(f"  RESULT: WOULD MATCH via address -> owner={exact_match['owner_raw']!r}")
            continue

        print("  RESULT: NO exact normalize_address() match in the full zip-scoped candidate set"
              f" (all {len(candidates)} checked).")

        # Loose fallback: search by house number, scoped to the SAME zip and
        # ordered deterministically, to distinguish "address format differs"
        # from "genuinely not in the set". Zip-scoped (unlike the prior
        # version, which searched the whole county) so a true match can't
        # hide behind unrelated same-house-number addresses elsewhere in
        # Oakland.
        house_number = (p['address'] or '').strip().split(' ')[0]
        if house_number:
            pg.execute("""
                SELECT parcel_id, owner_raw, address, zip, source_county
                FROM parcels_regrid
                WHERE source_county = 'oakland' AND zip = %s AND address ILIKE %s
                ORDER BY address
                LIMIT 15
            """, (p['zip'], f"{house_number}%"))
            near = pg.fetchall()
            if near:
                print(f"  Near-misses by house number ILIKE '{house_number}%' (same zip {p['zip']!r}):")
                for n in near:
                    print(f"    address={n['address']!r}  zip={n['zip']!r}  owner={n['owner_raw']!r}")
            else:
                print(f"  No rows at all with address starting '{house_number}' in zip {p['zip']!r}"
                      f" -- likely genuinely not ingested (usecode-filtered out, or not in Regrid's"
                      f" Oakland file under this house number/street spelling).")

    conn.close()
    print("\n" + "=" * 78)
    print("Done. No writes were made.")
    print("=" * 78)


if __name__ == "__main__":
    main()
