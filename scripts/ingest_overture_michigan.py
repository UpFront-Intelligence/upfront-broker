#!/usr/bin/env python3
"""Ingest Overture Maps Places data for Michigan into the national_locations table.

Runs against the real DATABASE_URL (same convention as other scripts/ here).
Uses DuckDB's httpfs extension to query Overture's Parquet files directly
from public S3 — no global download, no API key.

Usage (from repo root):
    DATABASE_URL="postgresql://..." python3 scripts/ingest_overture_michigan.py

Options (env vars):
    OVERTURE_RELEASE   — override auto-detection, e.g. "2026-06-17.0"
                         If not set, the script auto-detects the latest release
                         by querying the Overture STAC catalog. Set this explicitly
                         if you need a specific release or if auto-detection fails
                         in a restricted network environment.
    BATCH_SIZE         — rows per database commit (default 1000)
    DRY_RUN            — set to "1" to parse and print stats but not write to DB

Dependencies (not in main requirements.txt — dev/ops only):
    pip install duckdb                    (query Parquet from S3)
    (psycopg2-binary already in requirements.txt)

==========================================================================
CATEGORY SCOPE — what this script ingests and why
==========================================================================
Overture Places has 11 top-level category prefixes. Ingestion scope below:

  INCLUDED:
    eat_and_drink      — restaurants, bars, cafes, coffee shops, food trucks
    retail             — all retail (pharmacies are retail.pharmacy, auto parts
                         are retail.auto_parts_and_supply_store, etc.)
    automotive         — gas stations, car washes, dealerships, auto services
    beauty_and_spa     — salons, nail salons, spas, barbers
    financial_service  — banks, credit unions, insurance offices, ATMs
                         NOTE: task spec said "professional_services" — that
                         top-level does not exist in Overture's actual taxonomy.
                         The closest matching category is financial_service.
                         Verify against the first real ingest output.

  EXCLUDED:
    accommodation      — hotels, motels (not retail/restaurant use case)
    arts_and_entertainment — museums, theaters, galleries
    attractions_and_activities — parks, tours, recreation
    active_life        — gyms, fitness centers, sports facilities
    education          — schools, universities, tutoring
    private_establishments_and_corporates — corporate HQs, office buildings

NOTE: the task spec also listed "health_and_medical" as a top-level category
(for pharmacies). This does NOT exist as a top-level in Overture 2026 —
pharmacies are under retail.pharmacy. If future Overture releases add a
health_and_medical top-level, add it to INCLUDE_TOP_LEVELS below.

==========================================================================
SCHEMA ASSUMPTIONS — verify against first real ingest
==========================================================================
Confirmed against Overture 2026-06-17.0 documentation:
  names.primary            — primary place name
  categories.primary       — full dot-path, e.g. "eat_and_drink.restaurant.pizza"
  brand.names.primary      — canonical brand name (e.g. "Starbucks")
                             NOTE: brand.names is a nested struct; confirmed from
                             JSON shape {"names": {"primary": "Starbucks"}, "wikidata": null}
  brand.wikidata           — Wikidata entity ID, may be null
  confidence               — float 0-1 existence confidence
  addresses                — 1-indexed array in SQL; addresses[1].{freeform,locality,
                             region,postcode,country}
  bbox.xmin/ymin/xmax/ymax — bounding box coordinates for S3 predicate pushdown
  geometry                 — WKB point; ST_X(geometry)=lng, ST_Y(geometry)=lat
  websites, phones         — may be stored as JSON strings or native; handled both ways
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import psycopg2
import psycopg2.extras

# ── Scope ──────────────────────────────────────────────────────────────────────
# Filtering uses taxonomy.hierarchy[1] (the top-level Overture taxonomy node,
# 1-based in DuckDB SQL), NOT categories.primary (which is the leaf node and
# has no dot-path structure — confirmed from live data 2026-06-17.0).
#
# CONFIRMED Overture 2026 top-level taxonomy names (verified against live data):
#   food_and_drink        — restaurants, cafes, bars, coffee shops, fast food
#   shopping              — retail stores, pharmacies (specialty_store > pharmacy),
#                           grocery, clothing, auto parts, discount stores
#   travel_and_transportation — gas stations, repair shops, car washes, parking
#   lifestyle_services    — beauty salons, hair salons, nail salons, spas, barbers
#   services_and_business — banks, ATMs, insurance, financial services, offices;
#                           sub-filtered by SERVICES_BUSINESS_LEAVES below because
#                           this top-level is enormous (~70K Wayne Co. rows total)
#                           and includes many non-CRE-relevant categories.
#
# NOT included (too noisy or out of scope for CRE broker use):
#   health_care           — doctors, dentists, hospitals (pharmacies already in shopping)
#   cultural_and_historic — museums, historic sites
#   sports_and_recreation — gyms, parks, stadiums
#   community_and_government — churches, community centers, government offices
#   education             — schools, universities
#   arts_and_entertainment — theaters, galleries
#   lodging               — hotels, motels
#   geographic_entities   — geographic areas, not places

INCLUDE_TOP_LEVELS = {
    "food_and_drink",
    "shopping",
    "travel_and_transportation",
    "lifestyle_services",
    "services_and_business",   # sub-filtered below
}

# services_and_business sub-filter — only leaf categories (categories.primary)
# with clear CRE-tenant relevance (physical storefront or office presence).
# Confirmed against live Wayne County data 2026-06-25. Excluded from this list:
#   real_estate_agent/real_estate (4,920 + 1,387) — individual agents, not offices
#   lawyer/legal_services — solo attorneys, not law firm storefronts
#   professional_services — catch-all with too much noise (photographers, etc.)
#   accountant — individual-heavy; tax_services already captures chains (H&R Block)
#   courier_and_delivery_services — fleet/gig addresses; UPS Store/FedEx covered by shipping_center
#   coworking_space — mislabeled in Overture data (law firms tagged as coworking)
#   marketing/advertising/software/IT agencies — non-retail office services
SERVICES_BUSINESS_LEAVES = {
    # Banking & ATMs
    "atms", "bank_credit_union", "banks", "credit_union",
    # Finance — physical office/storefront presence
    "money_transfer_services",   # Western Union, MoneyGram
    "financial_service",         # generic catch-all: Edward Jones, advisors, etc.
    "financial_advising",        # wealth management offices
    "insurance_agency",          # Allstate, State Farm
    "tax_services",              # H&R Block, Liberty Tax, Jackson Hewitt
    "mortgage_broker",
    "mortgage_lender",
    "check_cashing_payday_loans",
    "installment_loans",         # OneMain Financial, Advance America
    # Shipping & Storage
    "post_office",
    "shipping_center",           # UPS Store, FedEx Office
    "package_locker",
    "self_storage_facility",
    "storage_facility",
    # Personal services
    "laundromat",
    "dry_cleaning",
    # Vehicle rentals
    "car_rental_agency",
    "rental_kiosks",
    # Office-tenant professional services
    "employment_agencies",       # staffing firms: OfficeTeam, JVS
    "commercial_real_estate",    # CRE firms and offices (not individual agents)
    "property_management",
}

# Michigan bounding box (intentionally slightly larger than actual MI extent;
# we also filter to state='MI' from the addresses field for precision).
MICHIGAN_BBOX = {
    "xmin": -90.5,
    "xmax": -82.0,
    "ymin": 41.5,
    "ymax": 48.5,
}

BATCH_SIZE             = int(os.getenv("BATCH_SIZE", "1000"))
DRY_RUN                = os.getenv("DRY_RUN", "") == "1"
TRUNCATE_BEFORE_INGEST = os.getenv("TRUNCATE_BEFORE_INGEST", "") == "1"

# ── Helpers ─────────────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    from services.naming import normalize_name as _nn
    return _nn(name)


def normalize_address(addr: str) -> str:
    from services.naming import normalize_address as _na
    return _na(addr)


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        env_path = os.path.join(REPO_ROOT, "backend", ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def detect_latest_release() -> str:
    """Try to auto-detect the latest Overture release.

    Primary: Overture STAC catalog (standard JSON API, no auth).
    Fallback: S3 XML bucket listing (public bucket, no auth).
    If both fail, raises with instructions to set OVERTURE_RELEASE manually.
    """
    import requests as req

    # Primary: STAC catalog
    try:
        r = req.get("https://stac.overturemaps.org/catalog.json", timeout=10)
        r.raise_for_status()
        catalog = r.json()
        versions = []
        for link in catalog.get("links", []):
            href = link.get("href", "")
            # STAC child hrefs contain the release id, e.g.
            # "https://stac.overturemaps.org/collections/2026-06-17.0/..."
            m = re.search(r'/(\d{4}-\d{2}-\d{2}\.\d+)', href)
            if m:
                versions.append(m.group(1))
        if versions:
            latest = sorted(set(versions))[-1]
            print(f"  Auto-detected latest Overture release via STAC: {latest}")
            return latest
    except Exception as e:
        print(f"  STAC catalog fetch failed ({e}), trying S3 listing…")

    # Fallback: S3 XML listing
    try:
        r = req.get(
            "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/",
            params={"prefix": "release/", "delimiter": "/", "list-type": "2"},
            timeout=10,
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        versions = []
        for p in root.findall(".//s3:CommonPrefixes/s3:Prefix", ns):
            parts = (p.text or "").strip("/").split("/")
            if len(parts) == 2 and re.match(r'\d{4}-\d{2}-\d{2}\.\d+', parts[1]):
                versions.append(parts[1])
        if versions:
            latest = sorted(versions)[-1]
            print(f"  Auto-detected latest Overture release via S3 listing: {latest}")
            return latest
    except Exception as e:
        print(f"  S3 listing also failed ({e}).")

    raise RuntimeError(
        "Could not auto-detect the latest Overture release. "
        "Set OVERTURE_RELEASE=<version> (e.g. 2026-06-17.0) and retry."
    )


def _as_json(val):
    """Normalize websites/phones — Overture may return them as a JSON string,
    a Python list, or None. Always store as a Python list (or None)."""
    if val is None:
        return None
    if isinstance(val, list):
        return val if val else None
    if isinstance(val, str):
        val = val.strip()
        if not val or val == "[]":
            return None
        try:
            parsed = json.loads(val)
            return parsed if parsed else None
        except json.JSONDecodeError:
            return [val]
    return None


def _clamp_confidence(val):
    if val is None:
        return None
    try:
        f = float(val)
        # confidence is 0-1 per Overture spec; Numeric(4,3) max is 9.999
        return min(max(f, 0.0), 1.0)
    except (TypeError, ValueError):
        return None


UPSERT_SQL = """
INSERT INTO national_locations
  (overture_id, brand_primary, brand_normalized, name_primary,
   category_primary, category_top, address, address_normalized,
   city, state, zip, lat, lng, websites, phones, confidence,
   raw_data, release_version)
