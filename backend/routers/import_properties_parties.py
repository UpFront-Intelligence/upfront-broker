"""
General-purpose property importer — one spreadsheet row creates/updates a
Property plus an Account+Contact for every party column group (any role,
fixed or custom) plus a Tenant link, all owner-scoped, in one pass.

Every column maps to exactly one of:
  property.<field>      — standard Property field
  party.<role>.<attr>   — Account+Contact fan-out under a role (role can be
                           one of the known slugs or any custom string)
  tenant.name           — find-or-create a Tenant, link via property_tenants
  ignore                — explicit skip

Auto-detection (recognizes both the "PROPERTY: X Y" prefix convention and
bare/"OWNER X" convention) only produces *suggestions* — every column's
mapping is editable regardless of what was detected.

POST /api/import/properties-with-parties/preview — headers + suggested
                                                     mapping + sample rows
POST /api/import/properties-with-parties         — streams NDJSON progress
                                                     lines, then a summary line
"""
import csv
import io
import json
import re

import openpyxl
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from rapidfuzz import fuzz

from database import SessionLocal
from models.user import User
from models.property import Property
from models.account import Account
from models.contact import Contact
from models.contact_account import ContactAccount
from models.contact_phone import ContactPhone
from models.property_party import PropertyParty
from models.tenant import Tenant
from models.property_tenant import PropertyTenant
from auth_utils import get_current_user
from services.naming import normalize_name, normalize_address
from services.national_locations import link_property_to_national_locations
from services.accounts import ensure_role, owned_accounts_query
from routers.imports import SYNONYMS, VALID_FIELDS, NUMERIC_FIELDS, _best_match, _coerce
from routers.properties import _geocode
from services.property_category import categorize_property_type

router = APIRouter()

MAX_ROWS = 5000
ACCOUNT_FUZZY_THRESHOLD = 88
TENANT_FUZZY_THRESHOLD = 55

# ── Known party roles ─────────────────────────────────────────────────────────
# slug -> (display label, legacy properties.*_account_id column or None).
# A column can also be assigned to any custom role string typed in the UI —
# those just get no legacy FK and a title-cased label.
KNOWN_ROLES = {
    "owner":           ("Owner",           "recorded_owner_account_id"),
    "leasing_broker":  ("Leasing Broker",  "manager_account_id"),
    "sale_broker":     ("Sale Broker",     None),
    "tenant_rep":      ("Tenant Rep",      None),
    "sublease_broker": ("Sublease Broker", None),
}


def role_info(role_slug: str):
    if role_slug in KNOWN_ROLES:
        label, fk_field = KNOWN_ROLES[role_slug]
        return label, fk_field
    return role_slug.replace("_", " ").replace("-", " ").title(), None


# ── Party attribute vocabulary ────────────────────────────────────────────────
# The brief's literal list, plus a few additions needed for backward
# compatibility with the existing "PROPERTY: Leasing Company *" convention
# (combined city/state/zip and full-name columns) — flagged in the report.
PARTY_ATTRIBUTES = [
    "company_name", "company_phone", "company_website", "company_industry",
    "company_address", "company_city", "company_state", "company_zip",
    "company_city_state_zip",                                          # addition
    "contact_first_name", "contact_last_name", "contact_full_name",     # *_full_name addition
    "contact_title", "contact_type",
    "contact_phone", "contact_mobile",
    "contact_phone_direct", "contact_phone_fax",                        # collapse targets
    "contact_phone_home", "contact_phone_other",                        # collapse targets
    "contact_email", "contact_other_email", "contact_website",           # *_website addition
    "contact_address", "contact_city", "contact_state", "contact_zip",
    "contact_city_state_zip",                                          # addition
]

# attribute -> ContactPhone label, for the phone-collapse attributes
_PHONE_LABELS = {
    "contact_phone": "office", "contact_mobile": "mobile",
    "contact_phone_direct": "direct", "contact_phone_fax": "fax",
    "contact_phone_home": "other", "contact_phone_other": "other",
}

