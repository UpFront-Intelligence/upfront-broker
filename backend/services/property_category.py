"""
Maps Property.property_type (free-text, whatever a CoStar-style export or
manual entry happens to say) onto the fixed 10-category property_category
taxonomy. Pattern/keyword-based, not a literal lookup of today's exact
strings — future imports will bring property_type values we haven't seen
yet, and they still need to land somewhere sensible. See CLAUDE.md's
PROPERTY_CATEGORY section for the full rule list and the Flex/R&D
ordering judgment call explained below.
"""
import logging

logger = logging.getLogger(__name__)

CATEGORIES = [
    "Multi-Family", "Office", "Industrial", "Retail", "Health Care",
    "Hospitality", "Flex", "Land", "Sports & Entertainment", "Specialty",
]

# Order matters — first match wins. Flex's "tech/r&d" is checked before
# Office's bare "r&d" so a compound "Tech/R&D" property_type lands in Flex,
# not Office (CoStar's own glossary lists Flex under both Industrial and as
# its own category inconsistently — this codebase defaults R&D-flavored
# Flex into its own bucket; revisit once real Flex data shows up).
_CONTAINS_RULES = [
    ("Flex",                   ["flex", "showroom", "tech/r&d"]),
    ("Office",                 ["office", "medical office", "r&d", "research"]),
    ("Industrial",             ["industrial", "warehous", "distribution", "manufactur",
                                 "cold storage", "truck terminal"]),
    ("Multi-Family",           ["multi-family", "apartment", "garden", "mid-rise", "high-rise"]),
    ("Health Care",            ["assisted living", "nursing", "hospital", "senior housing", "ccrc"]),
    ("Hospitality",            ["hotel", "motel", "resort", "extended stay"]),
    ("Land",                   ["land"]),
    ("Sports & Entertainment", ["amusement", "bowling", "golf", "marina", "theater", "arena", "stadium"]),
    ("Specialty",              ["self-storage", "religious", "day care", "car wash", "parking structure"]),
]


def categorize_property_type(property_type):
    """Returns one of CATEGORIES, "Uncategorized" (matched nothing — logged
    so unmatched values are visible, not silently swallowed), or None
    (property_type itself was empty — never forced into a bucket)."""
    if not property_type:
        return None
    pt = property_type.strip().lower()
    if pt.startswith("general retail"):
        return "Retail"
    for category, keywords in _CONTAINS_RULES:
        if any(kw in pt for kw in keywords):
            return category
    logger.warning("property_category: unmatched property_type %r — using Uncategorized", property_type)
    return "Uncategorized"


# Oakland County CLASSCODE (MI State Tax Commission numeric code) -> this
# app's CRE property_type vocabulary (PROP_TYPES on property.html), the
# vocabulary categorize_property_type() above actually understands.
# Promoted here from routers/properties.py (2026-07-03) when
# routers/finder.py needed the same mapping for parcels_regrid rows — same
# "one real function, not two copies" reasoning that moved normalize_address
# into services/naming.py.
#
# Distinct from routers/finder.py's _classcode_to_type(), which returns
# generic Michigan tax-classification labels ("Commercial", "Residential")
# for raw parcel display — those labels don't match categorize_property_type()'s
# vocabulary and must NOT be used to derive property_category.
#
# Only covers codes that can appear in parcels_regrid after usecode
# filtering (401/402/407 standard, 41110/00003 Detroit are already dropped
# at ingest) — 303/307 (Industrial BLL), 101/102 (Agricultural), and
# Detroit's own 5-digit scheme are NOT covered and will return None here.
# This is now a DELIBERATE scoping, not just a gap: callers that know a
# row's source_county is 'wayne_detroit' should call
# parcel_usedesc_to_property_type_detroit() below instead of this function
# entirely (see finder.py's _parcel_from_regrid_row(), which branches on
# source_county for exactly this reason) — this also closes a latent bug
# flagged in earlier recon, where this function was being called unscoped
# on every parcel including Detroit's, with no county-awareness to prevent
# a 5-digit Detroit code (some of which have leading zeros that vanish
# under int() — e.g. "00003" parses to 3, not "003") from numerically
# colliding with one of these 3-digit keys. attach_parcel() in
# routers/properties.py still calls this function unscoped against the
# legacy Oakland-only `parcels` table's classcode column — that table only
# ever contains standard 3-digit codes (Oakland is never Detroit), so no
# collision risk there today, but if attach_parcel is ever extended to
# source from parcels_regrid instead, it would need the same source_county
# branching finder.py now has.
PARCEL_CLASSCODE_PROPERTY_TYPE = {
    201: "Office",       # Commercial
    202: "Office",       # Commercial Condo
    203: "Office",       # Commercial Other
    207: "Land",         # Commercial Vacant
    301: "Industrial",
    302: "Industrial",   # Industrial Condo
    403: "Multifamily",  # Residential Apartment
    407: "Land",         # Residential Vacant Land
}


