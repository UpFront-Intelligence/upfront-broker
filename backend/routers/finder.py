"""
Property Finder — Oakland County ArcGIS parcel lookup.

GET  /api/finder/debug     → probe base URLs (diagnostic)
GET  /api/finder/parcels?zip= → CRE parcels for a zip, with exists_in_db flag
POST /api/finder/add          → create Property (+ optional Deal) from parcel data
"""
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.property import Property
from models.deal import Deal
from models.shared import EnrichmentCache
from auth_utils import get_current_user

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

# ── Oakland County parcel layer — confirmed MapServer endpoint ───────────────
OAKLAND_PARCELS_URL = (
    "https://gisservices.oakgov.com/arcgis/rest/services"
    "/Enterprise/EnterpriseOpenParcelDataMapService/MapServer/1"
)

OAKLAND_CANDIDATES = [
    # Confirmed primary (MapServer, not FeatureServer)
    "https://gisservices.oakgov.com/arcgis/rest/services/Enterprise/EnterpriseOpenParcelDataMapService/MapServer/1",
    # Fallbacks in priority order
    "https://gis.oakgov.com/arcgis/rest/services/CRAPublic/Parcels_Public_WM/FeatureServer/0",
    "https://gis.oakgov.com/arcgis/rest/services/CRAPublic/ParcelsPublic/FeatureServer/0",
    "https://services2.arcgis.com/jsIt88o7Q1eBVvmn/arcgis/rest/services/OC_Tax_Parcels_Public/FeatureServer/0",
]

MAX_PARCELS      = 2000
CACHE_ZIP_PREFIX = "oakland_zip_"
ZIP_TTL_DAYS     = 7

