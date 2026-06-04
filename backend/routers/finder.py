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

MAX_PARCELS      = 500
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
    """
    Oakland County CLASSCODE field — first digit indicates class.
    Codes starting with 1xx = residential → skip.
    """
    if not code:
        return None
    s = str(code).strip()
    try:
        c = int(s)
    except (TypeError, ValueError):
        return None
    if 100 <= c <= 199: return None          # residential — skip
    if 200 <= c <= 299: return "Retail"      # commercial
    if 300 <= c <= 399: return "Industrial"
    if 400 <= c <= 699: return "Land"
    if 700 <= c <= 799: return "Land"
    if 800 <= c <= 899: return "Land"
    return None


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

    # SF: LIVING_AREA_SQFT is residential; Shape__Area is parcel footprint (sq ft) for commercial
    sf_raw  = attrs.get("LIVING_AREA_SQFT")
    sf_area = attrs.get("Shape__Area") or attrs.get("Shape_Area")
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
    """Return CRE parcels for a zip code with per-user exists_in_db flag."""
    cache_key = f"{CACHE_ZIP_PREFIX}{zip}"

    # Check parcel cache
    cached_parcels = _get_or_set_cache(db, "parcels_v2_by_zip", cache_key, ZIP_TTL_DAYS)

    if not cached_parcels:
        layer_url = OAKLAND_PARCELS_URL

        # Confirmed field names from live Oakland MapServer response
        params = urllib.parse.urlencode({
            "where":             f"SITEZIP5='{zip}'",
            "outFields":         ("KEYPIN,PIN,SITEADDRESS,SITECITY,SITESTATE,SITEZIP5,"
                                  "NAME1,NAME2,CLASSCODE,CVTTAXDESCRIPTION,"
                                  "ASSESSEDVALUE,TAXABLEVALUE,"
                                  "LIVING_AREA_SQFT,Shape__Area,"
                                  "NUM_BEDS,NUM_BATHS,STRUCTURE_DESC"),
            "returnGeometry":    "true",
            "geometryPrecision": "4",
            "resultRecordCount": MAX_PARCELS,
            "f":                 "json",
        })
        url = f"{layer_url}/query?{params}"

        try:
            data = _get(url)
        except Exception as primary_exc:
            # Walk remaining candidates until one succeeds
            data = None
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

        features   = data.get("features", [])
        parcels    = []
        first_feat = True   # debug fields on first accepted parcel only
        # Log raw keys from very first feature to confirm field names
        if features:
            import logging
            logging.getLogger("upfront").info(
                "Oakland first feature attrs keys: %s | NAME1=%r Shape__Area=%r",
                list((features[0].get("attributes") or {}).keys()),
                (features[0].get("attributes") or {}).get("NAME1"),
                (features[0].get("attributes") or {}).get("Shape__Area"),
            )
        for feat in features:
            attrs = feat.get("attributes") or {}
            # Skip residential: CLASSCODE 1xx OR NUM_BEDS > 0
            classcode = attrs.get("CLASSCODE")
            num_beds  = attrs.get("NUM_BEDS")
            if num_beds and float(num_beds) > 0:
                continue
            prop_type = _classcode_to_type(classcode)
            if prop_type is None:
                continue   # skip unclassified / residential
            p = _parcel_from_attrs(attrs)

            geometry = feat.get("geometry")
            p["lat"], p["lng"] = _centroid(geometry)
            if p["lat"] is None:
                continue   # skip parcels with no geometry

            # ── TEMPORARY: attach raw geometry debug to first accepted parcel ──
            if first_feat:
                first_feat = False
                rings = (geometry or {}).get("rings", [])
                raw_pts = rings[0][:3] if rings else []   # first 3 pts of outer ring
                centroid_x = sum(pt[0] for pt in rings[0]) / len(rings[0]) if rings else None
                centroid_y = sum(pt[1] for pt in rings[0]) / len(rings[0]) if rings else None
                p["debug_geo"] = {
                    "geometry_type": (geometry or {}).get("type"),
                    "ring_count":    len(rings),
                    "outer_ring_pts": len(rings[0]) if rings else 0,
                    "first_3_raw_pts": raw_pts,
                    "centroid_raw_x": centroid_x,
                    "centroid_raw_y": centroid_y,
                    "converted_lat":  p["lat"],
                    "converted_lng":  p["lng"],
                    "spatial_ref":    (geometry or {}).get("spatialReference"),
                }
            # ── END TEMPORARY ─────────────────────────────────────────────────

            parcels.append(p)

        cached_parcels = {"parcels": parcels, "total": len(parcels), "zip": zip,
                          "layer_url": OAKLAND_PARCELS_URL}
        _save_cache(db, "parcels_v2_by_zip", cache_key, "Oakland_ArcGIS",
                    cached_parcels, ZIP_TTL_DAYS)

    # Overlay per-user exists_in_db
    parcels     = cached_parcels.get("parcels", [])
    my_keypins  = {
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
        "zip":       cached_parcels.get("zip", zip),
        "layer_url": cached_parcels.get("layer_url", ""),
        "cached":    True,
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