VALUES %s
ON CONFLICT (overture_id) DO UPDATE SET
  brand_primary      = EXCLUDED.brand_primary,
  brand_normalized   = EXCLUDED.brand_normalized,
  name_primary       = EXCLUDED.name_primary,
  category_primary   = EXCLUDED.category_primary,
  category_top       = EXCLUDED.category_top,
  address            = EXCLUDED.address,
  address_normalized = EXCLUDED.address_normalized,
  city               = EXCLUDED.city,
  state              = EXCLUDED.state,
  zip                = EXCLUDED.zip,
  lat                = EXCLUDED.lat,
  lng                = EXCLUDED.lng,
  websites           = EXCLUDED.websites,
  phones             = EXCLUDED.phones,
  confidence         = EXCLUDED.confidence,
  raw_data           = EXCLUDED.raw_data,
  release_version    = EXCLUDED.release_version
"""


# ── DuckDB query ───────────────────────────────────────────────────────────────

DUCKDB_SETUP_SQL = """
INSTALL spatial;
INSTALL httpfs;
LOAD spatial;
LOAD httpfs;
SET s3_region = 'us-west-2';
"""

def _build_query(release: str) -> str:
    s3_path = (
        f"s3://overturemaps-us-west-2/release/{release}/"
        "theme=places/type=place/*"
    )
    # bbox predicate pushes down into Parquet row-group min/max statistics —
    # dramatically reduces S3 data scanned before addresses/taxonomy are decoded.
    # taxonomy.hierarchy[1] is the actual top-level Overture category (1-based in
    # DuckDB SQL). categories.primary is the leaf node and has no dot-path
    # structure — the broken ILIKE 'eat_and_drink%' pattern has been removed.
    top_levels_sql = ", ".join(f"'{t}'" for t in sorted(INCLUDE_TOP_LEVELS - {"services_and_business"}))
    svc_leaves_sql = ", ".join(f"'{l}'" for l in sorted(SERVICES_BUSINESS_LEAVES))
    return f"""
