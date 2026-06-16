# UpFront Broker — CLAUDE.md

> Read this before every prompt. Surgical edits. Don't rewrite what works.

---

## What This Is

B2B CRE broker intelligence platform for independent commercial real estate brokers in Metro Detroit. Solo-agent, IC-first — broker owns their data, fully portable. Live at **upfront-broker.onrender.com**.

> NOT a property database. Brokers have CoStar for that.
> This is a BROKER INTELLIGENCE PLATFORM: know who owns what, find the human behind the LLC, stay ahead of transactions, build targeted buyer outreach.

---

## Stack

- **Backend:** FastAPI + SQLAlchemy + PostgreSQL + Alembic
- **Frontend:** Vanilla JS (ES6+), no frameworks, multi-file
- **Deployment:** Render (web service + PostgreSQL), auto-deploy via GitHub webhook
- **Auth:** Google OAuth + email/password, JWT tokens
- **Maps:** Leaflet.js
- **Geospatial:** Oakland County ArcGIS (geometry/coordinates only)

## Repo & Local

- **GitHub:** github.com/AI-ResumeWizard/upfront-broker
- **Local:** /Applications/UpFront Broker/upfront-broker
- **Claude Code:** `cd "/Applications/UpFront Broker/upfront-broker" && claude` (green terminal)
- **Render shell:** Render dashboard → service → Shell tab

## Design System

```
Navy:   #0f1923  (sidebar, headers)
Gold:   #c9943a  (accent, primary buttons)
Cream:  #f7f4ef  (background)
Fonts:  DM Sans (body), DM Serif Display (headings), JetBrains Mono (numbers)
```

---

## Coding Rules (CRITICAL)

- ES6+ OK on frontend — **no frameworks, vanilla JS only**
- CSS variables always — **never hardcode colors**
- `owner_id` on **every** DB query — data isolation is the product promise
- Validate any FK passed from the client belongs to the current `owner_id` before assignment (not just isolation on read — isolation on write)
- Surgical edits — **don't rewrite what works**
- One file per concern, pages under 500 lines
- All code changes via **Claude Code** (green terminal)
- All ops commands via **Render shell** (browser)
- Set `foreign_keys=` explicitly on any SQLAlchemy relationship between two tables that share more than one FK (properties↔accounts now has four FKs — already burned us twice; be defensive on every new pair)

---

## Operational Protocol

Every action the user must take is spelled out explicitly: the environment (Claude Code / Render Shell / Render Dashboard / Browser / Local Terminal), the exact command or click, and the order. No ambiguity about what to run or when.

**Environment labels:**
- `→ CLAUDE CODE` — green terminal, AI coding assistant local
- `→ RENDER DASHBOARD` — browser, Render web UI
- `→ RENDER SHELL` — Render dashboard → service → Shell tab
- `→ LOCAL TERMINAL` — dark grey terminal on Mac, in repo dir
- `→ BROWSER` — live site or test page

**Auto-deploy quirk:** Render's auto-deploy webhook occasionally stops firing silently. If a push doesn't trigger a new deploy within a few minutes, queue Manual Deploy → Deploy latest commit from the dashboard.

**Auto-migrate on deploy:** Render runs `alembic upgrade head` during build. A silent two-line `alembic upgrade head` output (just the two `INFO` lines, no "Running upgrade") is success, not failure. Confirm with `alembic current` against the expected head.

**Render shell is shallow/grafted clone:** `git log` only shows the build's tip commit. `git show --stat HEAD~1` will fail with "ambiguous argument" because there's no parent. To inspect a commit's actual diff stats, do it from the local repo, not Render.

---

## Data Model

### CONTACT
```
id, owner_id, first_name, last_name, email, phone, title, company,
account_id, tenant_id (FK → tenants),
address, city, state, zip, notes, created_at
```

