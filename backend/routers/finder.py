"""
Property Finder — Oakland County ArcGIS parcel discovery.

GET  /api/finder/discover          → find + cache the current parcel layer URL
GET  /api/finder/parcels?zip=      → CRE parcels for a zip, with exists_in_db flag
POST /api/finder/add               → create Property (+ optional Deal) from parcel data
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

ARCGIS_SERVICES = "https://gis.oakgov.com/arcgis/rest/services"
MAX_PARCELS     = 500

# Candidate layer names to try during discovery (most likely first)
LAYER_CANDIDATES = [
    "Parcels_and_Zoning/Oakland_County_Parcels",
    "Property/Parcels",
    "BaseMap/Parcels",
    "Parcels/Parcels",
]

CACHE_LAYER_KEY   = "oakland_parcel_layer"
CACHE_ZIP_PREFIX  = "oakland_zip_"
LAYER_TTL_DAYS    = 90
ZIP_TTL_DAYS      = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "UpFrontBroker/1.0 (credetroit@gmail.com)"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _propclass_to_type(code) -> Optional[str]:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    if 100 <= c <= 199: return None          # residential — skip
    if 200 <= c <= 299: return "Retail"      # commercial (refine with PROPCLASSDESC)
    if 300 <= c <= 399: return "Industrial"
    if 400 <= c <= 699: return "Land"
    if 700 <= c <= 799: return "Land"
    if 800 <= c <= 899: return "Land"
    return None


def _centroid(geometry) -> tuple[Optional[float], Optional[float]]:
    """Return (lat, lng) centroid from an ESRI polygon geometry dict."""
    if not geometry:
        return None, None
    rings = geometry.get("rings", [])
    if not rings:
        return None, None
    pts = rings[0]   # outer ring
    if not pts:
        return None, None
    lngs = [p[0] for p in pts]
    lats  = [p[1] for p in pts]
    return round(sum(lats) / len(lats), 6), round(sum(lngs) / len(lngs), 6)


def _parcel_from_attrs(attrs: dict) -> dict:
    """Transform raw ArcGIS attribute dict into our parcel shape."""
    prop_type = _propclass_to_type(attrs.get("PROPCLASS"))
    city = attrs.get("SITUSCITY") or attrs.get("MUNICIPALITY") or ""
    assessed = (
        attrs.get("TAXABLEVALUE")
        or attrs.get("ASSESSEDVALUE")
        or attrs.get("SEV")
    )
    sf_rentable = attrs.get("SQFEET")
    acres       = attrs.get("TOTALACRES")
    sf_land     = round(float(acres) * 43560, 0) if acres else None

    owner = attrs.get("OWNERNAME1") or ""
    if attrs.get("OWNERNAME2"):
        owner = f"{owner} / {attrs['OWNERNAME2']}".strip(" /")

    notes_parts = []
    if attrs.get("SCHOOLDIST"):
        notes_parts.append(f"School District: {attrs['SCHOOLDIST']}")

    return {
        "keypin":          attrs.get("KEYPIN") or attrs.get("keypin"),
        "address":         attrs.get("SITUSADDR") or "",
        "city":            city.title(),
        "zip":             attrs.get("SITUSZIP") or "",
        "state":           "MI",
        "property_type":   prop_type,
        "subtype":         attrs.get("PROPCLASSDESC") or "",
        "sf_rentable":     float(sf_rentable) if sf_rentable else None,
        "sf_land":         sf_land,
        "year_built":      int(attrs["YEARBUILT"]) if attrs.get("YEARBUILT") else None,
        "assessed_value":  float(assessed) if assessed else None,
        "tax_year":        int(attrs["TAXYEAR"]) if attrs.get("TAXYEAR") else None,
        "zoning":          attrs.get("ZONING") or "",
        "owner":           owner,
        "owner_addr":      attrs.get("OWNERADDR") or "",
        "owner_city":      attrs.get("OWNERCITY") or "",
        "owner_state":     attrs.get("OWNERSTATE") or "",
        "owner_zip":       attrs.get("OWNERZIP") or "",
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

@router.get("/discover")
def discover_layer(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Find the current Oakland County parcel FeatureServer layer URL."""
    cached = _get_or_set_cache(db, "arcgis_layer", CACHE_LAYER_KEY, LAYER_TTL_DAYS)
    if cached:
        return cached

    # Query the services directory
    try:
        directory = _get(f"{ARCGIS_SERVICES}?f=json")
    except Exception as exc:
        raise HTTPException(503, f"OakGov ArcGIS unreachable: {exc}")

    services = directory.get("services", []) + directory.get("folders", [])

    # Try to find a FeatureServer with "Parcel" in the name
    found_url = None
    for svc in services:
        name = svc.get("name", "")
        stype = svc.get("type", "")
        if stype == "FeatureServer" and "parcel" in name.lower():
            found_url = f"{ARCGIS_SERVICES}/{name}/FeatureServer/0"
            break

    # Fall back to known candidate paths
    if not found_url:
        for candidate in LAYER_CANDIDATES:
            test_url = f"{ARCGIS_SERVICES}/{candidate}/FeatureServer/0?f=json"
            try:
                result = _get(test_url)
                if "fields" in result or "name" in result:
                    found_url = f"{ARCGIS_SERVICES}/{candidate}/FeatureServer/0"
                    break
            except Exception:
                continue

    if not found_url:
        raise HTTPException(404, "Could not locate Oakland County parcel layer. "
                            "Check https://gis.oakgov.com/arcgis/rest/services manually.")

    result = {"layer_url": found_url}
    _save_cache(db, "arcgis_layer", CACHE_LAYER_KEY, "Oakland_ArcGIS",
                result, LAYER_TTL_DAYS)
    return result