SELECT
    id                                   AS overture_id,
    names.primary                        AS name_primary,
    TRY(brand.names.primary)             AS brand_primary,
    TRY(brand.wikidata)                  AS brand_wikidata,
    categories.primary                   AS category_primary,
    TRY(taxonomy.hierarchy[1])           AS category_top,
    TRY(addresses[1].freeform)           AS address,
    TRY(addresses[1].locality)           AS city,
    TRY(addresses[1].region)             AS state,
    TRY(addresses[1].postcode)           AS zip_code,
    TRY(addresses[1].country)            AS country,
    TRY(CAST(ST_Y(geometry) AS DOUBLE))  AS lat,
    TRY(CAST(ST_X(geometry) AS DOUBLE))  AS lng,
    websites,
    phones,
    confidence,
    TRY(operating_status)                AS operating_status,
    version
FROM read_parquet('{s3_path}', filename=true, hive_partitioning=1)
WHERE
    bbox.xmin >= {MICHIGAN_BBOX['xmin']}
    AND bbox.xmax <= {MICHIGAN_BBOX['xmax']}
    AND bbox.ymin >= {MICHIGAN_BBOX['ymin']}
    AND bbox.ymax <= {MICHIGAN_BBOX['ymax']}
    AND TRY(addresses[1].region) = 'MI'
    AND (
        TRY(taxonomy.hierarchy[1]) IN ({top_levels_sql})
        OR (
            TRY(taxonomy.hierarchy[1]) = 'services_and_business'
            AND categories.primary IN ({svc_leaves_sql})
        )
    )
