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

@router.get("/test")
def test_layer(current_user: User = Depends(get_current_user)):
    """
    Probe all OAKLAND_CANDIDATES — returns layer info + minimal query result
    for each URL so we can identify which one is live.
    """
    results = {}
    for url in OAKLAND_CANDIDATES:
        entry: dict = {"url": url}

        # Layer info
        try:
            data = _get(f"{url}?f=json")
            entry["layer_info"] = {
                "ok":       "error" not in data,
                "name":     data.get("name"),
                "geomType": data.get("geometryType"),
                "fields":   [f["name"] for f in data.get("fields", [])[:25]],
                "error":    data.get("error"),
            }
        except Exception as exc:
            entry["layer_info"] = {"ok": False, "error": str(exc)}

        # Minimal query (only if layer info succeeded)
        if entry["layer_info"].get("ok"):
            query_url = (
                f"{url}/query?where=1%3D1"
                "&resultRecordCount=1&outFields=*&returnGeometry=false&f=json"
            )
            try:
                qdata     = _get(query_url)
                features  = qdata.get("features", [])
                entry["query"] = {
                    "ok":          "error" not in qdata,
                    "count":       len(features),
                    "sample_keys": list(features[0].get("attributes", {}).keys())[:20] if features else [],
                    "error":       qdata.get("error"),
                }
            except Exception as exc:
                entry["query"] = {"ok": False, "error": str(exc)}
        else:
            entry["query"] = {"ok": False, "skipped": True}

        results[url] = entry

    return results


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
    cached_parcels = _get_or_set_cache(db, "parcels_by_zip", cache_key, ZIP_TTL_DAYS)

    if not cached_parcels:
        layer_url = OAKLAND_PARCELS_URL

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
                          "layer_url": OAKLAND_PARCELS_URL}
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
