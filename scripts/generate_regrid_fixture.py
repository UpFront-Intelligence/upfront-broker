#!/usr/bin/env python3
"""Generates tests/fixtures/regrid_sample_wayne.csv — a synthetic 191-column,
20-row Regrid county export, built before any real Regrid CSV exists.

Column names: the 8 matching-critical ones (parcelnumb, owner, address, city,
state, zip, county, geometry) are confirmed against Regrid's public schema
docs (support.regrid.com/parcel-data/schema). Roughly 80 more are realistic
Regrid/county-assessor field names gathered the same way (ll_*, mail_*,
plss_*, lbcs_*, zoning_*, etc.) but NOT individually confirmed — Regrid's
own full schema spreadsheet 404'd when fetched for this build. The
remainder are padded with clearly-labeled `regrid_unconfirmed_field_NN`
placeholders purely to exercise "wide, mostly-empty CSV" ingestion — they
are NOT real Regrid column names. See CLAUDE.md's PARCELS_REGRID section.

The 20 rows are designed (and verified against backend/services/naming.py's
normalize_name + rapidfuzz.token_sort_ratio) to land in three score bands
against five seeded test accounts/properties that tests/test_regrid_reconciler.py
and scripts/test_regrid_reconciler.py create:
  5  rows  -> owner score 100        + address matches a seeded property -> auto_linked
  8  rows  -> owner score 65-94      (no seeded-property address match)  -> suggested
  7  rows  -> owner score 36-56      (well under the 65 floor)           -> no_match

Re-run this script any time the row design needs to change; don't hand-edit
the generated CSV.
"""
import csv
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "regrid_sample_wayne.csv")

# ── Seed accounts/properties this fixture is designed against ───────────────
# (tests/test_regrid_reconciler.py and scripts/test_regrid_reconciler.py both
# create accounts/properties with exactly these names/addresses before
# running ingest+reconcile against this CSV.)
SEED_ACCOUNTS = [
    "Woodward Capital Partners LLC",
    "Riverfront Logistics Partners LLC",
    "Greenfield Realty Advisors Trust",
    "Midtown Property Management Inc",
    "Cass Corridor Investments LP",
]

SEED_PROPERTIES = [
    "1001 Woodward Ave",
    "2700 Trumbull Ave",
    "440 Burroughs St",
    "4150 Woodward Ave",
    "100 Cass Ave",
]

# ── Realistic Regrid/assessor-style columns (see module docstring re: confidence) ──
_REALISTIC_COLUMNS = [
    "ll_uuid", "ll_stable_id", "ll_stack_uuid",
    "parcelnumb", "parcelnumb_no_formatting", "state_parcelnumb", "account_number", "tax_id",
    "alt_parcelnumb1", "alt_parcelnumb2", "alt_parcelnumb3",
    "owner", "owner2", "owner3", "owner4",
    "mailadd", "mail_address2", "mail_city", "mail_state2", "mail_zip", "mail_country",
    "address", "address2", "scity", "city", "county", "county_name", "state", "state2", "zip", "szip",
    "original_address",
    "geoid", "census_tract", "census_block", "census_blockgroup",
    "plss_township", "plss_section", "plss_range",
    "qoz", "qoz_tract", "fema_flood_zone",
    "lbcs_activity", "lbcs_activity_desc", "lbcs_function", "lbcs_function_desc",
    "zoning", "zoning_description", "zoning_type", "zoning_subtype", "zoning_code_link",
    "ll_gisacre", "ll_gissqft", "ll_bldg_count", "ll_bldg_footprint_sqft", "ll_address_count",
    "sourcedate", "recrdareano", "gisacre", "sqft",
    "legaldesc", "plat", "book", "page", "lot", "block", "sec", "twp", "rng", "subdivision",
    "struct", "structno", "yearbuilt", "numstories", "numunits", "structstyle",
    "parval", "landval", "improvval", "taxyear", "saledate", "saleprice", "taxamt", "owntype",
    "usps_vacancy", "usps_vacancy_date", "cdl_majority_category", "cdl_majority_percent",
    "geometry",
]

TARGET_COLUMN_COUNT = 191
_PAD_NEEDED = TARGET_COLUMN_COUNT - len(_REALISTIC_COLUMNS)
_PADDING_COLUMNS = [f"regrid_unconfirmed_field_{i:03d}" for i in range(1, _PAD_NEEDED + 1)]

