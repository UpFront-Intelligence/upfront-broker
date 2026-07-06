"""
Property Finder — Oakland County ArcGIS parcel lookup.

GET  /api/finder/debug     → probe base URLs (diagnostic)
GET  /api/finder/parcels?zip= → CRE parcels for a zip, with exists_in_db flag
GET  /api/finder/public-record/{property_id} → parcels_regrid first, live
                                  ArcGIS/local-parcels fallback for counties
                                  not yet ingested (see get_public_record)
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
from models.account import Account
from models.deal import Deal
from models.parcel_regrid import ParcelRegrid
from models.shared import EnrichmentCache, Activity
from services.naming import normalize_address
from services.property_category import (
    parcel_classcode_to_property_type,
    parcel_usedesc_to_property_type_detroit,
)
from services.regrid import create_and_link_account_from_parcel_owner
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


def _get_parcels_legacy_arcgis(
    zip:          str,
    db:           Session,
    current_user: User,
):
    """Legacy path: local `parcels` table (Oakland-only) with live-ArcGIS
    fallback. Kept in place, unreachable (no @router decorator) — replaced
    as the live /parcels route by the parcels_regrid-backed get_parcels()
    below on 2026-07-03. Not deleted yet; clean up once the new path is
    verified live. Body is otherwise byte-for-byte what GET /parcels used
    to do."""
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


MAX_PARCELS_REGRID_RESULTS = 500


def _safe_int(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _bldg_sqft_from_raw_data(raw_data: dict):
    """'bldg_sqft' (36.4% populated in a 500-row production sample,
    2026-07-03) with 'area_building' as a fallback ONLY when bldg_sqft
    itself is null (22.4% populated, a different, lower-coverage concept —
    do NOT use ll_bldg_footprint_sqft, that's building FOOTPRINT/ground-
    outline, not total building SF). Extracted out of
    _parcel_from_regrid_row() so get_public_record()'s "Building SF" row
    (property.html's Public Record tab) uses the exact same extraction,
    not a second copy — see that endpoint for why this is explicitly NOT
    conflated with Property.sf_rentable (a different, commercial-leasing
    concept)."""
    bldg_sqft = _safe_int(raw_data.get("bldg_sqft"))
    if bldg_sqft is None:
        bldg_sqft = _safe_int(raw_data.get("area_building"))
    return bldg_sqft


def _derive_property_type_for_parcel(row: ParcelRegrid):
    """Same source_county branching _parcel_from_regrid_row() uses below:
    wayne_detroit rows go through the usedesc keyword classifier (its own
    5-digit scheme has no classcode mapping and calling the classcode
    function unscoped risked numeric collisions — see that classifier's
    docstring), every other county through the 3-digit classcode
    classifier. Extracted so get_public_record()'s "Class/Type" accept
    affordance (property.html's Public Record tab) uses the exact same
    derivation as the map display, not a second copy."""
    if row.source_county == "wayne_detroit":
        return parcel_usedesc_to_property_type_detroit(row.usedesc)
    return parcel_classcode_to_property_type(row.usecode)


def _parcel_from_regrid_row(row: ParcelRegrid) -> dict:
    """Shapes a parcels_regrid row into the same parcel dict contract
    _parcel_from_local_row()/_parcel_from_attrs() above already produce, so
    finder.html's existing renderParcels()/openPanel() work unchanged once
    this endpoint is wired to the page (next phase). Fields the legacy
    `parcels` table had that parcels_regrid doesn't (classcode,
    cvttaxdescription, living_area_sqft, shapearea, bedrooms, bathrooms,
    taxablevalue, postaladdress) are simply omitted rather than guessed —
    openPanel()'s row() helper already skips any null/empty field, so this
    doesn't break rendering, just shows fewer detail rows for now.

    property_type comes from parcel_classcode_to_property_type()
    (services/property_category.py) — the classifier actually used in the
    real property_category write-site chain (attach_parcel), NOT finder.py's
    own _classcode_to_type() a few functions up, which returns a different,
    incompatible vocabulary (generic tax labels like "Commercial" instead of
    this app's CRE types like "Office") that was never meant to drive
    property_category.

    EXCEPT for source_county == 'wayne_detroit': that county's usecode is a
    separate 5-digit assessor scheme parcel_classcode_to_property_type()
    was never meant to read (and calling it unscoped risked numeric
    collisions with the 3-digit standard-county keys — a latent bug flagged
    in recon, closed by this branch). Detroit rows call
    parcel_usedesc_to_property_type_detroit(row.usedesc) instead — see that
    function's docstring for why usedesc is a viable signal there but was
    rejected for every other county. Standard counties still have no retail
    detection at all; only Detroit gets a "Retail" output today.

    bldg_sqft/year_built/num_units come from raw_data JSON, not dedicated
    columns — confirmed real key names against a 500-row production sample
    (2026-07-03): 'bldg_sqft' (36.4% populated) with 'area_building' as a
    fallback ONLY when bldg_sqft itself is null (22.4% populated, a
    different, lower-coverage concept — do NOT use ll_bldg_footprint_sqft,
    that's building FOOTPRINT/ground-outline, not total building SF, and
    conflating them would mislabel real data). 'year_built' (20.4%
    populated, 'yearbuilt' is a confirmed duplicate, ignored). 'num_units'
    (0.4% populated — included anyway; openPanel()'s row() helper already
    skips it on the ~99.6% of parcels where it's absent, so a near-empty
    field costs nothing). No value is fabricated when raw_data lacks a key —
    _safe_int() returns None, and None keys are simply omitted from display,
    same as every other field this function already treats this way.
    """
    raw_data = row.raw_data or {}
    bldg_sqft = _bldg_sqft_from_raw_data(raw_data)
    year_built = _safe_int(raw_data.get("year_built"))
    num_units = _safe_int(raw_data.get("num_units"))
    property_type = _derive_property_type_for_parcel(row)

    return {
        "source":         "prospect",
        "property_id":    None,
        "keypin":         row.parcel_id,
        "pin":            row.parcel_id,
        "address":        row.address or "",
        "city":           (row.city or "").title(),
        "zip":            row.zip or "",
        "state":          row.state or "MI",
        "property_type":  property_type,
        "subtype":        row.usedesc or "",
        "sf_rentable":    None,   # not a parcels_regrid column — see bldg_sqft below
        "sf_land":        None,
        "bldg_sqft":      bldg_sqft,   # raw_data['bldg_sqft'], falls back to raw_data['area_building']
        "num_units":      num_units,   # raw_data['num_units'] — sparse (0.4%), included anyway
        "year_built":     year_built,  # raw_data['year_built']
        "assessed_value": float(row.assessed_value) if row.assessed_value is not None else None,
        "tax_year":       None,
        "zoning":         row.zoning,
        "owner":          row.owner_raw or "",
        "owner_addr":     None, "owner_city": None, "owner_state": None, "owner_zip": None,
        "bedrooms":       None,
        "bathrooms":      None,
        "notes":          None,
        "name1":          row.owner_raw or None,
        "name2":          None,
        "lat":            row.centroid_lat,
        "lng":            row.centroid_lng,
        "county":         row.county,
        "source_county":  row.source_county,
        "sale_price":     float(row.sale_price) if row.sale_price is not None else None,
        "sale_date":      row.sale_date.isoformat() if row.sale_date else None,
        "lot_acres":      float(row.lot_acres) if row.lot_acres is not None else None,
        "usecode":        row.usecode,
        "land_use":       row.land_use,
        # CRM-summary fields — a prospect has none of these (they only exist
        # once a broker actually adds it as a Property); kept as explicit
        # None rather than omitted so both branches of the common dict
        # contract always carry the same keys.
        "asking_price":   None,
        "cap_rate":       None,
        "status":         None,
        "tenant_summary": None,
    }


def _property_row_to_finder_shape(p: Property) -> dict:
    """Shapes an owner-scoped Property row into the same dict contract
    _parcel_from_regrid_row() produces above, so finder.html's renderParcels()/
    openPanel() can treat "yours" and "prospect" results uniformly wherever
    the fields overlap, and branch only where they genuinely differ (see the
    unified-search recon report).

    property_type is set from Property.property_category (already computed
    and stored at every property_type write site — see property_category.py)
    rather than parcel_classcode_to_property_type(): that function's input is
    a raw county classcode, and Property has no such column — it already
    stores its own classification directly in this app's vocabulary, so
    there's nothing to feed the classcode mapper. finder.html aliases the
    one vocabulary mismatch ('Multi-Family' vs the badge system's
    'Multifamily' key) client-side; every other property_category value
    that isn't one of the 4 badge categories already falls back to the
    existing Unclassified badge, same as any prospect parcel type the
    badge system doesn't recognize.

    CRM-summary fields included here are exactly the ones already sitting on
    this row with no extra join/query: asking_price, cap_rate, status
    (always populated, defaults "Active"), and tenant (a single free-text
    occupant field — not the full property_tenants roster, which would need
    a per-property join and isn't "cheap").
    """
    return {
        "source":         "yours",
        "property_id":    p.id,
        "keypin":         None,
        "pin":            None,
        "address":        p.address or "",
        "city":           p.city or "",
        "zip":            p.zip or "",
        "state":          p.state or "MI",
        "property_type":  p.property_category,
        "subtype":        p.subtype or "",
        "sf_rentable":    p.sf_rentable,
        "sf_land":        p.sf_land,
        "bldg_sqft":      p.sf_rentable,
        "num_units":      p.units,
        "year_built":     p.year_built,
        "assessed_value": p.assessed_value,
        "tax_year":       p.tax_year,
        "zoning":         p.zoning,
        "owner":          None,
        "owner_addr":     None, "owner_city": None, "owner_state": None, "owner_zip": None,
        "bedrooms":       None,
        "bathrooms":      None,
        "notes":          p.notes,
        "name1":          None,
        "name2":          None,
        "lat":            p.lat,
        "lng":            p.lng,
        "county":         p.county,
        "source_county":  None,
        "sale_price":     p.last_sale_price,
        "sale_date":      p.last_sale_date.isoformat() if p.last_sale_date else None,
        "lot_acres":      (p.sf_land / 43560.0) if p.sf_land else None,
        "usecode":        None,
        "land_use":       None,
        "asking_price":   p.asking_price,
        "cap_rate":       p.cap_rate,
        "status":         p.status,
        "tenant_summary": p.tenant,
    }


@router.get("/parcels")
def get_parcels(
    zip:                 Optional[str]   = None,
    city:                Optional[str]   = None,
    street:               Optional[str]   = None,
    owner:                Optional[str]   = None,
    assessed_value_min:  Optional[float] = None,
    assessed_value_max:  Optional[float] = None,
    sale_price_min:       Optional[float] = None,
    sale_price_max:       Optional[float] = None,
    lot_acres_min:        Optional[float] = None,
    lot_acres_max:        Optional[float] = None,
    usecode:              Optional[str]   = Query(None, description="Exact match; comma-separated for a list"),
    db:                  Session = Depends(get_db),
    current_user:        User    = Depends(get_current_user),
):
    """Unified Property Finder search: merges the broker's own owner-scoped
    `properties` ("yours") with parcels_regrid prospects ("prospect") into
    one ranked/deduped list. At least one of zip/city/street/owner is
    required — no unfiltered full-table scans over 215K parcels_regrid rows
    (the owner-scoped Property query is cheap regardless, but is gated by
    the same check for consistency).

    Two independent, small, capped queries are shaped into a common dict
    contract (_parcel_from_regrid_row / _property_row_to_finder_shape) and
    merged in Python rather than a SQL UNION — see the unified-search recon
    report: normalize_address() (the dedupe key) is Python-only, the two
    tables' column shapes are too different for a clean UNION, and this
    matches the existing /api/query engine's per-source-shaping pattern.

    Dedup: if a "yours" property and a "prospect" parcel normalize to the
    same address, only the "yours" entry is kept — the prospect is dropped,
    not just dimmed (replaces the old exists_in_db flag entirely).

    Two existing frontend callers hit this route today, both zip-only:
    finder.html's ZIP search, and property.html's "Show Nearby Parcels" Map
    tab toggle (toggleNearby()) — both already treat zip as required, so
    the new "at least one" rule doesn't change their behavior. Neither is
    modified in this change; their results will just now come from
    parcels_regrid's 6-county set instead of Oakland-only.
    """
    zip    = (zip or "").strip() or None
    city   = (city or "").strip() or None
    street = (street or "").strip() or None
    owner  = (owner or "").strip() or None

    if not any([zip, city, street, owner]):
        raise HTTPException(
            status_code=400,
            detail="At least one of zip, city, street, or owner is required.",
        )

    q = db.query(ParcelRegrid)
    if zip:
        q = q.filter(ParcelRegrid.zip == zip)
    if city:
        q = q.filter(ParcelRegrid.city.ilike(f"%{city}%"))
    if street:
        q = q.filter(ParcelRegrid.address.ilike(f"%{street}%"))
    if owner:
        q = q.filter(ParcelRegrid.owner_raw.ilike(f"%{owner}%"))
    if assessed_value_min is not None:
        q = q.filter(ParcelRegrid.assessed_value >= assessed_value_min)
    if assessed_value_max is not None:
        q = q.filter(ParcelRegrid.assessed_value <= assessed_value_max)
    if sale_price_min is not None:
        q = q.filter(ParcelRegrid.sale_price >= sale_price_min)
    if sale_price_max is not None:
        q = q.filter(ParcelRegrid.sale_price <= sale_price_max)
    if lot_acres_min is not None:
        q = q.filter(ParcelRegrid.lot_acres >= lot_acres_min)
    if lot_acres_max is not None:
        q = q.filter(ParcelRegrid.lot_acres <= lot_acres_max)
    if usecode:
        codes = [c.strip() for c in usecode.split(",") if c.strip()]
        if codes:
            q = q.filter(ParcelRegrid.usecode.in_(codes))

    rows = q.limit(MAX_PARCELS_REGRID_RESULTS).all()
    prospects = [_parcel_from_regrid_row(r) for r in rows]

    # ── "Yours" — owner-scoped Property query, same filter params where a
    # compatible field exists on Property; filters with no Property
    # equivalent (owner, usecode) are simply skipped for this query, not
    # treated as errors (owner has no text-name field on Property; usecode
    # is a county tax-classification scheme Property doesn't carry).
    pq = db.query(Property).filter(Property.owner_id == current_user.id)
    if zip:
        pq = pq.filter(Property.zip == zip)
    if city:
        pq = pq.filter(Property.city.ilike(f"%{city}%"))
    if street:
        pq = pq.filter(Property.address.ilike(f"%{street}%"))
    if assessed_value_min is not None:
        pq = pq.filter(Property.assessed_value >= assessed_value_min)
    if assessed_value_max is not None:
        pq = pq.filter(Property.assessed_value <= assessed_value_max)
    if sale_price_min is not None:
        pq = pq.filter(Property.last_sale_price >= sale_price_min)
    if sale_price_max is not None:
        pq = pq.filter(Property.last_sale_price <= sale_price_max)
    if lot_acres_min is not None:
        pq = pq.filter(Property.sf_land / 43560.0 >= lot_acres_min)
    if lot_acres_max is not None:
        pq = pq.filter(Property.sf_land / 43560.0 <= lot_acres_max)

    my_properties = pq.limit(MAX_PARCELS_REGRID_RESULTS).all()
    yours = []
    for p in my_properties:
        shaped = _property_row_to_finder_shape(p)
        # Live Regrid enrichment — restores the assessed_value/sale_price/
        # usecode/etc. a "yours" pin used to show back when it was just a
        # dimmed parcels_regrid pin (see the unified-search recon report's
        # FIX 1). Reuses get_public_record()'s exact matching logic via
        # _match_parcel_regrid_for_property() rather than a second
        # implementation. Omitted entirely (not fabricated as nulls) when
        # no match exists — a real, confirmable gap (e.g. this address
        # isn't ingested yet), not an error.
        match, _ = _match_parcel_regrid_for_property(db, p)
        if match is not None:
            shaped["public_record"] = _public_record_subobject(match)
        yours.append(shaped)
    yours_missing_coords = sum(1 for y in yours if not (y["lat"] and y["lng"]))

    # Per-user address set for dedup — deliberately UNFILTERED (every one of
    # the broker's properties, regardless of the filters above) so a prospect
    # is correctly dropped even if the matching "yours" property happens to
    # fall outside this particular search's price/size range and therefore
    # isn't itself in `yours`. Reuses normalize_address() exactly as
    # get_public_record() and services/regrid.py's reconcile() already do —
    # no second normalizer.
    my_addresses = {
        normalize_address(a) for (a,) in
        db.query(Property.address)
        .filter(Property.owner_id == current_user.id, Property.address.isnot(None))
        .all()
        if a
    }
    prospects = [
        p for p in prospects
        if not (p["address"] and normalize_address(p["address"]) in my_addresses)
    ]

    parcels = yours + prospects

    return {
        "parcels":              parcels,
        "total":                len(parcels),
        "yours_total":          len(yours),
        "prospect_total":       len(prospects),
        "yours_missing_coords": yours_missing_coords,
        "zip":                  zip,
        "source":               "parcels_regrid+properties",
    }


@router.get("/parcels/search")
def search_parcels(
    q:            str     = "",
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Lightweight typeahead over the local parcels table — shared reference
    data (Option A), no owner_id scoping."""
    q = q.strip()
    if len(q) < 2:
        return []
    try:
        rows = db.execute(
            text("SELECT keypin, siteaddress, sitecity, sitezip5, classcode,"
                 " assessedvalue, living_area_sqft FROM parcels"
                 " WHERE siteaddress ILIKE :q OR keypin ILIKE :q"
                 " LIMIT 10"),
            {"q": f"%{q}%"},
        ).fetchall()
    except Exception:
        return []
    return [{
        "keypin":           r.keypin,
        "siteaddress":      r.siteaddress,
        "sitecity":         r.sitecity,
        "sitezip5":         r.sitezip5,
        "classcode":        r.classcode,
        "assessedvalue":    float(r.assessedvalue) if r.assessedvalue is not None else None,
        "living_area_sqft": float(r.living_area_sqft) if r.living_area_sqft is not None else None,
    } for r in rows]


@router.get("/parcel/{keypin}")
def get_parcel_by_keypin(
    keypin:       str,
    property_id:  Optional[int] = Query(None),
    db:           Session       = Depends(get_db),
    current_user: User          = Depends(get_current_user),
):
    """3-step parcel lookup: exact keypin → stripped keypin → address fallback."""
    def _serialize(row) -> dict:
        return {
            "name1":             row.name1,
            "name2":             row.name2,
            "cvttaxdescription": row.cvttaxdescription,
            "classcode":         row.classcode,
            "assessedvalue":     row.assessedvalue,
            "taxablevalue":      row.taxablevalue,
            "living_area_sqft":  row.living_area_sqft,
            "shapearea":         row.shapearea,
        }

    COLS = ("SELECT name1, name2, cvttaxdescription, classcode,"
            " assessedvalue, taxablevalue, living_area_sqft, shapearea"
            " FROM parcels")
    try:
        # Step 1 — exact keypin match
        row = db.execute(text(f"{COLS} WHERE keypin = :k"), {"k": keypin}).fetchone()
        if row:
            return _serialize(row)

        # Step 2 — normalise both sides (remove dashes/spaces) and retry
        # Always runs: handles DB-has-dashes/input-doesn't and vice-versa
        stripped = keypin.replace("-", "").replace(" ", "")
        row = db.execute(
            text(f"{COLS} WHERE REPLACE(REPLACE(keypin,'-',''),' ','') = :k"),
            {"k": stripped},
        ).fetchone()
        if row:
            return _serialize(row)

        # Step 3 — address fallback via property record
        if property_id:
            prop = db.query(Property).filter(
                Property.id       == property_id,
                Property.owner_id == current_user.id,
            ).first()
            if prop and prop.address:
                if prop.zip:
                    row = db.execute(
                        text(f"{COLS} WHERE siteaddress ILIKE :addr AND sitezip5 = :zip LIMIT 1"),
                        {"addr": prop.address + "%", "zip": prop.zip},
                    ).fetchone()
                else:
                    row = db.execute(
                        text(f"{COLS} WHERE siteaddress ILIKE :addr LIMIT 1"),
                        {"addr": prop.address + "%"},
                    ).fetchone()
                if row:
                    return _serialize(row)

    except Exception:
        return {}   # parcels table not available yet

    raise HTTPException(status_code=404, detail="Parcel not found")


def _property_source_county(prop: Property) -> Optional[str]:
    """Maps a property's free-text county to the parcels_regrid.source_county
    value it would have been ingested under. Returns None if property.county
    is blank -- callers should fall back to an unscoped query in that case,
    same as before this scoping was added. property.county is inconsistently
    populated in practice (confirmed 2026-07-02: 2 of 5 sampled Oakland
    properties had county=None despite matching correctly), so requiring it
    would silently regress those matches rather than protect them.

    Wayne County's own assessor and the City of Detroit's assessor are two
    separate Regrid exports (source_county 'wayne' vs 'wayne_detroit' -- see
    CLAUDE.md's PARCELS_REGRID section) even though both are "Wayne County"
    from the property's point of view, so county name alone isn't enough
    for Wayne -- city is also checked.
    """
    if not prop.county:
        return None
    base = prop.county.strip().lower()
    if base.endswith(" county"):
        base = base[: -len(" county")].strip()
    if not base:
        return None
    if base == "wayne" and (prop.city or "").strip().lower() == "detroit":
        return "wayne_detroit"
    return base


def _match_parcel_regrid_for_property(db: Session, prop: Property):
    """The exact match order/scoping get_public_record() uses: opportunistic
    parcel_id match, then zip-scoped normalize_address() exact match, both
    scoped to the property's own source_county (via _property_source_county())
    when known. Extracted out of get_public_record() so the unified Property
    Finder merge (get_parcels() below) can attach live Regrid enrichment to a
    "yours" result without a second implementation of this matching logic —
    same reasoning that already governs normalize_address() itself living in
    services/naming.py instead of being copied per-caller.

    Returns (ParcelRegrid | None, matched_via | None), matched_via being
    "parcel_id" or "address" — get_public_record() surfaces that in its
    response; get_parcels() only cares whether a match exists.

    Known accepted cost: called once per "yours" result in get_parcels(),
    same nested-query-per-row tradeoff scan_duplicates()/reconcile() already
    accept elsewhere in this app (see their docstrings) — fine at the scale
    of one broker's own filtered result set, not re-optimized here.
    """
    source_county = _property_source_county(prop)
    match, matched_via = None, None

    if prop.parcel_id:
        q = db.query(ParcelRegrid).filter(ParcelRegrid.parcel_id == prop.parcel_id)
        if source_county:
            q = q.filter(ParcelRegrid.source_county == source_county)
        match = q.first()
        if match:
            matched_via = "parcel_id"

    if match is None and prop.zip and prop.address:
        target_norm = normalize_address(prop.address)
        q = db.query(ParcelRegrid).filter(ParcelRegrid.zip == prop.zip)
        if source_county:
            q = q.filter(ParcelRegrid.source_county == source_county)
        for cand in q.all():
            if cand.address and normalize_address(cand.address) == target_norm:
                match, matched_via = cand, "address"
                break

    return match, matched_via


def _public_record_subobject(match: ParcelRegrid) -> dict:
    """Regrid-sourced enrichment fields for the unified Finder's "yours"
    panel — a compact subset of ParcelRegrid's own columns for the map
    panel, distinct from get_public_record()'s response shape (that
    endpoint serves the full property detail page's Public Record tab, a
    richer, separate UI surface with its own already-established field
    set). Only called when a match exists — no zero/empty fabrication for
    the no-match case, that's handled by simply not attaching this
    sub-object at all (see get_parcels() below).
    """
    return {
        "assessed_value": float(match.assessed_value) if match.assessed_value is not None else None,
        "sale_price":     float(match.sale_price) if match.sale_price is not None else None,
        "sale_date":      match.sale_date.isoformat() if match.sale_date else None,
        "usecode":        match.usecode,
        "usedesc":        match.usedesc,
        "lot_acres":      float(match.lot_acres) if match.lot_acres is not None else None,
        "zoning":         match.zoning,
    }


@router.get("/public-record/{property_id}")
def get_public_record(
    property_id:  int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Public Record tab data source. parcels_regrid first (it has the
    owner name — Oakland ArcGIS strips NAME1/NAME2 from its public feed,
    Regrid doesn't), live ArcGIS/local-parcels as fallback for counties
    parcels_regrid doesn't cover yet (e.g. Macomb, not ingested — see
    CLAUDE.md's PARCELS_REGRID / REGRID OAKLAND PILOT sections).
    Read-only against parcels_regrid — no writes here.

    Match order:
      1. property.parcel_id == parcels_regrid.parcel_id, opportunistic.
         Oakland ArcGIS's "keypin" and Regrid's "parcelnumb" are different
         source ID schemes, not assumed equivalent — free to try first,
         not relied on.
      2. zip-scoped normalize_address() exact match — the same function
         services/regrid.py's reconcile() already uses in production to
         link parcels_regrid rows to properties, run here in the opposite
         direction (property → parcel instead of parcel → property).
      3. legacy local-parcels/ArcGIS 3-step lookup (get_parcel_by_keypin,
         above), only possible if property.parcel_id is already set from
         a prior manual attach — unchanged behavior for counties not yet
         in parcels_regrid.

    Both parcels_regrid queries are scoped to the property's own
    source_county (via _property_source_county()) when known, so a
    zip+address collision can't match a different county's parcel. When
    property.county is blank, the query is unscoped (same as before this
    was added) rather than silently excluding otherwise-valid matches.

    EXTENDED (2026-07-06) — also merges in _public_record_subobject()
    (assessed_value, sale_price, sale_date, usecode, usedesc, lot_acres,
    zoning), the same enrichment already built for Property Finder's
    "yours" pins, reusing the same matched row rather than re-querying.
    Plus bldg_sqft (via the shared _bldg_sqft_from_raw_data() extraction),
    surfaced as its own field specifically so the frontend can label it
    "Building SF (Public Record)" and NOT silently equate it with
    Property.sf_rentable — bldg_sqft is a general Regrid building-SF
    concept, sf_rentable is a commercial-leasing concept; these are not
    guaranteed to mean the same measurement. Plus derived_property_type
    (via the shared _derive_property_type_for_parcel() branching), this
    app's CRE vocabulary derived from usecode/usedesc, for the "Class/Type"
    accept affordance. This is the field-sync
    feature's data source — see CLAUDE.md's PARCELS_REGRID section for
    the accept-action design built on top of it.
    """
    prop = db.query(Property).filter(
        Property.id == property_id, Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    match, matched_via = _match_parcel_regrid_for_property(db, prop)

    if match is not None:
        return {
            "source":        "parcels_regrid",
            "matched_via":   matched_via,
            "owner":         match.owner_raw,
            "parcel_id":     match.parcel_id,
            "address":       match.address,
            "city":          match.city,
            "state":         match.state,
            "zip":           match.zip,
            "county":        match.county,
            "source_county": match.source_county,
            "ingested_at":   match.ingested_at.isoformat() if match.ingested_at else None,
            "bldg_sqft":     _bldg_sqft_from_raw_data(match.raw_data or {}),
            "derived_property_type": _derive_property_type_for_parcel(match),
            **_public_record_subobject(match),
        }

    # ── Fallback: legacy local-parcels/ArcGIS path — only reachable if the
    # property already has a keypin from a prior manual attach; parcels_regrid
    # has no coverage for this county yet (e.g. Macomb).
    if prop.parcel_id:
        try:
            legacy = get_parcel_by_keypin(
                keypin=prop.parcel_id, property_id=property_id,
                db=db, current_user=current_user,
            )
        except HTTPException:
            legacy = None
        if legacy:
            owner = (legacy.get("name1") or "").strip()
            if legacy.get("name2"):
                owner = f"{owner} / {legacy['name2']}".strip(" /")
            return {
                "source":        "arcgis_legacy",
                "matched_via":   "parcel_id",
                "owner":         owner or None,
                "parcel_id":     prop.parcel_id,
                "address":       prop.address,
                "city":          prop.city,
                "state":         prop.state,
                "zip":           prop.zip,
                "county":        legacy.get("cvttaxdescription"),
                "source_county": None,
                "ingested_at":   None,
            }

    return {"source": None, "matched_via": None}


def _log_public_record_sync(db: Session, owner_id: int, property_id: int,
                             field_label: str, old_value, new_value):
    """Reuses the existing Activity model/table (routers/activities.py's
    create_activity() constructs the exact same Activity(...) shape) rather
    than adding a new audit column — see the field-sync recon report for
    why: updated_at is a whole-row timestamp that fires for any change for
    any reason, so it can't answer "was this field synced from Public
    Record, and when." A dedicated 'last synced' column would also only
    ever remember the most recent sync; an Activity row naturally keeps
    history, and property.html already renders an Activity feed on the
    same page — no new UI surface needed."""
    old_display = old_value if old_value not in (None, "") else "—"
    new_display = new_value if new_value not in (None, "") else "—"
    db.add(Activity(
        owner_id=owner_id,
        property_id=property_id,
        activity_type="public_record_sync",
        subject=f"Public Record sync — {field_label}",
        notes=f"{field_label} updated from Public Record: {old_display} → {new_display}",
        activity_date=datetime.now(timezone.utc),
    ))


@router.post("/public-record/{property_id}/accept-owner")
def accept_public_record_owner(
    property_id:  int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """"Use this" owner-accept action from the Public Record tab — direct
    correction, no confirmation step (per the field-sync design: this is
    the one field where a plain scalar PUT can't work, since
    recorded_owner_account_id is an Account relationship, not a text
    field; see create_and_link_account_from_parcel_owner() in
    services/regrid.py for why this reuses create_account_from_suggestion()/
    _apply_auto_link()'s exact mechanics rather than a second
    account-resolution implementation).
    """
    prop = db.query(Property).filter(
        Property.id == property_id, Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    match, _ = _match_parcel_regrid_for_property(db, prop)
    if match is None or not match.owner_raw:
        raise HTTPException(status_code=400, detail="No Public Record owner available to accept")

    old_owner_name = None
    if prop.recorded_owner_account_id:
        old_account = db.query(Account).filter(Account.id == prop.recorded_owner_account_id).first()
        old_owner_name = old_account.name if old_account else None

    result = create_and_link_account_from_parcel_owner(db, current_user.id, match, prop)

    _log_public_record_sync(db, current_user.id, property_id, "Recorded Owner",
                             old_owner_name, result["account_name"])
    db.commit()

    return result


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
