"""Shared name normalization for fuzzy matching (tenants, accounts)."""
import re

STRIP_WORDS = {
    'llc', 'corp', 'corporation', 'co', 'inc', 'incorporated', 'ltd', 'limited',
    'coffee', 'restaurant', 'cafe', 'company', 'the', 'group', 'holdings',
    'enterprises', 'bar', 'grill', 'kitchen', 'bistro', 'eatery', 'diner',
    'and', 'of', 'at', 'by',
    'trust', 'lp', 'llp',
}


def normalize_name(name: str) -> str:
    if not name:
        return ''
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", ' ', n)
    words = [w for w in n.split() if w not in STRIP_WORDS]
    return ' '.join(words) if words else n.strip()


def normalize_address(addr: str) -> str:
    a = re.sub(r"[^\w\s]", ' ', (addr or '').lower().strip())
    return re.sub(r"\s+", ' ', a).strip()
