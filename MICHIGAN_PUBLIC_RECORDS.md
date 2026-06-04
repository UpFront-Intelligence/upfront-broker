# Michigan Public Records — 5-County Data Source Strategy

Used by the "Enrich from Public Records" feature in `properties.html`.
Implementation lives (or will live) in `backend/routers/enrichment.py`.

---

## County Routing

| County | Source | Mechanism | Coverage |
|---|---|---|---|
| Oakland | ArcGIS REST API | HTTP GET, JSON | Full county parcel layer |
| Macomb | ArcGIS REST API | HTTP GET, JSON | Full county parcel layer |
| Wayne | BS&A Online | HTML scrape | Per-municipality routing |
| Livingston | BS&A Online | HTML scrape | Per-municipality routing |
| Washtenaw | BS&A Online | HTML scrape | Per-municipality routing |

Routing key: `property.city` + `property.state == "MI"`.  
City → county lookup table is at the bottom of this file.

---

## Oakland County — ArcGIS REST API

**Portal:** https://www.oakgov.com/maps  
**ArcGIS services directory:** `https://gis.oakgov.com/arcgis/rest/services/`

### Confirmed parcel MapServer endpoint

```
https://gisservices.oakgov.com/arcgis/rest/services/Enterprise/EnterpriseOpenParcelDataMapService/MapServer/1
```

**Note:** this is a **MapServer** layer, not a FeatureServer.
All query URLs use `/MapServer/1/query` — not `/FeatureServer/0/query`.

Hardcoded in `routers/finder.py` as `OAKLAND_PARCELS_URL`.

### Parcel query by ZIP (Property Finder)
```
GET {base}/query
  ?where=SITUSZIP='48304'
  &outFields=*
  &returnGeometry=true
  &f=json
```

### Parcel query by KEYPIN (Enrichment)
```
GET {base}/query
  ?where=KEYPIN='{parcel_id}'
  &outFields=*
  &f=json
```

### Fallback by situs address
```
GET {base}/query
  ?where=SITUSADDR+LIKE+'{street}%25'+AND+SITUSCITY='{city}'
  &outFields=*
  &resultRecordCount=5
  &f=json
```

### Field mapping — Oakland MapServer → Property model (CONFIRMED)

Fields confirmed from live API response (`/api/finder/test`).

| Oakland field | Property model field | Notes |
|---|---|---|
| `KEYPIN` | `parcel_id` | Primary parcel ID |
| `PIN` | `parcel_id` (alt) | Alternate parcel ID |
| `SITEADDRESS` | `address` | Situs street address |
| `SITECITY` | `city` | |
| `SITESTATE` | `state` | |
| `SITEZIP5` | `zip` | **Use this for WHERE filter, not SITUSZIP** |
| `NAME1` | `account.name` | Primary owner entity |
| `NAME2` | `account.name` | Secondary owner (append to NAME1) |
| `CLASSCODE` | `property_type` | Integer code — see CLASSCODE table below |
| `CVTTAXDESCRIPTION` | `notes` / city fallback | Municipality description |
| `ASSESSEDVALUE` | `assessed_value` | Assessed value |
| `TAXABLEVALUE` | `assessed_value` (alt) | Taxable value |
| `LIVING_AREA_SQFT` | `sf_rentable` | Building living area SF |
| `NUM_BEDS` | `bedrooms` | Use to filter residential (> 0 = residential) |
| `NUM_BATHS` | `bathrooms` | |
| `STRUCTURE_DESC` | `subtype` / `notes` | Structure description |

### Residential filter

Skip a parcel if **either** condition is true:
- `NUM_BEDS > 0` (has bedrooms → residential)
- `CLASSCODE` 100–199 (residential class code)

### CLASSCODE code → property_type mapping

| Code range | Meaning | Maps to |
|---|---|---|
| 101–199 | Residential | **Skip** — out of scope for CRE v1 |
| 200–299 | Commercial | `"Office"` or `"Retail"` (use `PROPCLASSDESC` to disambiguate) |
| 300–399 | Industrial | `"Industrial"` |
| 400–499 | Residential Vacant Land | `"Land"` |
| 500–599 | Commercial Vacant Land | `"Land"` |
| 600–699 | Industrial Vacant Land | `"Industrial"` |
| 700–799 | Developmental | `"Land"` |
| 800–899 | Agricultural | `"Land"` |

```python
def propclass_to_type(code: int) -> str | None:
    if 200 <= code <= 299: return "Retail"   # refine with PROPCLASSDESC
    if 300 <= code <= 399: return "Industrial"
    if 400 <= code <= 699: return "Land"
    if 700 <= code <= 799: return "Land"
    if 800 <= code <= 899: return "Land"
    return None  # residential or unknown — skip
```

### /api/finder/discover endpoint

Queries the OakGov services directory to locate the current parcel layer path.
Required because OakGov has restructured their services tree in the past.

```python
GET https://gis.oakgov.com/arcgis/rest/services?f=json
# Walk response["services"] for an item where:
#   "type" == "FeatureServer" and "name" contains "Parcel" or "Property"
# Return the full URL of the matching layer
```

