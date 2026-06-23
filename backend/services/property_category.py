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