FIELDNAMES = _REALISTIC_COLUMNS + _PADDING_COLUMNS
assert len(FIELDNAMES) == TARGET_COLUMN_COUNT, len(FIELDNAMES)


def _wkt(lng: float, lat: float) -> str:
    d = 0.0003
    return (f"POLYGON(({lng-d} {lat-d}, {lng+d} {lat-d}, "
            f"{lng+d} {lat+d}, {lng-d} {lat+d}, {lng-d} {lat-d}))")


def _row(parcel_id, owner, address, lng=-83.0458, lat=42.3486):
    return {
        "parcelnumb": parcel_id,
        "owner": owner,
        "address": address,
        "city": "Detroit",
        "state": "MI",
        "zip": "48201",
        "county": "Wayne",
        "geometry": _wkt(lng, lat),
    }


# ── AUTO-LINK rows: owner score 100 (verified), address exactly matches a
# seeded property after normalize_address (punctuation/case noise only). ──
AUTO_LINK_ROWS = [
    _row("82-001-001.000", "Woodward Capital Partners, LLC",      "1001 WOODWARD AVE.", -83.0458, 42.3486),
    _row("82-001-002.000", "Riverfront Logistics Partners LLC.",  "2700 trumbull ave",  -83.0658, 42.3386),
    _row("82-001-003.000", "Greenfield Realty Advisors Trust",    "440 Burroughs St",   -83.0658, 42.3686),
    _row("82-001-004.000", "Midtown Property Management, Inc",   "4150 woodward ave.", -83.0658, 42.3586),
    _row("82-001-005.000", "Cass Corridor Investments, LP",       "100 CASS AVE",       -83.0558, 42.3386),
]

# ── SUGGESTED rows: owner score 65-94 (verified), address deliberately not
# matching any seeded property (irrelevant either way for this branch). ──
SUGGESTED_ROWS = [
    _row("82-002-001.000", "Woodward Capital Holdings LLC",   "1500 Brush St",     -83.0408, 42.3406),
    _row("82-002-002.000", "Riverfront Logistics Group",      "200 River Pl",      -83.0408, 42.3306),
    _row("82-002-003.000", "Greenfield Advisors LLC",         "900 Larned St",     -83.0508, 42.3296),
    _row("82-002-004.000", "Midtown Realty Management LLC",   "3434 Russell St",  -83.0608, 42.3496),
    _row("82-002-005.000", "Cass Corridor Realty LLC",        "3100 Cass Ave",     -83.0608, 42.3396),
    _row("82-002-006.000", "Woodward Partners LLC",           "6500 Woodward Ave", -83.0608, 42.3306),
    _row("82-002-007.000", "Riverfront Partners LLC",         "1300 Atwater St",   -83.0358, 42.3296),
    _row("82-002-008.000", "Greenfield Realty Trust",         "1200 Griswold St",  -83.0498, 42.3306),
]

# ── NO_MATCH rows: owner score 37-56 (verified, well under the 65 floor). ──
NO_MATCH_ROWS = [
    _row("82-003-001.000", "Sunbelt Industrial Acquisitions LLC", "8000 W Fort St",    -83.0908, 42.3046),
    _row("82-003-002.000", "Pinegrove Family Office",             "19000 Schaefer Hwy",-83.1808, 42.4046),
    _row("82-003-003.000", "Lakeshore Veterinary Properties",     "4500 Belle Isle Ave",-82.9908, 42.3406),
    _row("82-003-004.000", "Anchor Bay Hospitality Group",        "14000 Kercheval Ave",-82.9408, 42.3806),
    _row("82-003-005.000", "Birchwood Senior Living LLC",         "12000 Conant St",   -83.0608, 42.3996),
    _row("82-003-006.000", "Harborview Capital Trust",            "5000 Mt Elliott St",-83.0258, 42.3596),
    _row("82-003-007.000", "Sterling Auto Group",                 "9000 Grand River Ave",-83.1108, 42.3656),
]

ALL_ROWS = AUTO_LINK_ROWS + SUGGESTED_ROWS + NO_MATCH_ROWS
assert len(ALL_ROWS) == 20


def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, restval="")
        writer.writeheader()
        for row in ALL_ROWS:
            writer.writerow(row)
    print(f"Wrote {len(ALL_ROWS)} rows x {len(FIELDNAMES)} columns -> {OUT_PATH}")


if __name__ == "__main__":
    main()