Route: `GET /api/finder/discover`  
Caches the result in `ENRICHMENT_CACHE` with `lookup_type="arcgis_layer"`,
`lookup_key="oakland_parcel"`, TTL = 90 days (see Data Privacy Architecture).

---

## Macomb County — ArcGIS REST API

**Portal:** https://www.macombcountymi.gov/GIS  
**ArcGIS base (verify):** `https://gis.macombcountymi.gov/arcgis/rest/services/`

### Parcel query endpoint
```
GET {base}/Parcels/MapServer/0/query
  ?where=PARCEL_ID+%3D+%27{parcel_id}%27
  &outFields=*
  &f=json
```

### Field mapping (Macomb → Property model)

| ArcGIS field | Property model field | Notes |
|---|---|---|
| `PARCEL_ID` | `parcel_id` | Note underscore vs. Oakland's no-underscore |
| `SEV` | `assessed_value` | |
| `TAXES` | `tax_amount` | May be split summer/winter |
| `YEAR_BUILT` | `year_built` | |
| `BLDG_SQ_FT` | `sf_rentable` | |
| `LAND_SQ_FT` | `sf_land` | |
| `OWNER_NAME` | — | Contact linking |
| `LEGAL_DESC` | `legal_desc` | |

> **Verify before coding:** Macomb's ArcGIS field names differ slightly from
> Oakland. Confirm by querying `{base}/Parcels/MapServer/0?f=json`.

---

## Wayne County — BS&A Online

Wayne County has no single county-level ArcGIS parcel API. Assessment data
is managed at the municipal level. Most municipalities use BS&A Online.

**BS&A portal:** https://www.bsaonline.com  
**Parcel search URL:**
```
https://www.bsaonline.com/SiteSearch/SiteSearchDetails
  ?SiteCode={SITE_CODE}
  &SearchType=PRNT
  &ParcelNumber={parcel_id}
  &AssessmentYear={year}
  &Chkvar=true
```

**Address search URL (fallback):**
```
https://www.bsaonline.com/SiteSearch/SiteSearchDetails
  ?SiteCode={SITE_CODE}
  &SearchType=ADDR
  &SearchItem1={street_number}
  &SearchItem2={street_name}
  &AssessmentYear={year}
  &Chkvar=true
```

### Wayne County municipality SiteCodes (verify each — BS&A updates these)

| City / Township | SiteCode |
|---|---|
| Detroit | DETMI |
| Dearborn | DBNMI |
| Dearborn Heights | DBHMI |
| Livonia | LIVMI |
| Westland | WSTMI |
| Garden City | GCYMI |
| Redford Township | RDFMI |
| Canton Township | CNTMI |
| Plymouth Township | PLYMI |
| Northville Township | NVTMI |
| Romulus | ROMMI |
| Taylor | TLYmi |
| Allen Park | ALPMI |
| Lincoln Park | LNPMI |
| Wyandotte | WYDMI |
| Inkster | INKMI |
| River Rouge | RVRMI |
| Ecorse | ECSMI |

> **Important:** SiteCodes are assigned by BS&A and can change when a
> municipality upgrades or re-contracts. Verify at
> https://www.bsaonline.com before using. The correct SiteCode is visible
> in the URL when manually navigating a municipality's BS&A portal.

### Fields to scrape from BS&A result page

The result HTML contains a details card. Target these labels:

| BS&A label | Property model field |
|---|---|
| Parcel Number | `parcel_id` |
| SEV | `assessed_value` |
| Summer Tax / Winter Tax | `tax_amount` (sum) |
| Year Built | `year_built` |
| Floor Area | `sf_rentable` |
| Lot Size | `sf_land` |
| Owner Name | — (contact linking) |
| Legal Description | `legal_desc` |

Use `BeautifulSoup` + CSS selector `div.AssessingOutputRow` to walk the
label/value pairs. Labels vary slightly by municipality version.

---

## Livingston County — BS&A Online

Most Livingston County municipalities are on BS&A Online.

### Key municipality SiteCodes (verify)

| City / Township | SiteCode |
|---|---|
| Howell | HWLMI |
| Brighton | BRGMI |
| Brighton Township | BRTMI |
| Genoa Township | GNAMI |
| Hamburg Township | HMBMI |
| Hartland Township | HRTMI |
| Cohoctah Township | CHMMI |

Scraping approach and field mapping identical to Wayne County above.

---

## Washtenaw County — BS&A Online

### Key municipality SiteCodes (verify)

| City / Township | SiteCode |
|---|---|
| Ann Arbor | AABMI |
| Ypsilanti | YPSMI |
| Ypsilanti Township | YPTMI |
| Pittsfield Township | PFTMI |
| Saline | SLNMI |
| Chelsea | CHLMI |
| Dexter | DXTMI |
| Superior Township | SUPMI |
| Augusta Township | AUGMI |

Scraping approach and field mapping identical to Wayne County above.

---

## Enrichment Field Map — Summary

What gets written back to the `Property` model:

