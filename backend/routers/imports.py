"""
CSV / XLSX import with intelligent fuzzy field mapping.

POST /api/import/preview  — parse headers, suggest mapping with confidence scores
POST /api/import/execute  — import rows using confirmed mapping, detect duplicates
"""
import csv
import io
import json
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from rapidfuzz import fuzz
import openpyxl

from database import get_db
from models.user import User
from models.property import Property
from models.contact import Contact
from models.account import Account
from models.contact_account import ContactAccount
from auth_utils import get_current_user

router = APIRouter()

# ── Synonym dictionaries ──────────────────────────────────────────────────────

SYNONYMS = {
    "property": {
        "address":             ["address","property address","street address","street","addr",
                                "property addr","site address","location"],
        "city":                ["city","municipality","town"],
        "state":               ["state","st","province"],
        "zip":                 ["zip","zip code","postal","postal code"],
        "county":              ["county","county name","jurisdiction"],
        "property_type":       ["type","property type","asset type","use type","space use",
                                "building type"],
        "subtype":             ["subtype","sub type","sub-type","secondary type",
                                "building class","property subtype","class"],
        "sf_rentable":         ["sf","sqft","square feet","building size","rentable sf","rba",
                                "building sf","size","gla","rentable area"],
        "sf_land":             ["sf land","land sf","land area sf","land size","lot size sf",
                                "land square feet","lot sf","acreage sf","land area"],
        "asking_price":        ["asking price","list price","total price","sale price",
                                "list","offer price","asking total"],
        "asking_price_per_sf": ["asking price per sf","asking psf","price per sf","$/sf",
                                "price/sf","asking $/sf","list price psf","per sf","psf"],
        "year_built":          ["year built","year","built","year constructed"],
        "units":               ["units","unit count","number of units","# units","apt units"],
        "stories":             ["stories","floors","number of floors","num floors",
                                "building stories","number of stories","# floors","# stories"],
        "parking_ratio":       ["parking ratio","parking","parking spaces per 1000",
                                "parking/1000","p/1000","parking rate"],
        "occupancy_pct":       ["occupancy pct","occupancy %","occupancy percent","occupancy",
                                "occupied pct","leased pct","leased %","percent leased",
                                "percent occupied","current occupancy","occ %","occ pct"],
        "cap_rate":            ["cap rate","cap","capitalization rate"],
        "assessed_value":      ["assessed value","assessment","tax value","assessed"],
        "tax_amount":          ["tax amount","taxes","tax","annual tax","property tax",
                                "tax bill","real estate tax","tax assessment amount"],
        "tax_year":            ["tax year","assessment year","tax yr","year assessed"],
        "noi":                 ["noi","net operating income","net income","annual noi",
                                "operating income"],
        "parcel_id":           ["parcel","parcel id","pin","apn","parcel number","tax id"],
        "tenant":              ["tenant","tenants","current tenant","occupant"],
        "last_sale_price":     ["last sale price","sale price","sold price","last sold price"],
        "last_sale_date":      ["last sale date","sold date","sale date","last sold date"],
        "notes":               ["notes","comments","description","remarks","memo"],
        # ── Owner / linked-silo fields (map to Account + Contact, not Property) ──
        "owner_name":          ["owner name","owner","landlord","property owner",
                                "ownername1","ownername"],
        "owner_contact":       ["owner contact","contact name","contact person",
                                "owner contact name"],
        "owner_phone":         ["owner phone","phone","owner phone number","contact phone"],
        "owner_email":         ["owner email","email","owner email address","contact email"],
        "owner_address":       ["owner address","mailing address","owner mailing address"],
        "owner_city_state_zip":["owner city state zip","city state zip","owner csz"],
    },
    "contact": {
        "first_name":    ["first name","first","fname","given name","forename"],
        "last_name":     ["last name","last","lname","surname","family name"],
        "email":         ["email","email address","e-mail","e mail","mail"],
        "phone":         ["phone","phone number","office phone","work phone",
                          "telephone","office"],
        "mobile":        ["mobile","cell","cell phone","mobile phone","cellular"],
        "title":         ["title","job title","position","role","designation"],
        "company":       ["company","firm","organization","employer","brokerage"],
        "contact_type":  ["type","contact type","category","classification"],
        "notes":         ["notes","comments","bio","remarks"],
    },
    "account": {
        "name":        ["name","company name","entity name","account name","llc name",
                        "firm name","organization"],
        "entity_type": ["type","entity type","company type","structure","org type"],
        "ein":         ["ein","tax id","federal id","employer id","tin"],
        "phone":       ["phone","main phone","office phone","telephone"],
        "email":       ["email","contact email","main email"],
        "address":     ["address","mailing address","street address","business address"],
        "city":        ["city","town","municipality"],
        "state":       ["state","province"],
        "zip":         ["zip","postal code","zip code"],
        "notes":       ["notes","comments","description"],
    },
    "deal": {
        "name":             ["name","deal name","transaction name","opportunity","deal title"],
        "deal_type":        ["type","deal type","transaction type","listing type","rep type"],
        "stage":            ["stage","status","pipeline stage","deal status","phase"],
        "list_price":       ["list price","listing price","asking price","price"],
        "sale_price":       ["sale price","sold price","closed price","purchase price"],
        "commission_pct":   ["commission","commission pct","commission rate","commission %",
                             "fee"],
        "projected_close":  ["projected close","expected close","close date","target close",
                             "estimated close"],
        "notes":            ["notes","comments","remarks"],
    },
}