### CONTACT_PHONES (multi-phone child table)
```
id, owner_id, contact_id (CASCADE),
label (mobile|office|direct|fax|other), number, is_primary,
created_at
```
- `contacts.phone` retained as legacy mirror — synced to current primary via `_resync_legacy_phone`
- Multi-primary guard: setting `is_primary=true` on one row unsets it on the contact's others, same transaction
- 2,322 legacy phones backfilled

### ACCOUNT (party model — not just companies)
```
id, owner_id, name, normalized_name,
roles text[] NOT NULL DEFAULT '{}',
account_type (deprecated, kept for display),
entity_type (LLC / Corp / Trust / Individual — legal form, separate from roles),
website, phone, email,
address, city, state, zip, notes, created_at
```
- An Account is a **party** — any actor that can own, be owned, or play a role in a deal. A company, a trust, a fund, OR a person.
- A person who owns something = Account (role `individual`) paired to a Contact for phone/email
- Multi-role via `roles` array — additive and sticky, never auto-stripped
- `normalized_name`: lowercase, strip punctuation + LLC/Inc/Corp/Co/Trust/LP/LLP/Holdings/Company — used for Regrid reconciliation
- GIN index on `roles`, btree on `normalized_name`

### ACCOUNT_ROLES (canonical vocabulary, seeded — 33 entries across 7 categories)
```
slug (PK), display_name, category
```
**Categories:** principals, brokerage_mgmt, capital_finance, legal_professional, diligence_project, government_public, vendor
**Key slugs:** owner, tenant, buyer, seller, investor, developer, guarantor, individual, brokerage, property_manager, asset_manager, lender, mortgage_broker, appraiser, loan_servicer, qi_1031, attorney, title_company, escrow_agent, accounting_firm, tax_consultant, insurance, environmental, engineering, surveyor, architect, general_contractor, zoning_consultant, inspector, municipality, econ_dev_authority, utility, vendor

### `ensure_role()` helper
```python
def ensure_role(account, role):
    if role not in account.roles:
        account.roles = account.roles + [role]   # reassign for SQLAlchemy ARRAY tracking
```
Fires automatically from every link-writer:
- `property.recorded_owner_account_id` set → `ensure_role(acct, 'owner')`
- `property.manager_account_id` set → `ensure_role(acct, 'property_manager')`
- Engagement created (`listing_sale|listing_lease|bov` → `'owner'`, `buyer_rep` → `'buyer'`, `tenant_rep` → `'tenant'`, `consulting|referral` → no role)
- Future: listings (brokerage_account_id → `'brokerage'`), comps (involved_brokerage_account_id → `'brokerage'`)

### PROPERTY
```
id, owner_id, name, building_name, park_name,
address, city, state, zip, lat, lng,
property_type, subtype, sf_rentable, sf_land, year_built,
assessed_value, tax_year, zoning, parcel_id,

recorded_owner_account_id (FK accounts, SET NULL)   -- the LLC on the deed
manager_account_id        (FK accounts, SET NULL)   -- property manager
tax_bill_account_id       (FK accounts, SET NULL)   -- tax bill recipient (clue, no role)

-- Industrial: clear_height, dock_doors, drive_in_doors, rail_service,
   power_amps, sprinklers, crane_capacity, cross_dock
-- Retail: anchor_tenant, traffic_count, frontage_ft, drive_through, pylon_sign
-- Office: building_class, leed_certified, fiber_optic, generator
-- Multifamily: unit_mix, avg_rent_per_unit, laundry, pet_friendly
-- Hospitality: flag, adr, revpar, number_of_rooms
-- Medical: exam_rooms, surgical_suites, licensed_beds
-- Land: floodplain, wetlands, utilities_to_site, environmental
-- Financial: gross_income, operating_expense, lease_type, tenant_pays, owner_pays
-- General: opportunity_zone, tif_district, historic_district
-- Legacy: tenant (text, migrated to property_tenants)

notes, created_at
```
- Three FKs to accounts → `Property.account` ↔ `Account.properties` relationship pinned to `account_id` explicitly (foreign_keys=)
- Owner-isolation validation via `_validate_account_links` before any FK assignment

