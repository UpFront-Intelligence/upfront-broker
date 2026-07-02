"""Per-county SFR/vacant-residential filter for Regrid parcel ingestion.

Prep work only -- NOT wired into ingest_csv() yet (see that function in
regrid.py). Verified read-only against the real county CSVs in
"REGRID DATA DONT MOVE" on 2026-07-02; ready to call from ingest_csv() as a
per-row gate once ingestion resumes for real (see CLAUDE.md's REGRID OAKLAND
PILOT section -- parcels_regrid was dropped after a disk-full incident and
ingestion is paused pending the separate-Postgres-instance rebuild).

Three per-county strategies, because Michigan county assessors do NOT share
one usecode scheme:

  standard — Oakland, Washtenaw, Livingston, Wayne (mi_wayne, non-Detroit),
             Genesee. 3-digit MI State Tax Commission codes. Drops 401
             (single-family improved), 402 (residential vacant), 407
             (residential - building on leased land). Note 407 is NOT
             "residential vacant land" despite that being a common
             assumption -- 402 is. Both are dropped here regardless, so the
             mix-up doesn't change this filter's behavior, but don't
             conflate the two if this list is ever edited.

  detroit  — mi_wayne_detroit only. Detroit's assessor uses its own
             183-code, 5-digit scheme, incompatible with the 3-digit codes
             above (a literal 401/402/407 match against Detroit rows
             matches nothing -- confirmed 2026-07-02). Drops 41110 (SINGLE
             FAMILY) and 00003 (VACANT RESIDENTIAL). 41124 (NEZ LAND -- a
             residential tax-abatement vacant-land code, likely a 402
             equivalent) and 00VAC (unlabeled generic vacant, type unknown)
             are deliberately KEPT pending manual review -- don't fold them
             into the drop set without re-verifying against usedesc first.

  macomb_unfiltered — mi_macomb only. 92.8% of rows have no usecode at all,
             and the gap is concentrated by municipality (Warren, Sterling
             Heights, Macomb Twp etc. report 0% coverage; only Clinton Twp
             + slivers of St. Clair Shores/Mount Clemens report any
             usecode). The LBCS fallback columns were checked and rejected
             -- 90% of the blanks are the single generic label "Private
             household", too coarse to separate SFR from CRE. No reliable
             filter exists yet, so every row is kept and tagged instead of
             dropped, so the untagged rows are findable for cleanup once a
             Macomb-specific classification source shows up.

Extend COUNTY_FILTER_CONFIG for any county not yet in this map -- the
default is "standard", so a new plain-3-digit-code MI county doesn't need a
code change, only a config entry if it turns out to differ.
"""
from typing import Optional

STANDARD_DROP_CODES = frozenset({"401", "402", "407"})
DETROIT_DROP_CODES = frozenset({"41110", "00003"})

MACOMB_TAG_FIELD = "source_note"
MACOMB_TAG_VALUE = "macomb_unfiltered"

# filename (as shipped by Regrid / stored in "REGRID DATA DONT MOVE") -> strategy name
COUNTY_FILTER_CONFIG = {
    "mi_oakland.csv.gz": "standard",
    "mi_washtenaw.csv.gz": "standard",
    "mi_livingston.csv.gz": "standard",
    "mi_wayne.csv.gz": "standard",
    "mi_genesee.csv.gz": "standard",
    "mi_wayne_detroit.csv.gz": "detroit",
    "mi_macomb.csv.gz": "macomb_unfiltered",
}

DEFAULT_STRATEGY = "standard"


def strategy_for_file(filename: str) -> str:
    """Looks up the filter strategy for a county file by its filename.
    Falls back to 'standard' for anything not yet in COUNTY_FILTER_CONFIG."""
    return COUNTY_FILTER_CONFIG.get(filename, DEFAULT_STRATEGY)


def apply_filter(row: dict, strategy: str) -> tuple[bool, dict]:
    """Given one CSV row (dict keyed by lowercased column names -- the same
    shape ingest_csv() builds its `row` dict in) and a strategy name,
    returns (keep, tags).

    `keep` is False for rows the strategy drops (standard/detroit only --
    macomb_unfiltered never drops). `tags` is a dict of extra fields the
    caller should merge onto the record before storage; empty for
    standard/detroit, {'source_note': 'macomb_unfiltered'} for macomb.
    """
    usecode = (row.get("usecode") or "").strip()

    if strategy == "standard":
        return (usecode not in STANDARD_DROP_CODES), {}

    if strategy == "detroit":
        return (usecode not in DETROIT_DROP_CODES), {}

    if strategy == "macomb_unfiltered":
        return True, {MACOMB_TAG_FIELD: MACOMB_TAG_VALUE}

    raise ValueError(f"Unknown filter strategy: {strategy!r}")


def filter_row(row: dict, filename: str) -> tuple[bool, dict]:
    """Convenience wrapper: looks up the strategy for `filename` and applies
    it to `row` in one call. Returns (keep, tags) -- see apply_filter()."""
    return apply_filter(row, strategy_for_file(filename))