# Kept for /debug endpoint
ALT_BASES = [
    "https://gis.oakgov.com/arcgis/rest/services",
    "https://gis.oakgov.com/arcgis/rest/services/Property",
    "https://gis.oakgov.com/arcgis/rest/services/Parcels",
    "https://oakgov.maps.arcgis.com/arcgis/rest/services",
    "https://services1.arcgis.com/QHF6KMnTeiUQgmFe/arcgis/rest/services",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "UpFrontBroker/1.0 (credetroit@gmail.com)"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _classcode_to_type(code) -> Optional[str]:
    """Michigan state classification codes (Oakland County CLASSCODE field)."""
    if not code:
        return None
    s = str(code).strip()
    try:
        c = int(s)
    except (TypeError, ValueError):
        return s or None
    return {
        401: "Residential",
        402: "Residential Condo",
        403: "Residential Apartment",
        407: "Residential Vacant Land",
        201: "Commercial",
        202: "Commercial Condo",
        203: "Commercial Other",
        207: "Commercial Vacant Land",
        301: "Industrial",
        302: "Industrial Condo",
        303: "Industrial Other",
        307: "Industrial Other",
        101: "Agricultural",
        102: "Agricultural",
          1: "Exempt",
          2: "Exempt",
          6: "Exempt",
    }.get(c, s)   # unrecognized → raw classcode


# Keep old name as alias in case any callers still use it
_propclass_to_type = _classcode_to_type


def _webmercator_to_latlng(x: float, y: float) -> tuple[float, float]:
    """Convert Web Mercator (EPSG:3857/102100) x,y to WGS84 lat,lng."""
    import math
    lng = (x / 20037508.34) * 180
    lat = (y / 20037508.34) * 180
    lat = 180 / math.pi * (
        2 * math.atan(math.exp(lat * math.pi / 180)) - math.pi / 2
    )
    return lat, lng


def _centroid(geometry) -> tuple[Optional[float], Optional[float]]:
    """
    Return (lat, lng) centroid from an ESRI polygon geometry dict.
    Oakland MapServer returns Web Mercator (EPSG:3857) — convert to WGS84.
    """
    if not geometry:
        return None, None
    rings = geometry.get("rings", [])
    if not rings:
        return None, None
    pts = rings[0]   # outer ring
    if not pts:
        return None, None
    avg_x = sum(p[0] for p in pts) / len(pts)
    avg_y = sum(p[1] for p in pts) / len(pts)
    lat, lng = _webmercator_to_latlng(avg_x, avg_y)
    return round(lat, 6), round(lng, 6)


def _parcel_from_attrs(attrs: dict) -> dict:
    """Transform confirmed Oakland MapServer attribute dict into our parcel shape."""
    prop_type = _classcode_to_type(attrs.get("CLASSCODE"))
    city      = attrs.get("SITECITY") or attrs.get("CVTTAXDESCRIPTION") or ""
    assessed  = attrs.get("ASSESSEDVALUE") or attrs.get("TAXABLEVALUE")

    # SF: LIVING_AREA_SQFT is residential; Shape.area is parcel footprint (sq ft) for commercial
    sf_raw  = attrs.get("LIVING_AREA_SQFT")
    sf_area = attrs.get("Shape.area") or attrs.get("Shape_Area")
    if sf_raw:
        sf_rentable   = float(sf_raw)
        sf_label      = "sf_rentable"
    elif sf_area:
        sf_rentable   = round(float(sf_area), 0)
        sf_label      = "sf_est"   # parcel footprint — stored in notes
    else:
        sf_rentable   = None
        sf_label      = None

    owner = (attrs.get("NAME1") or "").strip()
    if attrs.get("NAME2"):
        owner = f"{owner} / {attrs['NAME2']}".strip(" /")

    notes_parts = []
    if attrs.get("STRUCTURE_DESC"):
        notes_parts.append(f"Structure: {attrs['STRUCTURE_DESC']}")
    if attrs.get("CVTTAXDESCRIPTION"):
        notes_parts.append(f"Municipality: {attrs['CVTTAXDESCRIPTION']}")
    if sf_label == "sf_est" and sf_rentable:
        notes_parts.append(f"Est. SF (parcel area): {int(sf_rentable):,}")

    return {
        "keypin":          attrs.get("KEYPIN") or attrs.get("PIN") or "",
        "pin":             attrs.get("PIN") or "",
        "address":         attrs.get("SITEADDRESS") or "",
        "city":            city.title(),
        "zip":             attrs.get("SITEZIP5") or "",
        "state":           attrs.get("SITESTATE") or "MI",
        "property_type":   prop_type,
        "subtype":         attrs.get("STRUCTURE_DESC") or "",
        "sf_rentable":     float(sf_rentable) if sf_rentable else None,
        "sf_land":         None,   # not in this layer
        "year_built":      None,   # not in this layer
        "assessed_value":  float(assessed) if assessed else None,
        "tax_year":        None,   # not in this layer
        "zoning":          None,   # not in this layer
        "owner":           owner,
        "owner_addr":      None,
        "owner_city":      None,
        "owner_state":     None,
        "owner_zip":       None,
        "bedrooms":        attrs.get("NUM_BEDS"),
        "bathrooms":       attrs.get("NUM_BATHS"),
        "notes":           "\n".join(notes_parts) or None,
    }


def _parcel_from_local_row(row) -> dict:
    """Build parcel dict from a local parcels table row (lowercase column names)."""
    try:
        d = dict(row._mapping)
    except AttributeError:
        d = dict(row)

    classcode = d.get("classcode")
    city      = d.get("sitecity") or d.get("cvttaxdescription") or ""
    assessed  = d.get("assessedvalue") or d.get("taxablevalue")

    sf_raw  = d.get("living_area_sqft")
    sf_area = d.get("shapearea")
    if sf_raw:
        sf_rentable, sf_label = float(sf_raw), "sf_rentable"
    elif sf_area:
        sf_rentable, sf_label = round(float(sf_area), 0), "sf_est"
    else:
        sf_rentable, sf_label = None, None

    owner = (d.get("name1") or "").strip()
    if d.get("name2"):
        owner = f"{owner} / {d['name2']}".strip(" /")

    notes_parts = []
    if d.get("structure_desc"):
        notes_parts.append(f"Structure: {d['structure_desc']}")
    if d.get("cvttaxdescription"):
        notes_parts.append(f"Municipality: {d['cvttaxdescription']}")
    if sf_label == "sf_est" and sf_rentable:
        notes_parts.append(f"Est. SF (parcel area): {int(sf_rentable):,}")

    return {
        "keypin":         d.get("keypin") or d.get("pin") or "",
        "pin":            d.get("pin") or "",
        "address":        d.get("siteaddress") or "",
        "city":           city.title(),
        "zip":            d.get("sitezip5") or "",
        "state":          d.get("sitestate") or "MI",
        "property_type":  _classcode_to_type(classcode),
        "subtype":        d.get("structure_desc") or "",
        "sf_rentable":    float(sf_rentable) if sf_rentable else None,
        "sf_land":        None,
        "year_built":     None,
        "assessed_value": float(assessed) if assessed else None,
        "tax_year":       None,
        "zoning":         None,
        "owner":          owner,
        "owner_addr":     None, "owner_city":  None,
        "owner_state":    None, "owner_zip":   None,
        "bedrooms":       d.get("num_beds"),
        "bathrooms":      d.get("num_baths"),
        "notes":          "\n".join(notes_parts) or None,
        # Raw fields passed through for the detail panel
        "name1":             (d.get("name1") or "").strip() or None,
        "name2":             (d.get("name2") or "").strip() or None,
        "postaladdress":     d.get("postaladdress") or None,
        "classcode":         d.get("classcode") or None,
        "cvttaxdescription": d.get("cvttaxdescription") or None,
        "taxablevalue":      float(d["taxablevalue"]) if d.get("taxablevalue") else None,
        "living_area_sqft":  float(d["living_area_sqft"]) if d.get("living_area_sqft") else None,
        "shapearea":         round(float(d["shapearea"]), 0) if d.get("shapearea") else None,
        "county":            "Oakland County",
    }


def _get_or_set_cache(db: Session, lookup_type: str, lookup_key: str,
                      ttl_days: int = 7) -> Optional[dict]:
    """Return cached raw_response if present and not expired."""
    entry = db.query(EnrichmentCache).filter(
        EnrichmentCache.lookup_type == lookup_type,
        EnrichmentCache.lookup_key  == lookup_key,
        EnrichmentCache.expires_at  > datetime.now(timezone.utc),
    ).first()
    if entry:
        entry.hit_count += 1
        db.commit()
        return entry.raw_response
    return None


def _save_cache(db: Session, lookup_type: str, lookup_key: str,
                source: str, data: dict, ttl_days: int = 7):
    # Delete stale entry first
    db.query(EnrichmentCache).filter(
        EnrichmentCache.lookup_type == lookup_type,
        EnrichmentCache.lookup_key  == lookup_key,
    ).delete()
    entry = EnrichmentCache(
        lookup_type  = lookup_type,
        lookup_key   = lookup_key,
        source       = source,
        raw_response = data,
        expires_at   = datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    db.add(entry)
    db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/test")
def test_layer(current_user: User = Depends(get_current_user)):
    """
    Three diagnostic probes against OAKLAND_PARCELS_URL.
    Returns raw responses so we can see real field names and supported syntax.

    test1 — simplest: where=1=1, no encoding
    test2 — zip with spaces: where=SITUSZIP = '48304'
    test3 — layer metadata: {url}?f=json  (shows actual field list)
    """
    url = OAKLAND_PARCELS_URL
    result: dict = {"url": url}

    # Test 1 — simplest possible, no where-clause encoding
    try:
        result["test1_where_1eq1"] = _get(
            f"{url}/query?where=1=1&resultRecordCount=1&outFields=*&f=json"
        )
    except Exception as exc:
        result["test1_where_1eq1"] = {"error": str(exc)}

    # Test 2 — confirmed zip field SITEZIP5
    try:
        result["test2_zip_query"] = _get(
            f"{url}/query?where=SITEZIP5 = '48304'&resultRecordCount=1&outFields=*&f=json"
        )
    except Exception as exc:
        result["test2_zip_query"] = {"error": str(exc)}

    # Test 3 — layer info to see actual field names
    try:
        result["test3_layer_info"] = _get(f"{url}?f=json")
    except Exception as exc:
        result["test3_layer_info"] = {"error": str(exc)}

    return result


@router.get("/debug")
def debug_arcgis(current_user: User = Depends(get_current_user)):
    """
    Diagnostic endpoint — probes every candidate base URL and returns the
    raw response (or error) for each. Use this to find what's actually
    available on OakGov ArcGIS before wiring the real layer URL.
    """
    results = {}
    for base in ALT_BASES:
        url = f"{base}?f=json"
        try:
            data = _get(url)
            # Summarise — return service names + types rather than the full blob
            services = data.get("services", [])
            folders  = data.get("folders", [])
            results[base] = {
                "ok":       True,
                "services": [{"name": s.get("name"), "type": s.get("type")} for s in services[:30]],
                "folders":  folders[:20],
                "raw_keys": list(data.keys()),
            }
        except Exception as exc:
            results[base] = {"ok": False, "error": str(exc)}
    return results


@router.get("/parcels")
def get_parcels(
    zip:          str     = Query(..., min_length=5, max_length=5),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Return all parcels for a zip code with per-user exists_in_db flag."""
    parcels: list = []

    # ── 1. Attributes from local parcels table (no record limit) ─────────────
    local_rows = []
    try:
        local_rows = db.execute(
            text("SELECT keypin, pin, siteaddress, sitecity, sitestate, sitezip5,"
                 " name1, name2, classcode, cvttaxdescription,"
                 " assessedvalue, taxablevalue, living_area_sqft, shapearea,"
                 " num_beds, num_baths, structure_desc, postaladdress"
                 " FROM parcels WHERE sitezip5 = :z"),
            {"z": zip},
        ).fetchall()
    except Exception:
        local_rows = []   # table doesn't exist yet — fall through to ArcGIS

    if local_rows:
        # ── 2. Geometry-only query to ArcGIS (KEYPIN + rings, no attrs) ──────
        geo_params = urllib.parse.urlencode({
            "where":             f"SITEZIP5='{zip}'",
            "outFields":         "KEYPIN",
            "returnGeometry":    "true",
            "geometryPrecision": "4",
            "resultRecordCount": max(MAX_PARCELS, len(local_rows)),
            "f":                 "json",
        })
        coord_map: dict = {}
        try:
            geo_data = _get(f"{OAKLAND_PARCELS_URL}/query?{geo_params}")
            for feat in geo_data.get("features", []):
                kp = (feat.get("attributes") or {}).get("KEYPIN", "")
                if kp and feat.get("geometry"):
                    lat, lng = _centroid(feat["geometry"])
                    if lat is not None:
                        coord_map[kp] = (lat, lng)
        except Exception:
            pass   # no coordinates — parcels still returned without map pins

        # ── 3. Join attributes + coordinates ─────────────────────────────────
        for row in local_rows:
            p = _parcel_from_local_row(row)
            kp = p.get("keypin", "")
            p["lat"], p["lng"] = coord_map.get(kp, (None, None))
            parcels.append(p)

    else:
        # ── Fallback: full ArcGIS query when local table is empty/missing ─────
        params = urllib.parse.urlencode({
            "where":             f"SITEZIP5='{zip}'",
            "outFields":         ("KEYPIN,PIN,SITEADDRESS,SITECITY,SITESTATE,SITEZIP5,"
                                  "NAME1,NAME2,CLASSCODE,CVTTAXDESCRIPTION,"
                                  "ASSESSEDVALUE,TAXABLEVALUE,"
                                  "LIVING_AREA_SQFT,Shape.area,"
                                  "NUM_BEDS,NUM_BATHS,STRUCTURE_DESC"),
            "returnGeometry":    "true",
            "geometryPrecision": "4",
            "resultRecordCount": MAX_PARCELS,
            "f":                 "json",
        })
        url  = f"{OAKLAND_PARCELS_URL}/query?{params}"
        data = None
        try:
            data = _get(url)
        except Exception as primary_exc:
            qs = url.split("/query?", 1)[1]
            for fallback in OAKLAND_CANDIDATES[1:]:
                try:
                    data = _get(f"{fallback}/query?{qs}")
                    break
                except Exception:
                    continue
            if data is None:
                raise HTTPException(503, f"All parcel layer URLs failed: {primary_exc}")

        if "error" in data:
            raise HTTPException(502, f"ArcGIS error: {data['error'].get('message','unknown')}")

        for feat in data.get("features", []):
            attrs = feat.get("attributes") or {}
            p     = _parcel_from_attrs(attrs)
            p["lat"], p["lng"] = _centroid(feat.get("geometry"))
            if p["lat"] is None:
                continue
            parcels.append(p)

    # Overlay per-user exists_in_db
    my_keypins = {
        row[0] for row in
        db.query(Property.parcel_id)
        .filter(Property.owner_id == current_user.id,
                Property.parcel_id.isnot(None)).all()
    }
    for p in parcels:
        p["exists_in_db"] = (p.get("keypin") or "") in my_keypins

    return {
        "parcels":   parcels,
        "total":     len(parcels),
        "zip":       zip,
        "layer_url": OAKLAND_PARCELS_URL,
    }


@router.get("/parcel/{keypin}")
def get_parcel_by_keypin(keypin: str, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    try:
        row = db.execute(
            text("SELECT name1, name2, cvttaxdescription, classcode, assessedvalue, taxablevalue, living_area_sqft, shapearea FROM parcels WHERE keypin = :k"),
            {"k": keypin}
        ).fetchone()
    except Exception:
        return {}
    if not row:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return {
        "name1": row.name1,
        "name2": row.name2,
        "cvttaxdescription": row.cvttaxdescription,
        "classcode": row.classcode,
        "assessedvalue": row.assessedvalue,
        "taxablevalue": row.taxablevalue,
        "living_area_sqft": row.living_area_sqft,
        "shapearea": row.shapearea
    }


@router.post("/add")
def add_parcel_to_pipeline(
    body:         dict,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """
    Create a Property from ArcGIS parcel data.
    body: {parcel: {...}, create_deal: bool}
    """
    parcel      = body.get("parcel", {})
    create_deal = bool(body.get("create_deal", False))
    keypin      = parcel.get("keypin") or ""

    # Duplicate check
    if keypin:
        existing = db.query(Property).filter(
            Property.owner_id == current_user.id,
            Property.parcel_id == keypin,
        ).first()
        if existing:
            return {"property": _prop_response(existing), "duplicate": True,
                    "deal": None}

    prop = Property(
        owner_id        = current_user.id,
        name            = parcel.get("address") or parcel.get("keypin", ""),
        address         = parcel.get("address") or "",
        city            = parcel.get("city") or "",
        state           = parcel.get("state") or "MI",
        zip             = parcel.get("zip") or "",
        property_type   = parcel.get("property_type"),
        subtype         = parcel.get("subtype") or None,
        sf_rentable     = parcel.get("sf_rentable"),
        sf_land         = parcel.get("sf_land"),
        year_built      = parcel.get("year_built"),
        assessed_value  = parcel.get("assessed_value"),
        tax_year        = parcel.get("tax_year"),
        zoning          = parcel.get("zoning") or None,
        parcel_id       = keypin or None,
        lat             = parcel.get("lat"),
        lng             = parcel.get("lng"),
        notes           = parcel.get("notes"),
        status          = "Active",
    )
    db.add(prop)
    db.flush()   # get prop.id before optional deal creation

    deal = None
    if create_deal:
        deal = Deal(
            owner_id    = current_user.id,
            property_id = prop.id,
            name        = f"{prop.address or prop.name} — Prospecting",
            stage       = "Prospecting",
        )
        db.add(deal)

    db.commit()
    db.refresh(prop)
    if deal:
        db.refresh(deal)

    return {
        "property":  _prop_response(prop),
        "duplicate": False,
        "deal":      {"id": deal.id, "name": deal.name, "stage": deal.stage} if deal else None,
    }


def _prop_response(p: Property) -> dict:
    return {"id": p.id, "name": p.name, "address": p.address,
            "city": p.city, "state": p.state, "parcel_id": p.parcel_id}