"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    db_url = get_db_url()
    if not db_url:
        sys.exit(
            "ERROR: DATABASE_URL not set.\n"
            "Run: DATABASE_URL=postgresql://... python3 scripts/ingest_overture_michigan.py"
        )

    release = os.getenv("OVERTURE_RELEASE", "").strip()

    print("=" * 70)
    print("Overture Maps — Michigan Places ingestion")
    print(f"Started:   {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Batch size: {BATCH_SIZE}  |  Dry-run: {DRY_RUN}")
    print("=" * 70)

    if not release:
        print("\nAuto-detecting latest Overture release…")
        release = detect_latest_release()
    else:
        print(f"Using explicitly-set release: {release}")

    print(f"\nRelease:   {release}")
    print(f"Scope:     Michigan (bbox + addresses[1].region = 'MI')")
    print(f"Top-levels: {', '.join(sorted(INCLUDE_TOP_LEVELS))}")
    print(f"Truncate:   {'YES — will TRUNCATE national_locations first' if TRUNCATE_BEFORE_INGEST else 'no'}\n")

    try:
        import duckdb
    except ImportError:
        sys.exit(
            "duckdb is not installed. Run:\n"
            "  pip install -r backend/requirements-dev.txt"
        )

    query = _build_query(release)

    # Open Postgres connection early so TRUNCATE (if requested) runs before
    # DuckDB starts streaming — avoids ingesting into a partially-populated table.
    conn = None if DRY_RUN else psycopg2.connect(db_url)
    if conn:
        conn.autocommit = False
        pg = conn.cursor()
        if TRUNCATE_BEFORE_INGEST:
            print("TRUNCATING national_locations (TRUNCATE_BEFORE_INGEST=1)…")
            pg.execute("TRUNCATE TABLE national_locations RESTART IDENTITY CASCADE")
            conn.commit()
            print("Truncated.\n")

    print("Connecting to DuckDB + S3…")
    duck = duckdb.connect()
    for stmt in DUCKDB_SETUP_SQL.strip().split("\n"):
        stmt = stmt.strip()
        if stmt:
            try:
                duck.execute(stmt)
            except Exception:
                pass  # INSTALL is a no-op if already installed; LOAD errors are real

    print(f"Running query against s3://overturemaps-us-west-2/release/{release}/…")
    print("(First run may be slow while DuckDB fetches Parquet metadata from S3)\n")

    cur = duck.execute(query)

    if DRY_RUN:
        print("DRY RUN — reading rows but not writing to database.\n")

    rows_seen = rows_ingested = rows_updated = rows_skipped = 0
    brand_counter    = Counter()
    category_counter = Counter()
    batch            = []

    def flush(batch, final=False):
        nonlocal rows_ingested, rows_updated
        if not batch or DRY_RUN:
            return
        # Distinguish new vs updated via RETURNING with xmax trick
        # (xmax=0 means INSERT; xmax!=0 means UPDATE via MVCC)
        upsert_with_xmax = UPSERT_SQL.rstrip() + "\nRETURNING (xmax = 0) AS was_insert"
        psycopg2.extras.execute_values(pg, upsert_with_xmax, batch, page_size=len(batch))
        results = pg.fetchall()
        rows_ingested += sum(1 for r in results if r[0])
        rows_updated  += sum(1 for r in results if not r[0])
        conn.commit()
        batch.clear()

    while True:
        rows = cur.fetchmany(BATCH_SIZE)
        if not rows:
            break

        for row in rows:
            rows_seen += 1
            (
                overture_id, name_primary, brand_primary, brand_wikidata,
                category_primary, category_top,
                address, city, state, zip_code, country,
                lat, lng, websites_raw, phones_raw, confidence,
                operating_status, version,
            ) = row

            # Belt-and-suspenders: DuckDB already filtered these; Python catches
            # any null-evaluation edge cases.
            if (state or "").upper() != "MI":
                rows_skipped += 1
                continue
            if category_top is None:
                rows_skipped += 1
                continue

            brand_norm = normalize_name(brand_primary) if brand_primary else None
            websites   = _as_json(websites_raw)
            phones     = _as_json(phones_raw)
            conf       = _clamp_confidence(confidence)

            # raw_data: structured fields for future enrichment/agent use.
            # brand.names.primary is null on some known chains (Western Union,
            # some Allstate franchise locations) — source data quality in Overture,
            # not a bug. raw_data preserves whatever Overture sent for later use.
            raw_data = {
                "name_primary":     name_primary,
                "brand_primary":    brand_primary,
                "brand_wikidata":   brand_wikidata,
                "category_primary": category_primary,
                "category_top":     category_top,
                "address":          address,
                "city":             city,
                "state":            state,
                "zip":              zip_code,
                "country":          country,
                "operating_status": operating_status,
                "version":          version,
            }

            if lat is not None:
                try:
                    lat = round(float(lat), 6)
                except (TypeError, ValueError):
                    lat = None
            if lng is not None:
                try:
                    lng = round(float(lng), 6)
                except (TypeError, ValueError):
                    lng = None

            brand_counter[brand_primary or "(no brand)"] += 1
            category_counter[category_top] += 1

            if DRY_RUN:
                continue

            batch.append((
                overture_id,
                brand_primary,
                brand_norm,
                name_primary,
                category_primary,
                category_top,
                address,
                normalize_address(address) if address else None,   # address_normalized
                city,
                state,
                zip_code,
                lat,
                lng,
                json.dumps(websites)  if websites  else None,
                json.dumps(phones)    if phones    else None,
                conf,
                json.dumps(raw_data),
                release,
            ))

            if len(batch) >= BATCH_SIZE:
                flush(batch)
                print(f"  … {rows_seen:,} seen — {rows_ingested:,} new, {rows_updated:,} updated, {rows_skipped:,} skipped")

    flush(batch, final=True)

    if conn:
        conn.close()
    duck.close()

    print("\n" + "=" * 70)
    print(f"Overture Michigan ingestion complete — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Release:       {release}")
    print(f"  Rows seen:     {rows_seen:,}")
    print(f"  Rows ingested: {rows_ingested:,}  (new)")
    print(f"  Rows updated:  {rows_updated:,}  (existing, refreshed)")
    print(f"  Rows skipped:  {rows_skipped:,}  (non-MI or out-of-scope category)")
    print()
    print("Category breakdown:")
    for cat, count in sorted(category_counter.items(), key=lambda x: -x[1]):
        print(f"  {cat:40s} {count:>8,}")
    print()
    print("Top 20 brands by location count:")
    for brand, count in brand_counter.most_common(20):
        print(f"  {(brand or '—'):40s} {count:>8,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