| Source field | Property model field | Condition |
|---|---|---|
| Parcel ID | `parcel_id` | Always; overwrites only if currently null |
| SEV | `assessed_value` | Always |
| Tax total | `tax_amount` | Always |
| Year built | `year_built` | Overwrites only if currently null |
| Building SF | `sf_rentable` | Overwrites only if currently null |
| Land SF | `sf_land` | Overwrites only if currently null |
| Legal description | `legal_desc` | Overwrites only if currently null |

Fields are never silently overwritten if the broker already has a value.
Show a diff modal so the broker can accept or skip each changed field.

---

## Implementation Notes

### Routing logic (pseudo-code)
```python
ARCGIS_COUNTIES  = {"Oakland", "Macomb"}
BSAONLINE_COUNTIES = {"Wayne", "Livingston", "Washtenaw"}

def route(property):
    if property.state != "MI":
        raise NotImplementedError("Only Michigan supported in v1")
    county = city_to_county(property.city)   # lookup table below
    if county in ARCGIS_COUNTIES:
        return arcgis_enrich(property, county)
    elif county in BSAONLINE_COUNTIES:
        site_code = city_to_bsa_code(property.city)
        return bsaonline_enrich(property, site_code)
    else:
        raise LookupError(f"No data source configured for {county} County")
```

### Lookup priority
1. `parcel_id` (fastest, most accurate — query directly)
2. `address` + `city` (fallback — returns multiple candidates, pick best match)

### Rate limiting
- ArcGIS: no documented rate limit for public services; be polite (1 req/s)
- BS&A Online: no public API; scrape with a 2s delay and a browser User-Agent
  header. Heavy scraping may trigger a block.

### ArcGIS response shape
```json
{
  "features": [
    {
      "attributes": {
        "PARCELID": "12-34-567-890-12",
        "SEV": 185000,
        "YEARBUILT": 1978,
        ...
      }
    }
  ]
}
```
Access via `response["features"][0]["attributes"]`.

### BS&A scrape shape
No JSON — parse HTML. The key selector pattern (BeautifulSoup):
```python
rows = soup.select("div.AssessingOutputRow")
data = {r.select_one(".label").text.strip(): r.select_one(".value").text.strip()
        for r in rows if r.select_one(".label")}
```
Exact class names vary by BS&A version; verify against a live scrape.

---

## City → County Lookup Table

```python
CITY_TO_COUNTY = {
    # Oakland
    "Auburn Hills": "Oakland", "Birmingham": "Oakland",
    "Bloomfield Hills": "Oakland", "Clawson": "Oakland",
    "Farmington": "Oakland", "Farmington Hills": "Oakland",
    "Ferndale": "Oakland", "Hazel Park": "Oakland",
    "Madison Heights": "Oakland", "Milford": "Oakland",
    "Novi": "Oakland", "Oak Park": "Oakland",
    "Pontiac": "Oakland", "Rochester": "Oakland",
    "Rochester Hills": "Oakland", "Royal Oak": "Oakland",
    "Southfield": "Oakland", "South Lyon": "Oakland",
    "Troy": "Oakland", "Walled Lake": "Oakland",
    "Waterford": "Oakland", "West Bloomfield": "Oakland",
    "White Lake": "Oakland", "Wixom": "Oakland",
    # Macomb
    "Center Line": "Macomb", "Clinton Township": "Macomb",
    "Eastpointe": "Macomb", "Fraser": "Macomb",
    "Harrison Township": "Macomb", "Macomb Township": "Macomb",
    "Mount Clemens": "Macomb", "New Baltimore": "Macomb",
    "Richmond": "Macomb", "Roseville": "Macomb",
    "Shelby Township": "Macomb", "St. Clair Shores": "Macomb",
    "Sterling Heights": "Macomb", "Utica": "Macomb",
    "Warren": "Macomb", "Washington Township": "Macomb",
    # Wayne
    "Allen Park": "Wayne", "Canton": "Wayne",
    "Dearborn": "Wayne", "Dearborn Heights": "Wayne",
    "Detroit": "Wayne", "Ecorse": "Wayne",
    "Garden City": "Wayne", "Grosse Pointe": "Wayne",
    "Inkster": "Wayne", "Lincoln Park": "Wayne",
    "Livonia": "Wayne", "Melvindale": "Wayne",
    "Northville": "Wayne", "Plymouth": "Wayne",
    "Redford": "Wayne", "River Rouge": "Wayne",
    "Riverview": "Wayne", "Romulus": "Wayne",
    "Southgate": "Wayne", "Taylor": "Wayne",
    "Trenton": "Wayne", "Westland": "Wayne",
    "Woodhaven": "Wayne", "Wyandotte": "Wayne",
    # Livingston
    "Brighton": "Livingston", "Fowlerville": "Livingston",
    "Hartland": "Livingston", "Howell": "Livingston",
    "Pinckney": "Livingston",
    # Washtenaw
    "Ann Arbor": "Washtenaw", "Chelsea": "Washtenaw",
    "Dexter": "Washtenaw", "Milan": "Washtenaw",
    "Saline": "Washtenaw", "Ypsilanti": "Washtenaw",
}
```