### ENGAGEMENT (brokerage pipeline — distinct from deals)
```
id, owner_id,
type   -- listing_sale | listing_lease | tenant_rep | buyer_rep | bov | consulting | referral
stage  -- pursuing | proposed | active | closed | lost | expired
signed_agreement bool, agreement_date,
client_account_id    (FK accounts, SET NULL),
subject_property_id  (FK properties, SET NULL),
name, notes, created_at
```
- Type × stage collapses the "Listings I want / Listings I have / Assignments I want / Assignments I have / BOVs" buckets into one entity
- Kanban by stage at `/pages/pipeline.html`, drag-to-PUT
- `_validate_account_links`-style owner-isolation on `client_account_id` and `subject_property_id`
- Future child junctions (Phase B): `opportunities` for listings (prospective buyers/tenants), `candidate_properties` for rep assignments

### DEAL (transaction pipeline — distinct from engagements)
```
id, owner_id, property_id, name, stage, deal_type,
price, commission_pct, commission_amt, co_broker, co_broker_split,
expected_close, actual_close, notes, created_at
```
Stages: Lead → Qualified → Proposal → LOI → Under Contract → Closed
Future: add `buyer_account_id`, `seller_account_id` for party links.

### ACTIVITY
```
id, owner_id, deal_id, contact_id,
activity_type, subject, notes, activity_date, created_at
```

### DOCUMENT
```
id, owner_id, deal_id, property_id,
filename, file_url, doc_type, notes, created_at
```
Future: generalize across all entities (account_id, contact_id, tenant_id, comp_id), add `kind` (file|url|text), serve via auth-checked endpoint.

### TENANT (top-level entity)
```
id, owner_id, name, normalized_name,
industry (Food & Beverage / Financial / Retail / Medical /
          Office / Industrial / Service / Other),
website, hq_address, hq_city, hq_state, hq_zip,
notes, created_at
```
`normalized_name` strips: LLC, Corp, Co, Coffee, Inc, Restaurant, Cafe, punctuation. Used for fuzzy matching (rapidfuzz partial_ratio, threshold 55).

### PROPERTY_TENANTS (space/lease junction)
```
id, owner_id, property_id, tenant_id,
sf, pct_of_building, rent_per_sf,
lease_type (NNN / Gross / Modified Gross / Full Service),
lease_start, lease_expiry, is_available, notes
```

### COMPS
```
id, owner_id, address, city, state, zip, property_type,
sf, sale_price, price_per_sf, sale_date, cap_rate, notes, created_at
```
Future: add `property_id` (FK), `involved_brokerage_account_id` (FK).

### PARCELS (local Oakland County reference table — ~50k rows currently, target 490k after Regrid)
```
keypin (PK), pin, revisiondate, cvttaxcode, cvttaxdescription,
classcode, name1, name2, siteaddress, sitecity, sitestate,
sitezip5, postaladdress, assessedvalue, taxablevalue,
num_beds, num_baths, structure_desc, living_area_sqft,
shapearea, shapelen, county (default: 'oakland')

Indexes: sitezip5, name1, classcode, county
```
- name1/name2 NULL in Oakland County public data — Regrid fills these
- Search at `GET /api/finder/parcels/search?q=` (ILIKE on siteaddress/keypin, cap 10)
- Attach at `POST /api/properties/{id}/attach-parcel` — owner-scoped, fills blank fields only, maps classcode → property_type via local Oakland map

**Oakland County CLASSCODE map:**
```
401 → Residential          407 → Residential Vacant Land
402 → Residential Condo    403 → Residential Apartment
201 → Commercial           202 → Commercial Condo
207 → Commercial Vacant    203 → Commercial Other
301 → Industrial           302 → Industrial Condo
101/102 → Agricultural     001/002/006 → Exempt
```