# Fuzzy synonyms for matching a header's remainder (after stripping any role
# prefix) against a party attribute. Same matching style as imports.py's
# property-field synonyms, just a separate small vocabulary.
_ATTRIBUTE_SYNONYMS = {
    "company_name":           ["company name", "name", "company"],
    "company_phone":          ["phone", "company phone"],
    "company_website":        ["website", "company website", "web"],
    "company_industry":       ["industry", "company industry"],
    "company_address":        ["address", "street", "company address", "company street"],
    "company_city":           ["city", "company city"],
    "company_state":          ["state", "company state"],
    "company_zip":            ["zip", "company zip", "zip code"],
    "company_city_state_zip": ["city state zip", "city/state/zip"],
    "contact_first_name":     ["first name", "contact first name"],
    "contact_last_name":      ["last name", "contact last name"],
    "contact_full_name":      ["contact", "contact name", "full name"],
    "contact_title":          ["title", "contact title", "job title"],
    "contact_type":           ["contact type"],
    "contact_phone":          ["contact phone", "phone"],
    "contact_mobile":         ["mobile phone", "mobile", "cell", "cell phone"],
    "contact_phone_direct":   ["direct number", "direct phone", "direct"],
    "contact_phone_fax":      ["contact fax", "fax"],
    "contact_phone_home":     ["home phone"],
    "contact_phone_other":    ["other phone"],
    "contact_email":          ["email address", "email", "contact email"],
    "contact_other_email":    ["other email"],
    "contact_website":        ["contact website"],
    "contact_address":        ["contact address", "contact street"],
    "contact_city":           ["contact city"],
    "contact_state":          ["contact state"],
    "contact_zip":            ["contact zip"],
    "contact_city_state_zip": ["contact city state zip", "contact city/state/zip"],
}

# Bare (no role prefix) headers unambiguous enough to default to role="owner"
# without ever being confused for a property field.
_BARE_CONTACT_ATTRS = {
    "first name": "contact_first_name", "last name": "contact_last_name",
    "email address": "contact_email", "email": "contact_email",
    "mobile phone": "contact_mobile", "mobile": "contact_mobile",
    "home phone": "contact_phone_home", "direct number": "contact_phone_direct",
    "other phone": "contact_phone_other", "contact fax": "contact_phone_fax",
    "fax": "contact_phone_fax", "other email": "contact_other_email",
    "contact type": "contact_type", "title": "contact_title",
}
# Generic single words — ambiguous between company-level and contact-level;
# resolved by whether we've already passed a first/last-name column.
_BARE_GENERIC_ATTRS = {
    "phone": ("company_phone", "contact_phone"),
    "website": ("company_website", "contact_website"),
    "industry": ("company_industry", "company_industry"),
}

_ROLE_PATTERNS = [
    (re.compile(r"^leasing\s*company\b", re.I), "leasing_broker"),
    (re.compile(r"^sublease\s*broker\b", re.I), "sublease_broker"),
    (re.compile(r"^sale\s*company\b", re.I),    "sale_broker"),
    (re.compile(r"^seller\b", re.I),             "sale_broker"),
    (re.compile(r"^tenant\s*rep\b", re.I),       "tenant_rep"),
    (re.compile(r"^tenant\s*company\b", re.I),   "tenant_rep"),
    (re.compile(r"^owner\s*company\b", re.I),    "owner"),
    (re.compile(r"^owner\b", re.I),               "owner"),
]

# ── Exact-match overrides ─────────────────────────────────────────────────────
# Verified against both real files (Michigan_Retail.xlsx's "PROPERTY: X Y"
# convention and template.xlsx's bare "Property X" convention). Pure fuzzy
# matching against RESO_SYNONYMS is unreliable for short phrases (e.g.
# "Building Class" fuzzy-matches the pre-existing "subtype" synonym list
# before it matches its own "building_class" field; "Property Street" beats
# nothing reliably for "address"). These exact, deterministic mappings are
# tried first; RESO_SYNONYMS fuzzy matching is the fallback for headers
# neither file uses, exactly per "auto-detection... suggestions only."
# Keys here must already be in _norm_for_match() form (lowercase, punctuation
# stripped to spaces, whitespace collapsed) since that's what's looked up.
_PROPERTY_EXACT_OVERRIDES = {
    "building address": "address", "building name": "building_name",
    "building park": "park_name", "propertytype": "property_type",
    "building status": "status", "building class": "building_class",
    "rentable building area": "sf_rentable", "percent leased": "occupancy_pct",
    "property name": "name", "property street": "address",
    "property city": "city", "property state": "state", "property zip": "zip",
    "property county": "county", "property type": "property_type",
    "latitude": "lat", "longitude": "lng",
    "total square footage": "sf_rentable", "land sf": "sf_land",
    "number of stories": "stories", "construction": "construction_type",
    "parking ratio spaces per 100sq ft": "parking_ratio",
    "occupancy": "occupancy_pct", "parcel number": "parcel_id",
}