@router.get("/parcels")
def get_parcels(
    zip:          str     = Query(..., min_length=5, max_length=5),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Return CRE parcels for a zip code with per-user exists_in_db flag."""
    cache_key = f"{CACHE_ZIP_PREFIX}{zip}"

    # Check parcel cache
    cached_parcels = _get_or_set_cache(db, "parcels_by_zip", cache_key, ZIP_TTL_DAYS)

    if not cached_parcels:
        # Discover or load layer URL
        layer_cache = _get_or_set_cache(db, "arcgis_layer", CACHE_LAYER_KEY, LAYER_TTL_DAYS)
        if layer_cache:
            layer_url = layer_cache["layer_url"]
        else:
            # Quick attempt with first candidate
            layer_url = (f"{ARCGIS_SERVICES}/{LAYER_CANDIDATES[0]}/FeatureServer/0")

        params = urllib.parse.urlencode({
            "where":             f"SITUSZIP='{zip}'",
            "outFields":         ("KEYPIN,SITUSADDR,SITUSCITY,SITUSZIP,PROPCLASS,"
                                  "PROPCLASSDESC,SQFEET,TOTALACRES,YEARBUILT,"
                                  "TAXYEAR,TAXABLEVALUE,ASSESSEDVALUE,SEV,"
                                  "ZONING,SCHOOLDIST,MUNICIPALITY,"
                                  "OWNERNAME1,OWNERNAME2,OWNERADDR,"
                                  "OWNERCITY,OWNERSTATE,OWNERZIP"),
            "returnGeometry":    "true",
            "geometryPrecision": "4",
            "resultRecordCount": MAX_PARCELS,
            "orderByFields":     "SQFEET DESC",
            "f":                 "json",
        })
        url = f"{layer_url}/query?{params}"

        try:
            data = _get(url)
        except Exception as exc:
            raise HTTPException(503, f"ArcGIS request failed: {exc}")

        if "error" in data:
            raise HTTPException(502, f"ArcGIS error: {data['error'].get('message','unknown')}")

        features = data.get("features", [])
        parcels  = []
        for feat in features:
            attrs = feat.get("attributes") or {}
            prop_type = _propclass_to_type(attrs.get("PROPCLASS"))
            if prop_type is None:
                continue   # skip residential
            p = _parcel_from_attrs(attrs)
            p["lat"], p["lng"] = _centroid(feat.get("geometry"))
            if p["lat"] is None:
                continue   # skip parcels with no geometry
            parcels.append(p)

        cached_parcels = {"parcels": parcels, "total": len(parcels), "zip": zip,
                          "layer_url": layer_url}
        _save_cache(db, "parcels_by_zip", cache_key, "Oakland_ArcGIS",
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