### ENRICHMENT_CACHE
```
id, lookup_type, lookup_key, data (JSON), expires_at, created_at
lookup_type: parcels_v2_by_zip (v2 — old parcels_by_zip entries ignored)
TTL: 7 days
```

### PORTAL
```
id, owner_id, property_id, deal_id, portal_type (buyer/seller),
access_email, access_token, sections_viewed (JSON), created_at
```

---

## API Routes

```
/api/auth                          — login, register, Google OAuth
/api/contacts                      — full CRUD (tenant_id field, /full includes phones)
/api/contacts/{id}/phones          — phone CRUD (owner-scoped via _get_owned_contact)
/api/contacts/search               — typeahead
/api/accounts                      — full CRUD (roles, normalized_name)
/api/accounts/search?q=            — typeahead (ILIKE name, owner-scoped, limit 8) — **registered BEFORE /{id} to avoid route shadowing**
/api/accounts/{id}/full            — includes roles_resolved, owned_properties, managed_properties, engagements, contacts
/api/properties                    — full CRUD (recorded_owner_account_id, manager_account_id, tax_bill_account_id, building_name, park_name)
/api/properties/search?q=          — typeahead
/api/properties/{id}/full          — includes recorded_owner_account (id+name)
/api/properties/{id}/attach-parcel — owner-scoped parcel attach
/api/deals                         — full CRUD
/api/activities                    — full CRUD
/api/documents                     — full CRUD
/api/portal                        — buyer/seller portal
/api/comps                         — full CRUD
/api/imports                       — CSV/XLSX, sectioned/alphabetized chooser, role-aware account creation, phone-slot mapping
/api/finder/parcels/search?q=      — local parcels table search
/api/finder/parcel/{keypin}        — single lookup (3-step fallback: exact → strip → address)
/api/finder/add                    — add parcel to pipeline
/api/tenants                       — full CRUD + fuzzy match
/api/tenants/{id}/contacts         — direct FK + account-name fuzzy match, deduped
/api/tenants/{id}/news             — Google News RSS
/api/tenants/fuzzy?name=           — fuzzy match (rapidfuzz, threshold 55)
/api/tenants/spaces                — space/lease CRUD
/api/engagements                   — full CRUD, list/group by stage, drag-to-PUT
/api/portfolio                     — cross-silo intelligence queries
```

---

## Pages

| Page | Status | Notes |
|------|--------|-------|
| Dashboard | ✅ | Pipeline funnel, upcoming closes, activity feed |
| Properties | ✅ | List, filter, 5-tab CoStar-style detail page |
| Property detail | ✅ | Summary / Spaces & Tenants / Contacts / Public Record / Map; Recorded Owner picker + Attach Public Record card on Public Record tab |
| Contacts | ✅ | List, filter, detail with phones list (label · number, primary badge, inline add/edit/delete) |
| Accounts | ✅ | List, filter; detail = party hub with role badges, owned/managed properties, engagements, contacts |
| Deals | ✅ | Kanban + List + Map, commission math, co-broker splits |
| Pipeline (engagements) | ✅ | Kanban by stage, "+ New Engagement" with account typeahead, property typeahead, "+ Create new property" sub-form, listing-type "Set [client] as recorded owner" checkbox |
| Tenants | ✅ | Grid, detail (Properties/Contacts/News tabs), fuzzy match |
| Property Finder | ✅ | ZIP → local DB, all types, circleMarker dots |
| Portfolio Intelligence | ⚠️ | Built, not fully tested |
| Client Portal | ✅ | Buyer + seller, email-gated, section tracking |
| Comps | ✅ | Manual + CSV upload |
| Import | ✅ | Sectioned (Properties · Accounts · Contacts · Tenants · Deals · Comps), alphabetized, role-aware, phone slots (mobile/office/direct/fax/other → contact_phones with priority-based is_primary) |

---

## Frontend Asset Caching (CRITICAL — closed mid-session)