def parcel_classcode_to_property_type(code):
    try:
        return PARCEL_CLASSCODE_PROPERTY_TYPE.get(int(str(code).strip()))
    except (TypeError, ValueError):
        return None


# ── Detroit-specific usedesc keyword classifier (2026-07-06) ────────────────
# Standard MI counties (Oakland, Wayne non-Detroit, Washtenaw, Livingston,
# Genesee) were investigated and REJECTED as targets for a usedesc-based
# retail classifier: confirmed via recon against live prod data that
# usedesc is null for 67% of usecode=201 rows there, and the populated
# values are boilerplate restatements of the classcode itself
# ("COMMERCIAL", "201-COMMERCIAL IMPROVED") with zero retail-specificity.
# zoning_subtype was also tested and rejected — 95% of usedesc-confirmed
# retail parcels in those counties are zoned "General Commercial," not
# anything retail-specific, so it doesn't discriminate either. Standard
# counties therefore still have NO retail detection and keep using
# parcel_classcode_to_property_type() above, untouched — a future retail
# signal for those counties will need a different mechanism entirely
# (leading candidate: Overture national_locations brand-matching against
# known retail chains, not usedesc/zoning parsing — see CLAUDE.md).
#
# wayne_detroit (Detroit's own 183-code, 5-digit assessor scheme) is
# different: usedesc there is real, specific, and populated — STORE-RETAIL,
# SHOPPING CENTER, MIXED USE-RETAIL, SUPERMARKET, DRUG STORE, RESTAURANT,
# BANK BRANCH, BAR, GAS STATION variants, OFFICE BLDG variants, WAREHOUSE
# variants, TWO/THREE/FOUR/FIVE/SIX FAMILY, APT variants, DUPLEX, VACANT
# COMMERCIAL/INDUSTRIAL, etc. This function is Detroit-only BY DESIGN, not
# a general-purpose usedesc classifier — do not call it for any other
# source_county; parcel_classcode_to_property_type() remains correct there.
#
# Order matters — first match wins, same pattern as _CONTAINS_RULES above.
# Keyword list is based on the actual usedesc vocabulary confirmed present
# in wayne_detroit via recon, not invented categories.
_DETROIT_USEDESC_RULES = [
    # "vacant" is checked FIRST, ahead of every type-word rule below,
    # because "VACANT COMMERCIAL/INDUSTRIAL" (present in the real usedesc
    # data per recon) would otherwise hit the Industrial rule's "industrial"
    # keyword before ever reaching this one. Same precedent already set by
    # PARCEL_CLASSCODE_PROPERTY_TYPE above: codes 207 ("Commercial Vacant")
    # and 407 ("Residential Vacant Land") both map to Land, not Office/
    # Multifamily, despite their underlying zoned use — vacant-ness
    # overrides the zoned-use word, consistently, in both classifiers.
    ("Land",        ["vacant"]),
    ("Retail",      ["store", "retail", "shopping center", "supermarket",
                      "drug store", "restaurant", "bank branch", "bar",
                      "gas station"]),
    ("Office",      ["office"]),
    ("Industrial",  ["warehous", "manufactur", "industrial"]),
    ("Multifamily", ["family", "apt", "duplex", "row house"]),
]


def parcel_usedesc_to_property_type_detroit(usedesc):
    """Detroit-only (source_county == 'wayne_detroit') usedesc keyword
    classifier — see _DETROIT_USEDESC_RULES above for why this approach
    works for Detroit specifically but was rejected for standard counties.
    Case-insensitive substring match, first rule wins. Returns one of
    Retail/Office/Industrial/Multifamily/Land, or None if usedesc is blank
    or matches no keyword."""
    if not usedesc:
        return None
    desc = usedesc.strip().lower()
    for category, keywords in _DETROIT_USEDESC_RULES:
        if any(kw in desc for kw in keywords):
            return category
    return None
