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
# Detroit's own 5-digit scheme are NOT covered and will return None here,
# same gap that already existed in attach_parcel's use of this mapping.
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
