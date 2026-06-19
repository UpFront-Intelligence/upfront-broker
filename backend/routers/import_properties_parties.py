"""
Properties + Parties fan-out import — one spreadsheet row creates/updates a
Property plus an Account and Contact for every detected party group
(leasing company, owner, sale company, tenant company, sublease broker),
all owner-scoped, in one pass.

POST /api/import/properties-with-parties/preview — headers + first 3 rows
POST /api/import/properties-with-parties         — streams NDJSON progress
                                                     lines, then a summary line
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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
from auth_utils import get_current_user
from services.naming import normalize_name
from services.accounts import ensure_role, owned_accounts_query
from routers.imports import _read_file

router = APIRouter()

MAX_ROWS = 5000
FUZZY_THRESHOLD = 88

# Standard property-level columns, in detection-summary display order.
PROPERTY_FIELDS = [
    ("address",        "Address",       "Building Address"),
    ("building_name",  "Building Name", "Building Name"),
    ("park_name",      "Park",          "Building Park"),
    ("property_type",  "Type",          "PropertyType"),
    ("status",         "Status",        "Building Status"),
    ("building_class", "Class",         "Building Class"),
    ("city",           "City",          "City"),
    ("state",          "State",         "State"),
    ("zip",            "Zip",           "Zip"),
    ("sf_rentable",    "SF",            "Rentable Building Area"),
    ("occupancy_pct",  "% Leased",      "Percent Leased"),
]

# (group key, spreadsheet column prefix, role slug, contact-link role label,
#  property FK column — None if there's no legacy FK slot for this role yet)
_PARTY_GROUPS = [
    ("leasing",  "Leasing Company", "leasing_broker",  "Leasing Contact",  "manager_account_id"),
    ("owner",    "Owner",           "owner",            "Owner Contact",    "recorded_owner_account_id"),
    ("sale",     "Sale Company",    "sale_broker",      "Sale Contact",     None),
    ("tenant",   "Tenant Company",  "tenant_rep",       "Tenant Contact",   None),
    ("sublease", "Sublease Broker", "sublease_broker",  "Sublease Contact", None),
]

# group -> human label, for the UI's detection-summary cards
PARTY_GROUP_LABELS = {key: prefix for key, prefix, *_ in _PARTY_GROUPS}

_GROUP_FIELD_SUFFIXES = [
    ("Name",            "account_name"),
    ("Contact",         "contact_name"),
    ("Address",         "address"),
    ("City State Zip",  "city_state_zip"),
    ("Phone",           "phone"),
]

# Cleaned header (lowercased, "PROPERTY:" prefix stripped) -> (group, field)
COLUMN_MAP = {h.lower(): ("property", field) for field, _, h in PROPERTY_FIELDS}
for _group_key, _prefix, *_ in _PARTY_GROUPS:
    for _suffix, _field in _GROUP_FIELD_SUFFIXES:
        COLUMN_MAP[f"{_prefix} {_suffix}".lower()] = (_group_key, _field)


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _clean_header(h: str) -> str:
    h = re.sub(r"(?i)^property\s*:\s*", "", (h or "").strip())
    return re.sub(r"\s+", " ", h.strip())


def _detect_columns(headers):
    colmap = {}
    for h in headers:
        target = COLUMN_MAP.get(_clean_header(h).lower())
        if target:
            colmap[h] = target
    return colmap


def _clean_zip5(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits[:5]


def _to_float(raw: str):
    try:
        return float(raw.replace(",", "").replace("%", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _normalize_address(addr: str) -> str:
    a = re.sub(r"[^\w\s]", " ", (addr or "").lower().strip())
    return re.sub(r"\s+", " ", a).strip()


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


def _extract_row_fields(row, colmap):
    prop_fields = {}
    groups = {key: {} for key in PARTY_GROUP_LABELS}
    for h, (group, field) in colmap.items():
        val = (row.get(h) or "").strip()
        if not val:
            continue
        (prop_fields if group == "property" else groups[group])[field] = val
    return prop_fields, groups


def _fill_blank(obj, field, value):
    if value and not getattr(obj, field, None):
        setattr(obj, field, value)


# ── Property upsert ───────────────────────────────────────────────────────────

def _upsert_property(db, prop_fields, owner_id, existing_props, warnings, row_num):
    address = prop_fields.get("address")
    norm_addr = _normalize_address(address)
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
        prop.zip = _clean_zip5(prop_fields["zip"])
    for field in ("building_name", "park_name", "property_type", "status", "building_class"):
        if prop_fields.get(field):
            setattr(prop, field, prop_fields[field])
    for field in ("sf_rentable", "occupancy_pct"):
        if prop_fields.get(field):
            val = _to_float(prop_fields[field])
            if val is not None:
                setattr(prop, field, val)

    if not prop.name:
        prop.name = prop.building_name or address

    db.flush()
    existing_props[norm_addr] = prop
    return prop, created


# ── Account / Contact find-or-create ──────────────────────────────────────────

def _find_or_create_account(db, name, owner_id, existing_accounts, warnings, row_num, group_label):
    norm = normalize_name(name)
    best, best_score = None, 0
    for acct in existing_accounts:
        score = fuzz.token_sort_ratio(norm, acct.normalized_name or "")
        if score > best_score:
            best, best_score = acct, score
    if best and best_score >= FUZZY_THRESHOLD:
        if best_score < 100:
            warnings.append(
                f"Row {row_num}: {group_label} — fuzzy-matched '{name}' to existing "
                f"account '{best.name}' ({best_score}%)")
        return best, False

    acct = Account(owner_id=owner_id, name=name, normalized_name=norm, roles=[])
    db.add(acct)
    db.flush()
    existing_accounts.append(acct)
    return acct, True


def _find_or_create_contact_at_account(db, full_name, acct, owner_id, role_label):
    first, last = _split_name(full_name)
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
                           role=role_label, is_primary=True))
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


# ── Per-row fan-out ────────────────────────────────────────────────────────────

def _process_row(db, row, colmap, owner_id, existing_props, existing_accounts,
                  counters, warnings, row_num):
    prop_fields, groups = _extract_row_fields(row, colmap)
    if not prop_fields.get("address"):
        raise ValueError("missing address")

    prop, created = _upsert_property(db, prop_fields, owner_id, existing_props, warnings, row_num)
    counters["properties_created" if created else "properties_updated"] += 1

    for group_name, group_label, role_slug, contact_role_label, fk_field in _PARTY_GROUPS:
        gfields = groups.get(group_name, {})
        name = gfields.get("account_name")
        if not name:
            continue

        acct, acct_created = _find_or_create_account(
            db, name, owner_id, existing_accounts, warnings, row_num, group_label)
        ensure_role(acct, role_slug)
        counters["accounts_created"] += int(acct_created)
        counters["accounts_linked"] += 1

        raw_csz = gfields.get("city_state_zip")
        if raw_csz:
            csz = _parse_city_state_zip(raw_csz)
            if csz:
                _fill_blank(acct, "city", csz["city"])
                _fill_blank(acct, "state", csz["state"])
                _fill_blank(acct, "zip", csz["zip"])
            else:
                _fill_blank(acct, "city", raw_csz)
                warnings.append(
                    f"Row {row_num}: could not parse {group_label} city/state/zip '{raw_csz}'")
        _fill_blank(acct, "address", gfields.get("address"))
        _fill_blank(acct, "phone", gfields.get("phone"))

        if fk_field:
            setattr(prop, fk_field, acct.id)
        if _add_property_party(db, prop.id, role_slug, account_id=acct.id):
            counters["property_parties_created"] += 1

        contact_name = gfields.get("contact_name")
        if contact_name:
            contact, contact_created = _find_or_create_contact_at_account(
                db, contact_name, acct, owner_id, contact_role_label)
            counters["contacts_created"] += int(contact_created)
            counters["contacts_linked"] += 1
            phone = gfields.get("phone")
            if phone:
                _add_contact_phone_if_new(db, contact, phone, "office", owner_id)
            if _add_property_party(db, prop.id, role_slug, contact_id=contact.id):
                counters["property_parties_created"] += 1


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/properties-with-parties/preview")
async def preview_properties_with_parties(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    headers, rows = _read_file(content, file.filename or "")
    if not headers:
        raise HTTPException(400, "Could not parse file — no headers found")

    colmap = _detect_columns(headers)
    if not any(g == "property" and f == "address" for g, f in colmap.values()):
        raise HTTPException(400, "Could not detect a 'Building Address' column — check header prefix")

    return {
        "headers":           headers,
        "preview_rows":      rows[:3],
        "total_rows":        len(rows),
        "detected_columns":  {h: f"{g}.{f}" for h, (g, f) in colmap.items()},
        "exceeds_limit":     len(rows) > MAX_ROWS,
        "max_rows":          MAX_ROWS,
    }


@router.post("/properties-with-parties")
async def import_properties_with_parties(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    headers, rows = _read_file(content, file.filename or "")
    if not headers:
        raise HTTPException(400, "Could not parse file — no headers found")
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"File has {len(rows)} data rows — max {MAX_ROWS} allowed")

    colmap = _detect_columns(headers)
    if not any(g == "property" and f == "address" for g, f in colmap.values()):
        raise HTTPException(400, "Could not detect a 'Building Address' column — check header prefix")

    owner_id = current_user.id
    total = len(rows)

    def gen():
        db = SessionLocal()
        counters = {k: 0 for k in (
            "properties_created", "properties_updated", "accounts_created",
            "accounts_linked", "contacts_created", "contacts_linked",
            "property_parties_created", "rows_skipped")}
        warnings, skipped_rows = [], []
        try:
            # Cached across rows for cross-row dedup within this run. Entries
            # stay valid after a per-row rollback — same session, so SQLAlchemy
            # just re-fetches expired attributes on next access.
            existing_props = {
                _normalize_address(p.address): p
                for p in db.query(Property).filter(Property.owner_id == owner_id).all()
            }
            existing_accounts = list(owned_accounts_query(db, owner_id).all())

            for i, row in enumerate(rows, start=1):
                try:
                    _process_row(db, row, colmap, owner_id, existing_props,
                                  existing_accounts, counters, warnings, i)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    counters["rows_skipped"] += 1
                    skipped_rows.append({"row": i, "reason": str(exc), "data": row})
                yield json.dumps({"type": "progress", "row": i, "total": total}) + "\n"

            yield json.dumps({
                "type": "done",
                **counters,
                "warnings": sorted(set(warnings)),
                "skipped_rows": skipped_rows,
            }) + "\n"
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="application/x-ndjson")