**Problem solved:** stale `app.js` survived hard refresh, broke nav items across deploys.

**Pattern in `backend/main.py`:**
```python
class RevalidateStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

app.mount("/static", RevalidateStaticFiles(...), name="css")
app.mount("/js",     RevalidateStaticFiles(...), name="js")
```
Plus `?v=2` query on `/js/app.js` and `/static/main.css` references in pages — bump per deploy when needed. HTML routes already serve with `_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}`.

---

## Sidebar (in `frontend/js/app.js`)

Single function `renderSidebar(activePage)` builds the nav for every page. Every page calls it; do not introduce per-page static nav blocks. Sections: Workspace (Dashboard, Pipeline), Records (Properties, Contacts, Accounts, Tenants, Deals), Tools (Comps, Import, Property Finder, Portfolio Intel, Client Portal).

---

## Key Learnings & Patterns

- **SQLAlchemy FK ambiguity:** properties↔accounts has FOUR FKs (account_id, recorded_owner_account_id, manager_account_id, tax_bill_account_id). Any relationship between them needs explicit `foreign_keys=`. Pin defensively on every new pair.
- **Render grafted clone:** `git log` on Render only shows the build's tip. Inspect commit stats locally.
- **Auto-migrate on deploy:** silent `alembic upgrade head` = success; confirm with `alembic current`.
- **Render webhook flakiness:** sometimes silently stops; manual deploy re-arms it.
- **Cache layers:** hard refresh bypasses browser cache but not server-side edge or `immutable` headers; cache-busting at asset URL level is the reliable fix.
- **Public/assessor data is reference, not authority:** Oakland County's assessor zip may not match USPS delivery zip. Curated/manual data wins. Never auto-overwrite manually entered fields — fill blanks only.
- **Oakland County strips owner names from ALL public data** (CSV + ArcGIS). Regrid solves this.
- **ArcGIS field naming:** `Shape.area`, not `Shape__Area` — verify via wildcard outFields=*.
- **Hybrid architecture:** local DB for attribute/owner queries, ArcGIS for geometry only.
- **Owner isolation on write, not just read:** validate any FK passed from the client belongs to the current owner before assignment. This bit us once (Contact PUT accepting any tenant_id) — established `_validate_account_links` pattern in properties router, reuse it everywhere.
- **Generic, broker-invoked, attestation-logged:** the safe pattern for any feature touching potentially-IP-bearing content (brochure parser, future Chrome extension). No source-specific detection in code; surface warnings at the moment of action; log the user's choice. Same posture as Google Drive, Dropbox.

---

## Regrid Status

- **License:** signed terms — 9-month dev license, Michigan-wide, $1,000 flat, credit applied to nationwide conversion
- **Refresh cadence:** "as available" — urban counties 4-6x/year, rural 1+x/year. Effectively quarterly-or-better on Metro Detroit.
- **Awaiting:** paperwork from Luke + Jake, then CC payment
- **Bonus:** Regrid CRO expressed inbound demand for what UpFront is building; partnership/referral conversation open for the future
- **On arrival:** one-time reconciliation script — fuzzy-match Regrid owner names against `accounts.normalized_name` (owner-scoped), set `property.recorded_owner_account_id`, fire `ensure_role('owner')`. Schema already in place.

---

## Tools & Resources

- **Claude Code** — primary coding interface (green local terminal)
- **Render** — hosting, shell access, auto-deploy via GitHub webhook
- **PostgreSQL** — primary database (Render-hosted)
- **FastAPI / SQLAlchemy / Alembic** — backend framework and ORM/migrations
- **Oakland County ArcGIS API** — parcel geometry/coordinates (rate-limited)
- **Regrid** — incoming, enriched parcel data (owner names, zoning, sale history, coordinates)
- **rapidfuzz** — fuzzy matching for Tenant deduplication and account reconciliation
- **Google News RSS** — tenant news feed
- **GitHub** — source control; auto-deploy trigger