# Valid model fields — prevents unknown-kwarg crashes on model instantiation
VALID_FIELDS = {
    "property": {"name","address","city","state","zip","county","property_type","subtype",
                 "status","year_built","sf_rentable","sf_land","units","stories","zoning",
                 "parking_ratio","occupancy_pct","asking_price","asking_price_per_sf",
                 "assessed_value","tax_amount","tax_year","cap_rate","noi",
                 "parcel_id","legal_desc","tenant","last_sale_price","last_sale_date","notes"},
    # owner_* fields are virtual — handled in execute, never passed to Property()
    "_owner_fields": {"owner_name","owner_contact","owner_phone",
                      "owner_email","owner_address","owner_city_state_zip"},
    "contact":  {"first_name","last_name","email","phone","mobile","title",
                 "contact_type","source","notes"},
    "account":  {"name","entity_type","ein","website","phone","email",
                 "address","city","state","zip","notes"},
    "deal":     {"name","deal_type","stage","list_price","sale_price",
                 "commission_pct","projected_close","notes"},
}

# Fields that need numeric coercion
NUMERIC_FIELDS = {
    "property": {"sf_rentable":float,"sf_land":float,"asking_price":float,
                 "asking_price_per_sf":float,"assessed_value":float,"tax_amount":float,
                 "year_built":int,"units":int,"stories":int,"tax_year":int,
                 "parking_ratio":float,"occupancy_pct":float,"cap_rate":float,"noi":float,
                 "last_sale_price":float},
    "contact":  {},
    "account":  {},
    "deal":     {"list_price":float,"sale_price":float,"commission_pct":float},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return (s or "").lower().strip()


def _read_file(content: bytes, filename: str):
    """Returns (headers: list, rows: list[dict])."""
    if (filename or "").lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not all_rows:
            return [], []
        headers = [str(h).strip() if h is not None else f"col_{i}"
                   for i, h in enumerate(all_rows[0])]
        rows = []
        for row in all_rows[1:]:
            rows.append({headers[i]: (str(v).strip() if v is not None else "")
                         for i, v in enumerate(row)})
        return headers, rows
    else:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = list(reader.fieldnames or [])
        return headers, list(reader)


def _best_match(header: str, synonyms: dict):
    """Returns (field_name | None, score 0-100)."""
    h = _norm(header)
    best_field, best_score = None, 0
    for field, syns in synonyms.items():
        for syn in syns:
            score = fuzz.token_sort_ratio(h, _norm(syn))
            if score > best_score:
                best_score = score
                best_field = field
    return (best_field if best_score >= 60 else None), best_score


_DATE_FIELDS = {
    "property": {"last_sale_date"},
    "deal":     {"projected_close"},
}

_DATE_FMTS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%Y/%m/%d")

def _parse_date(val: str):
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _parse_csz(val: str):
    """Parse 'City, ST 12345' → (city, state, zip). Returns (None, None, None) on failure."""
    m = re.match(r'^(.+),\s*([A-Za-z]{2})\s+(\d{5})', val.strip())
    if m:
        return m.group(1).strip(), m.group(2).upper(), m.group(3)
    return None, None, None


def _coerce(mapped: dict, record_type: str) -> dict:
    """Numeric + date type coercion; silently skips unparseable values."""
    out = dict(mapped)
    for field, typ in NUMERIC_FIELDS.get(record_type, {}).items():
        if field in out and out[field]:
            try:
                out[field] = typ(str(out[field]).replace(",", "").replace("$", "")
                                 .replace("%", "").strip())
            except (ValueError, TypeError):
                del out[field]
    for field in _DATE_FIELDS.get(record_type, set()):
        if field in out and out[field]:
            parsed = _parse_date(str(out[field]))
            if parsed:
                out[field] = parsed
            else:
                del out[field]
    return out


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/preview")
async def preview_import(
    file:        UploadFile = File(...),
    record_type: str        = Form(...),
    current_user: User      = Depends(get_current_user),
):
    if record_type not in SYNONYMS:
        raise HTTPException(400, f"Unknown record_type: {record_type}")

    content = await file.read()
    headers, rows = _read_file(content, file.filename or "")
    if not headers:
        raise HTTPException(400, "Could not parse file — no headers found")

    syns = SYNONYMS[record_type]
    mapping = {}
    for h in headers:
        field, score = _best_match(h, syns)
        mapping[h] = {
            "field":      field,
            "score":      score,
            "confidence": "high" if score >= 85 else "medium" if score >= 60 else "none",
        }

    owner_fields_present = (
        record_type == "property" and
        any(v.get("field") in VALID_FIELDS.get("_owner_fields", set())
            for v in mapping.values())
    )

    return {
        "headers":            headers,
        "preview_rows":       rows[:3],
        "total_rows":         len(rows),
        "suggested_mapping":  mapping,
        "available_fields":   list(syns.keys()),
        "owner_columns_detected": owner_fields_present,
        "owner_notice": (
            "This import will also create Accounts and Contacts from owner data"
            if owner_fields_present else None
        ),
    }


@router.post("/execute")
async def execute_import(
    file:             UploadFile = File(...),
    record_type:      str        = Form(...),
    mapping:          str        = Form(...),   # JSON: {"CSV col": "model_field"|"_skip"|null}
    current_user:     User       = Depends(get_current_user),
    db:               Session    = Depends(get_db),
):
    if record_type not in SYNONYMS:
        raise HTTPException(400, f"Unknown record_type: {record_type}")

    confirmed = json.loads(mapping)           # {csv_header: field_name | "_skip" | null}
    content   = await file.read()
    _, rows   = _read_file(content, file.filename or "")

    valid        = VALID_FIELDS.get(record_type, set())
    owner_fields = VALID_FIELDS.get("_owner_fields", set())
    all_allowed  = valid | owner_fields   # both sets pass through to mapped
    imported, skipped = 0, 0
    duplicates, flagged, errors = [], [], []

    for row_num, row in enumerate(rows, start=2):
        try:
            # Build mapped dict from confirmed field assignments
            mapped = {}
            for csv_col, field in confirmed.items():
                if not field or field == "_skip":
                    continue
                if field not in all_allowed:
                    continue
                val = str(row.get(csv_col, "") or "").strip()
                if val:
                    mapped[field] = val

            mapped = _coerce(mapped, record_type)

            # ── Property ──────────────────────────────────────────
            if record_type == "property":
                if not mapped.get("address"):
                    flagged.append({"row": row_num, "reason": "Missing address",
                                    "data": dict(row)})
                    continue
                existing = db.query(Property).filter(
                    Property.owner_id == current_user.id,
                    Property.address.ilike(mapped.get("address", "")),
                    Property.city.ilike(mapped.get("city", "")),
                ).first()
                if existing:
                    duplicates.append({"row": row_num,
                                       "reason": f"{mapped.get('address')}, {mapped.get('city')} already exists"})
                    skipped += 1
                    continue

                # Separate owner fields (go to Account/Contact) from property fields
                owner_fields = VALID_FIELDS.get("_owner_fields", set())
                owner_data   = {k: v for k, v in mapped.items() if k in owner_fields}
                prop_data    = {k: v for k, v in mapped.items() if k not in owner_fields}

                if not prop_data.get("name"):
                    prop_data["name"] = prop_data.get("address", "")

                prop = Property(**{k: v for k, v in prop_data.items() if k in valid},
                                owner_id=current_user.id)
                db.add(prop)
                db.flush()   # need prop.id for Account link

                # ── Create / link Account from owner_name ──────────
                acct = None
                if owner_data.get("owner_name"):
                    acct_name = owner_data["owner_name"].strip()
                    acct = db.query(Account).filter(
                        Account.owner_id == current_user.id,
                        Account.name.ilike(acct_name),
                    ).first()
                    if not acct:
                        city_o, state_o, zip_o = _parse_csz(
                            owner_data.get("owner_city_state_zip") or "")
                        acct = Account(
                            owner_id = current_user.id,
                            name     = acct_name,
                            address  = owner_data.get("owner_address") or None,
                            city     = city_o,
                            state    = state_o,
                            zip      = zip_o,
                        )
                        db.add(acct)
                        db.flush()
                    prop.account_id = acct.id

                # ── Create / link Contact from owner_contact ───────
                if owner_data.get("owner_contact"):
                    parts   = owner_data["owner_contact"].strip().split(" ", 1)
                    first   = parts[0]
                    last    = parts[1] if len(parts) > 1 else ""
                    email   = (owner_data.get("owner_email") or "").lower() or None
                    phone   = owner_data.get("owner_phone") or None

                    contact = None
                    if email:
                        contact = db.query(Contact).filter(
                            Contact.owner_id == current_user.id,
                            Contact.email == email,
                        ).first()
                    if not contact:
                        contact = db.query(Contact).filter(
                            Contact.owner_id == current_user.id,
                            Contact.first_name.ilike(first),
                            Contact.last_name.ilike(last),
                        ).first()
                    if not contact:
                        contact = Contact(
                            owner_id     = current_user.id,
                            first_name   = first,
                            last_name    = last,
                            email        = email,
                            phone        = phone,
                            contact_type = "Owner",
                        )
                        db.add(contact)
                        db.flush()

                    # Link contact ↔ account (if account exists and not already linked)
                    if acct:
                        already = db.query(ContactAccount).filter(
                            ContactAccount.contact_id == contact.id,
                            ContactAccount.account_id == acct.id,
                        ).first()
                        if not already:
                            db.add(ContactAccount(
                                contact_id = contact.id,
                                account_id = acct.id,
                                role       = "Owner",
                                is_primary = True,
                            ))

            # ── Contact ───────────────────────────────────────────
            elif record_type == "contact":
                if not mapped.get("first_name") and not mapped.get("last_name"):
                    flagged.append({"row": row_num, "reason": "Missing name",
                                    "data": dict(row)})
                    continue
                email = (mapped.get("email") or "").lower()
                if email:
                    existing = db.query(Contact).filter(
                        Contact.owner_id == current_user.id,
                        Contact.email == email,
                    ).first()
                    if existing:
                        duplicates.append({"row": row_num,
                                           "reason": f"Contact {email} already exists"})
                        skipped += 1
                        continue
                    mapped["email"] = email
                db.add(Contact(**{k: v for k, v in mapped.items() if k in valid},
                               owner_id=current_user.id))

            # ── Account ───────────────────────────────────────────
            elif record_type == "account":
                if not mapped.get("name"):
                    flagged.append({"row": row_num, "reason": "Missing account name",
                                    "data": dict(row)})
                    continue
                existing = db.query(Account).filter(
                    Account.owner_id == current_user.id,
                    Account.name.ilike(mapped.get("name", "")),
                ).first()
                if existing:
                    duplicates.append({"row": row_num,
                                       "reason": f"Account '{mapped.get('name')}' already exists"})
                    skipped += 1
                    continue
                db.add(Account(**{k: v for k, v in mapped.items() if k in valid},
                               owner_id=current_user.id))

            # ── Deal (preview-only — requires property linking) ───
            elif record_type == "deal":
                flagged.append({"row": row_num,
                                 "reason": "Deals require a linked Property — add via the Deals page",
                                 "data": mapped})
                continue

            imported += 1

        except Exception as exc:
            errors.append({"row": row_num, "reason": str(exc)})

    if imported > 0:
        db.commit()

    return {
        "imported":     imported,
        "skipped":      skipped,
        "flagged":      len(flagged),
        "flagged_rows": flagged,
        "duplicates":   duplicates,
        "errors":       errors,
    }