# Property fields RESO_SYNONYMS carries for the older single-linked-account
# import flow — always wrong here, since this importer's party system is
# strictly better for owner/contact data. Excluded from the fuzzy fallback.
_EXCLUDED_PROPERTY_FIELDS = {
    "owner_name", "owner_contact", "owner_phone", "owner_email",
    "owner_address", "owner_city_state_zip",
}
_PROPERTY_SYNONYMS_FILTERED = {
    f: syns for f, syns in SYNONYMS["property"].items() if f not in _EXCLUDED_PROPERTY_FIELDS
}


# ── File reading (positional — duplicate header names are real, e.g. two
#    columns both literally named "Phone") ───────────────────────────────────

def _read_file_positional(content: bytes, filename: str):
    """Returns (headers: list[str], rows: list[list[str]]) — rows are value
    lists aligned to headers by position, not dicts, since real templates
    repeat header text (e.g. a company-level "Phone" and a contact-level
    "Phone" column) that a name-keyed dict would silently collide on."""
    if (filename or "").lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not all_rows:
            return [], []
        headers = [str(h).strip() if h is not None else f"col_{i}"
                   for i, h in enumerate(all_rows[0])]
        rows = [[("" if v is None else str(v).strip()) for v in row] for row in all_rows[1:]]
        return headers, rows
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    headers = [h.strip() for h in all_rows[0]]
    rows = [[(v or "").strip() for v in row] for row in all_rows[1:]]
    return headers, rows


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _clean_header(h: str) -> str:
    h = re.sub(r"(?i)^property\s*:\s*", "", (h or "").strip())
    return re.sub(r"\s+", " ", h.strip())


def _norm_for_match(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _best_attribute_match(remainder: str):
    norm = _norm_for_match(remainder)
    if not norm:
        return None, 0
    best_attr, best_score = None, 0
    for attr, syns in _ATTRIBUTE_SYNONYMS.items():
        for syn in syns:
            score = fuzz.token_sort_ratio(norm, syn)
            if score > best_score:
                best_score, best_attr = score, attr
    return (best_attr if best_score >= 65 else None), best_score


def _clean_zip5(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits[:5]


def _split_name(full: str):
    parts = (full or "").strip().split(" ", 1)
    if not parts[0]:
        return None, None
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _parse_city_state_zip(raw: str):
    """'City, ST Zipcode[####]' -> {city, state, zip} or None on parse failure."""
    raw = (raw or "").strip()
    if "," not in raw:
        return None
    city, rest = raw.rsplit(",", 1)
    city, rest = city.strip(), rest.strip()
    if not city or len(rest) < 2:
        return None
    return {"city": city, "state": rest[:2].upper(), "zip": _clean_zip5(rest[2:])}


def _fill_blank(obj, field, value):
    if value and not getattr(obj, field, None):
        setattr(obj, field, value)


def _append_note_line(obj, label, value):
    """Collapse an attribute with no dedicated column into a labeled notes
    line — skips if that exact line is already present (idempotent re-import)."""
    if not value:
        return
    line = f"{label}: {value}"
    current = obj.notes or ""
    if line in current:
        return
    obj.notes = (current + ("\n" if current else "") + line)


# ── Column detection (suggestions only) ───────────────────────────────────────

def detect_column(header: str, contact_block_active: bool):
    """Returns (target_descriptor, score, contact_block_active_after).

    Priority, highest first: bare "Tenant" exact match; verified exact
    property-field overrides; role-prefixed party fields; unambiguous bare
    contact fields; bare generic fields (company/contact resolved by
    contact_block_active); RESO_SYNONYMS fuzzy fallback for property fields
    neither test file uses; ignore.
    """
    cleaned = _clean_header(header)
    norm = _norm_for_match(cleaned)

    if not norm:
        return "ignore", 0, contact_block_active

    if norm in ("tenant", "tenant name", "tenant company"):
        return "tenant.name", 95, contact_block_active

    if norm in _PROPERTY_EXACT_OVERRIDES:
        return f"property.{_PROPERTY_EXACT_OVERRIDES[norm]}", 100, contact_block_active

    for pattern, role_slug in _ROLE_PATTERNS:
        m = pattern.match(cleaned)
        if not m:
            continue
        remainder = cleaned[m.end():].strip()
        if not remainder:
            return "ignore", 0, contact_block_active   # section-divider cell, e.g. "OWNER "
        attr, score = _best_attribute_match(remainder)
        if attr:
            if attr in ("contact_first_name", "contact_last_name"):
                contact_block_active = True
            return f"party.{role_slug}.{attr}", score, contact_block_active
        break  # role matched but no attribute — fall through to other checks

    if norm in _BARE_CONTACT_ATTRS:
        return f"party.owner.{_BARE_CONTACT_ATTRS[norm]}", 80, True

    if norm in _BARE_GENERIC_ATTRS:
        company_attr, contact_attr = _BARE_GENERIC_ATTRS[norm]
        attr = contact_attr if contact_block_active else company_attr
        return f"party.owner.{attr}", 55, contact_block_active

    field, score = _best_match(norm, _PROPERTY_SYNONYMS_FILTERED)
    if field:
        return f"property.{field}", score, contact_block_active

    return "ignore", 0, contact_block_active


def suggest_mapping(headers):
    """Returns list of {"target": str, "score": int} aligned to headers."""
    suggestions = []
    contact_block_active = False
    for h in headers:
        target, score, contact_block_active = detect_column(h, contact_block_active)
        suggestions.append({"target": target, "score": score})
    return suggestions


# ── Target descriptor parsing ─────────────────────────────────────────────────

def _parse_target(descriptor):
    if not descriptor or descriptor in ("ignore", "_skip"):
        return None
    parts = descriptor.split(".")
    if parts[0] == "property" and len(parts) == 2:
        return {"kind": "property", "field": parts[1]}
    if parts[0] == "party" and len(parts) == 3:
        return {"kind": "party", "role": parts[1], "attribute": parts[2]}
    if parts[0] == "tenant":
        return {"kind": "tenant"}
    return None


def _extract_row(row_values, headers, mapping):
    """mapping: list aligned to headers — each a target descriptor string or
    None/"ignore". Returns (prop_fields: dict, parties: dict[role -> dict],
    tenant_name: str|None)."""
    prop_fields, parties, tenant_name = {}, {}, None
    for i, val in enumerate(row_values):
        val = (val or "").strip()
        if not val or i >= len(mapping):
            continue
        target = _parse_target(mapping[i])
        if not target:
            continue
        if target["kind"] == "property":
            prop_fields[target["field"]] = val
        elif target["kind"] == "party":
            parties.setdefault(target["role"], {})[target["attribute"]] = val
        elif target["kind"] == "tenant":
            tenant_name = val
    return prop_fields, parties, tenant_name


# ── Property upsert ───────────────────────────────────────────────────────────
# Generic over every field in VALID_FIELDS["property"] — prop_fields has
# already been through _coerce() (numeric/date casting) by the time this
# runs, so values just need an allowlist check, not per-field type handling.

def _upsert_property(db, prop_fields, owner_id, existing_props, warnings, row_num, uncategorized_types):
    address = prop_fields.get("address")
    norm_addr = normalize_address(address)
    prop = existing_props.get(norm_addr)
    created = False
    city, state = prop_fields.get("city", ""), prop_fields.get("state", "")

    if not prop:
        if not city or not state:
            warnings.append(f"Row {row_num}: missing city/state for '{address}'")
        prop = Property(owner_id=owner_id, address=address, city=city, state=state)
        db.add(prop)
        created = True
    else:
        if city:
            prop.city = city
        if state:
            prop.state = state

    if prop_fields.get("zip"):
        prop.zip = _clean_zip5(str(prop_fields["zip"]))

    for field, value in prop_fields.items():
        if field in ("address", "city", "state", "zip") or value in (None, ""):
            continue
        if field in VALID_FIELDS["property"]:
            setattr(prop, field, value)

    if not prop.name:
        prop.name = prop.building_name or address

    prop.property_category = categorize_property_type(prop.property_type)
    if prop.property_category == "Uncategorized":
        uncategorized_types.add(prop.property_type)

    if not prop.lat and prop.address:
        lat, lng = _geocode(prop.address, prop.city, prop.state)
        if lat is not None:
            prop.lat, prop.lng = lat, lng

    db.flush()   # assigns prop.id for new rows before link_property_to_national_locations
    link_property_to_national_locations(db, prop)
    existing_props[norm_addr] = prop
    return prop, created


# ── Account / Contact find-or-create ──────────────────────────────────────────

def _find_or_create_account(db, name, owner_id, existing_accounts, warnings, row_num, role_label):
    norm = normalize_name(name)
    best, best_score = None, 0
    for acct in existing_accounts:
        score = fuzz.token_sort_ratio(norm, acct.normalized_name or "")
        if score > best_score:
            best, best_score = acct, score
    if best and best_score >= ACCOUNT_FUZZY_THRESHOLD:
        if best_score < 100:
            warnings.append(
                f"Row {row_num}: {role_label} — fuzzy-matched '{name}' to existing "
                f"account '{best.name}' ({best_score}%)")
        return best, False

    acct = Account(owner_id=owner_id, name=name, normalized_name=norm, roles=[])
    db.add(acct)
    db.flush()
    existing_accounts.append(acct)
    return acct, True


def _find_or_create_contact_at_account(db, first, last, acct, owner_id, role_label):
    norm_first, norm_last = first.lower(), (last or "").lower()

    linked = (db.query(Contact)
                .join(ContactAccount, ContactAccount.contact_id == Contact.id)
                .filter(ContactAccount.account_id == acct.id, Contact.owner_id == owner_id)
                .all())
    for c in linked:
        if (c.first_name or "").lower() == norm_first and (c.last_name or "").lower() == norm_last:
            return c, False

    contact = Contact(owner_id=owner_id, first_name=first, last_name=last or "")
    db.add(contact)
    db.flush()
    db.add(ContactAccount(contact_id=contact.id, account_id=acct.id,
                           role=f"{role_label} Contact", is_primary=True))
    return contact, True


def _add_contact_phone_if_new(db, contact, number, label, owner_id):
    existing = db.query(ContactPhone).filter(
        ContactPhone.contact_id == contact.id, ContactPhone.number == number).first()
    if existing:
        return
    is_primary = db.query(ContactPhone).filter(
        ContactPhone.contact_id == contact.id).count() == 0
    db.add(ContactPhone(owner_id=owner_id, contact_id=contact.id, label=label,
                         number=number, is_primary=is_primary))
    db.flush()
    if is_primary:
        contact.phone = number


def _add_property_party(db, property_id, role, account_id=None, contact_id=None):
    """Duplicate-safe insert into property_parties — skips if the matching
    partial unique index (property_id, account_id, role) or
    (property_id, contact_id, role) would already be satisfied."""
    q = db.query(PropertyParty).filter(
        PropertyParty.property_id == property_id, PropertyParty.role == role)
    if account_id is not None:
        q = q.filter(PropertyParty.account_id == account_id)
    else:
        q = q.filter(PropertyParty.contact_id == contact_id)
    if q.first():
        return False
    db.add(PropertyParty(property_id=property_id, account_id=account_id,
                          contact_id=contact_id, role=role, source="import"))
    return True


# ── Tenant find-or-create + default-space link ────────────────────────────────
# Reuses the exact normalize_name + rapidfuzz.partial_ratio@55 matching the
# Tenant module already uses (routers/tenants.py) — no parallel matcher.

def _find_or_create_tenant(db, name, owner_id, existing_tenants):
    norm = normalize_name(name)
    best, best_score = None, 0
    for t in existing_tenants:
        score = fuzz.partial_ratio(norm, t.normalized_name or "")
        if score > best_score:
            best, best_score = t, score
    if best and best_score >= TENANT_FUZZY_THRESHOLD:
        return best, False

    t = Tenant(owner_id=owner_id, name=name, normalized_name=norm)
    db.add(t)
    db.flush()
    existing_tenants.append(t)
    return t, True


def _link_tenant_to_property(db, property_id, tenant_id, owner_id):
    existing_link = db.query(PropertyTenant).filter(
        PropertyTenant.property_id == property_id,
        PropertyTenant.tenant_id == tenant_id).first()
    if existing_link:
        return False
    has_any_space = db.query(PropertyTenant).filter(
        PropertyTenant.property_id == property_id).first() is not None
    db.add(PropertyTenant(
        owner_id=owner_id, property_id=property_id, tenant_id=tenant_id,
        notes=None if has_any_space else "Whole Building",
        source="import",
    ))
    return True


# ── Per-row fan-out ────────────────────────────────────────────────────────────

def _process_party(db, role_slug, attrs, prop, owner_id, existing_accounts, counters, warnings, row_num):
    name = attrs.get("company_name")
    if not name:
        return
    role_label, fk_field = role_info(role_slug)

    acct, acct_created = _find_or_create_account(
        db, name, owner_id, existing_accounts, warnings, row_num, role_label)
    ensure_role(acct, role_slug)
    counters["accounts_created"] += int(acct_created)
    counters["accounts_linked"] += 1

    raw_csz = attrs.get("company_city_state_zip")
    if raw_csz:
        csz = _parse_city_state_zip(raw_csz)
        if csz:
            _fill_blank(acct, "city", csz["city"])
            _fill_blank(acct, "state", csz["state"])
            _fill_blank(acct, "zip", csz["zip"])
        else:
            _fill_blank(acct, "city", raw_csz)
            warnings.append(f"Row {row_num}: could not parse {role_label} company city/state/zip '{raw_csz}'")
    _fill_blank(acct, "address", attrs.get("company_address"))
    _fill_blank(acct, "city", attrs.get("company_city"))
    _fill_blank(acct, "state", attrs.get("company_state"))
    if attrs.get("company_zip"):
        _fill_blank(acct, "zip", _clean_zip5(attrs["company_zip"]))
    _fill_blank(acct, "phone", attrs.get("company_phone"))
    _fill_blank(acct, "website", attrs.get("company_website"))
    _append_note_line(acct, "Industry", attrs.get("company_industry"))

    if fk_field:
        setattr(prop, fk_field, acct.id)
    if _add_property_party(db, prop.id, role_slug, account_id=acct.id):
        counters["property_parties_created"] += 1

    # Contact — from first/last name or a single combined "full name" column
    first = attrs.get("contact_first_name")
    last = attrs.get("contact_last_name")
    if not first and attrs.get("contact_full_name"):
        first, last = _split_name(attrs["contact_full_name"])
    if not first:
        return

    contact, contact_created = _find_or_create_contact_at_account(
        db, first, last, acct, owner_id, role_label)
    counters["contacts_created"] += int(contact_created)
    counters["contacts_linked"] += 1

    _fill_blank(contact, "title", attrs.get("contact_title"))
    _fill_blank(contact, "contact_type", attrs.get("contact_type"))
    _fill_blank(contact, "email", attrs.get("contact_email"))
    _append_note_line(contact, "Other email", attrs.get("contact_other_email"))
    _append_note_line(contact, "Website", attrs.get("contact_website"))

    _fill_blank(contact, "address", attrs.get("contact_address"))
    _fill_blank(contact, "city", attrs.get("contact_city"))
    _fill_blank(contact, "state", attrs.get("contact_state"))
    if attrs.get("contact_zip"):
        _fill_blank(contact, "zip", _clean_zip5(attrs["contact_zip"]))

    raw_ccsz = attrs.get("contact_city_state_zip")
    if raw_ccsz:
        parsed = _parse_city_state_zip(raw_ccsz)
        if parsed:
            _fill_blank(contact, "city", parsed["city"])
            _fill_blank(contact, "state", parsed["state"])
            _fill_blank(contact, "zip", parsed["zip"])
        else:
            warnings.append(f"Row {row_num}: could not parse {role_label} contact city/state/zip '{raw_ccsz}'")

    # Default inheritance — a contact with no distinct address of its own
    # takes its account's, same "fill blank from parent" pattern as the
    # account fields above. Never overwrites an explicit value.
    _fill_blank(contact, "address", acct.address)
    _fill_blank(contact, "city", acct.city)
    _fill_blank(contact, "state", acct.state)
    _fill_blank(contact, "zip", acct.zip)

    # company_phone mirrors onto the contact too (matches the historical
    # "PROPERTY: Leasing Company Phone" behavior — one shared switchboard
    # number for both the account and its linked contact).
    if attrs.get("company_phone"):
        _add_contact_phone_if_new(db, contact, attrs["company_phone"], "office", owner_id)
    for attr, label in _PHONE_LABELS.items():
        if attrs.get(attr):
            _add_contact_phone_if_new(db, contact, attrs[attr], label, owner_id)

    if _add_property_party(db, prop.id, role_slug, contact_id=contact.id):
        counters["property_parties_created"] += 1


def _process_row(db, row_values, headers, mapping, owner_id, existing_props, existing_accounts,
                  existing_tenants, counters, warnings, row_num, uncategorized_types):
    prop_fields, parties, tenant_name = _extract_row(row_values, headers, mapping)
    if not prop_fields.get("address"):
        raise ValueError("missing address")

    prop_fields = _coerce(prop_fields, "property")
    prop, created = _upsert_property(db, prop_fields, owner_id, existing_props, warnings, row_num,
                                      uncategorized_types)
    counters["properties_created" if created else "properties_updated"] += 1

    for role_slug, attrs in parties.items():
        _process_party(db, role_slug, attrs, prop, owner_id, existing_accounts, counters, warnings, row_num)

    if tenant_name:
        tenant, tenant_created = _find_or_create_tenant(db, tenant_name, owner_id, existing_tenants)
        counters["tenants_created"] += int(tenant_created)
        counters["tenants_linked"] += 1
        if _link_tenant_to_property(db, prop.id, tenant.id, owner_id):
            counters["property_tenants_created"] += 1


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/properties-with-parties/preview")
async def preview_properties_with_parties(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    headers, rows = _read_file_positional(content, file.filename or "")
    if not headers:
        raise HTTPException(400, "Could not parse file — no headers found")

    suggestions = suggest_mapping(headers)
    columns = [{"index": i, "header": h, "suggested_target": s["target"], "score": s["score"]}
               for i, (h, s) in enumerate(zip(headers, suggestions))]

    return {
        "headers":          headers,
        "columns":          columns,
        "preview_rows":     rows[:3],   # positional — headers can repeat (e.g. two "Phone" columns)
        "total_rows":       len(rows),
        "exceeds_limit":    len(rows) > MAX_ROWS,
        "max_rows":         MAX_ROWS,
        "party_attributes": PARTY_ATTRIBUTES,
        "known_roles":      [{"slug": slug, "label": label} for slug, (label, _) in KNOWN_ROLES.items()],
        "property_fields":  sorted(VALID_FIELDS["property"]),
    }


@router.post("/properties-with-parties")
async def import_properties_with_parties(
    file: UploadFile = File(...),
    mapping: str = Form(...),   # JSON array aligned to headers by index
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    headers, rows = _read_file_positional(content, file.filename or "")
    if not headers:
        raise HTTPException(400, "Could not parse file — no headers found")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"File has {len(rows)} data rows — max {MAX_ROWS} allowed")

    try:
        confirmed_mapping = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(400, "mapping must be a JSON array")
    if not isinstance(confirmed_mapping, list) or not all(
            t is None or isinstance(t, str) for t in confirmed_mapping):
        raise HTTPException(400, "mapping must be a JSON array of strings (or null)")
    if not any(_parse_target(t) == {"kind": "property", "field": "address"} for t in confirmed_mapping):
        raise HTTPException(400, "No column is mapped to property.address")

    owner_id = current_user.id
    total = len(rows)

    def gen():
        db = SessionLocal()
        counters = {k: 0 for k in (
            "properties_created", "properties_updated", "accounts_created",
            "accounts_linked", "contacts_created", "contacts_linked",
            "property_parties_created", "tenants_created", "tenants_linked",
            "property_tenants_created", "rows_skipped")}
        warnings, skipped_rows = [], []
        uncategorized_types = set()
        try:
            # Cached across rows for cross-row dedup within this run. Entries
            # stay valid after a per-row rollback — same session, so SQLAlchemy
            # just re-fetches expired attributes on next access.
            existing_props = {
                normalize_address(p.address): p
                for p in db.query(Property).filter(Property.owner_id == owner_id).all()
            }
            existing_accounts = list(owned_accounts_query(db, owner_id).all())
            existing_tenants = list(db.query(Tenant).filter(Tenant.owner_id == owner_id).all())

            for i, row in enumerate(rows, start=1):
                try:
                    _process_row(db, row, headers, confirmed_mapping, owner_id, existing_props,
                                 existing_accounts, existing_tenants, counters, warnings, i,
                                 uncategorized_types)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    counters["rows_skipped"] += 1
                    skipped_rows.append({"row": i, "reason": str(exc),
                                          "data": dict(zip(headers, row))})
                yield json.dumps({"type": "progress", "row": i, "total": total}) + "\n"

            yield json.dumps({
                "type": "done",
                **counters,
                "warnings": sorted(set(warnings)),
                "skipped_rows": skipped_rows,
                "uncategorized_property_types": sorted(uncategorized_types),
            }) + "\n"
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="application/x-ndjson")
