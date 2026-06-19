# UpFront Broker — CLAUDE.md

> Read this before every prompt. Surgical edits. Don't rewrite what works.
> This file is the ONLY context a brand-new session has — there is no
> memory of past sessions beyond what's written here and in the code itself.

> **MAINTENANCE RULE:** any commit that changes schema, adds/removes a route,
> a page, or a migration, or contradicts a claim documented below, must
> update this file in the *same* commit. Before writing a claim here, verify
> it against the actual model/router/migration file — not against memory of
> an earlier conversation, and not against what an instruction *says* should
> be true. This file has drifted badly from reality before (false columns,
> a column documented where a junction table actually existed, deleted files
> documented as missing when they'd been restored, design tokens documented
> as existing when they hadn't been added) — every section below was
> re-verified against current code as of 2026-06-19. Don't repeat the drift.

---

## What This Is

B2B CRE broker intelligence platform for independent commercial real estate brokers in Metro Detroit. Solo-agent, IC-first — broker owns their data, fully portable. Live at **upfront-broker.onrender.com**.

> NOT a property database. Brokers have CoStar for that.
> This is a BROKER INTELLIGENCE PLATFORM: know who owns what, find the human behind the LLC, stay ahead of transactions, build targeted buyer outreach.

**Architecture: property-centric, one connected graph — not five separate silos.** The Property is the anchor entity; Accounts, Contacts, Tenants, and Deals all relate back to a property rather than living in disconnected lists. This is implemented via several link mechanisms, not one single junction — know which one applies where:

- **`property_parties`** — general party↔property↔role links (e.g. leasing broker, sale broker, tenant rep, manager) created mainly by the general-purpose property importer's party fan-out. Either side of the party can be an Account or a Contact.
- **Direct FKs on `properties`** — `account_id`, `recorded_owner_account_id`, `manager_account_id`, `tax_bill_account_id` — the highest-traffic single-purpose owner/manager/tax-recipient links, queried constantly, so they're columns rather than junction lookups.
- **`property_tenants`** — Tenant↔Property occupancy/lease links (sf, rent, lease dates) — a different junction than `property_parties`, scoped to leasing specifically.
- **`deal_contacts`** — Account/Contact↔Deal role links (buyer, seller, attorney, lender, etc.) — scoped to a Deal, not directly to a Property (a Deal has its own `property_id` FK back to the property).
- **`engagements`** — direct `subject_property_id` / `client_account_id` FKs, no junction.

The unified Search/Map page (`/pages/search.html`) is the primary lens onto this graph today — one map-driven view across Properties/Accounts/Contacts/Tenants/Deals instead of five disconnected list pages (see **Pages** below).

---

## Stack

- **Backend:** FastAPI + SQLAlchemy + PostgreSQL + Alembic
- **Frontend:** Vanilla JS (ES6+), no frameworks, multi-file
- **Deployment:** Render (free tier, web service + PostgreSQL), auto-deploy via GitHub webhook
- **Auth:** Google OAuth + email/password, JWT tokens
- **Maps:** Leaflet.js v1.9.4, loaded via the unpkg CDN, OpenStreetMap tiles — the *only* mapping library in the app (Property detail's Map tab, Account/Contact detail mini-maps, and the Search/Map page all reuse it; don't introduce a second one)
- **Geocoding (three independent sources, don't conflate them):**
  - **Oakland County ArcGIS** — parcel geometry/boundaries only (Property Finder)
  - **Nominatim (OpenStreetMap)** — `Property.lat/lng`, auto-geocoded on save via a direct `urllib` call in `routers/properties.py` (no API key, best-effort, swallows errors)
  - **US Census Bureau geocoder** — `Account.lat/lng` and `Contact.lat/lng`, via `backend/services/geocoding.py` (no API key, US-only); see **Data Model → ACCOUNT/CONTACT** below

## Repo & Local

- **Local:** /Applications/UpFront Broker/upfront-broker
- **Claude Code:** `cd "/Applications/UpFront Broker/upfront-broker" && claude` (green terminal)

## Deployment / Git (CRITICAL)

- **GitHub remotes — two configured, only one matters:**
  - `new` → `git@github.com:UpFront-Intelligence/upfront-broker.git` — **this is the remote Render watches for auto-deploy.** Always push here.
  - `origin` → `https://github.com/AI-ResumeWizard/upfront-broker.git` — legacy remote from before the project moved orgs. **Never push here.**
  - The local `main` branch's upstream tracking has pointed at `new/main` and has drifted before — a bare `git push` is not safe. **Always push explicitly: `git push new main`.**
- **Render:** free tier — **no shell access.** Operational visibility is logs + env vars + manual "Deploy latest commit" from the dashboard only. Any one-off script (backfills, migrations) runs from a **local terminal** against `DATABASE_URL` (local `.env`, or the production connection string pasted in temporarily) — there's no in-place shell to run it from on Render itself.
- **Start command** (Render dashboard setting, mirrored in `render.yaml`): `python db_setup.py && cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
- **`db_setup.py`** (repo root) exists because the original core tables (`accounts`, `properties`, `contacts`, etc.) predate Alembic — they were created via `Base.metadata.create_all()` before migrations were adopted, so no migration under `alembic/versions/` creates them from scratch. Running `alembic upgrade head` against a brand-new empty database fails partway through the first migration that `ALTER`s one of those tables. `db_setup.py` detects fresh-vs-existing (`inspect(engine).has_table("accounts")`) and either `create_all()` + `alembic stamp head` (fresh) or a normal `alembic upgrade head` (existing). **Don't replay migrations on a fresh DB by hand — this script already handles the branch.**
- **`render.yaml`** exists at the repo root and is the deploy config (buildCommand/startCommand/envVars), committed alongside `db_setup.py`. It was deleted once earlier in this project's history and then deliberately restored — if you're tempted to delete it again because an older note says it shouldn't exist, don't; check `git log -- render.yaml` first.
- **Auto-deploy quirk:** the GitHub webhook occasionally stops firing silently. If a push doesn't trigger a deploy within a few minutes, use Manual Deploy → "Deploy latest commit" from the dashboard.
- **Auto-migrate on deploy:** the start command runs `alembic upgrade head` before `uvicorn` starts. A silent two-line `INFO` output (no "Running upgrade ... -> ..." line) means there was nothing new to apply — that's success, not failure.
- **Current migration head:** `c7e65628672c` (`add_account_lat_lng`) — 21 migrations total, linear chain, no branches. Verify with `alembic heads` if this drifts.

## Design System

Tokens live in `frontend/css/tokens.css`; `frontend/css/main.css` `@import`s it and aliases the old variable names (`--navy`, `--gold`, `--cream`, etc.) onto the new tokens so untouched pages inherit the new look without per-page edits — don't add a second source of truth, extend `tokens.css`.

```css
--ink:            #1B2235;   /* body text */
--paper:          #F3F2EE;   /* page background */
--surface:        #FFFFFF;   /* cards, sidebar, topbar — sidebar is light, NOT dark navy */
--accent:         #1F5E52;   /* primary green — buttons, links, active nav state */
--accent-hover:   #17473D;
--hint-gold:      #C8932A;   /* reserved exclusively for the suggestion/lightbulb system — never reuse */
--hint-gold-soft: #F6E8CC;
--dataviz-amber:      #A8702E;   /* categorical map/chart amber — deliberately distinct hex/lightness
                                     from --hint-gold so the two are never visually confusable */
--dataviz-amber-soft: #F2E2D0;
--border:         rgba(27,34,53,0.08);
--text-secondary: #5C6470;

--radius-sm: 8px;   --radius-md: 12px;
--shadow-sm / --shadow-md
--space-1 (4px) through --space-6 (48px)

/* Role badges — fixed mapping to account_roles.slug categories, not reused elsewhere */
--role-leasing / --role-owner / --role-sale / --role-tenant / --role-sublease / --role-manager

--font-system: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
```

- **Single typeface everywhere** — `--font-body`, `--font-serif`, and `--font-mono` (the legacy names old pages reference) all alias to `--font-system`. Hierarchy comes from weight/size only, not multiple families.
- **`--hint-gold` is exclusive to the lightbulb/suggestion UI** (`main.css`'s `.hint-*` block says so explicitly in a comment). **`--dataviz-amber` / `--dataviz-amber-soft` are the categorical map/chart amber** — used by Property Finder's "Commercial" legend dot + matching marker color (`finder.html`, read live via `getComputedStyle` with a hardcoded `#A8702E` fallback) and Query's `.type-property` result badge (`query.html`). Before these existed, both spots hardcoded the old pre-rewrite gold hex `#c9943a` directly — not literally `--hint-gold`, but the same visual conflict (a gold tone doing unrelated categorical work); both are migrated now. The Search/Map page's pins and Property Finder's non-Commercial categories still fall back to `--accent` for their color, unrelated to this token. If a third chart/map categorical color is ever needed, add a real token to `tokens.css` rather than reusing `--hint-gold`/`--dataviz-amber` or hardcoding a hex value inline.

---

## Coding Rules (CRITICAL)

- ES6+ OK on frontend — **no frameworks, vanilla JS only**
- CSS variables always — **never hardcode colors** (the one accepted exception: Leaflet `circleMarker` options, which take a literal color string — even there, read the token live via `getComputedStyle` first and only hardcode as a last-resort fallback)
- `owner_id` on **every** DB query — data isolation is the product promise
- Validate any FK passed from the client belongs to the current `owner_id` before assignment (not just isolation on read — isolation on write)
- Surgical edits — **don't rewrite what works**
- One file per concern, pages under 500 lines
- All code changes via **Claude Code** (green terminal)
- Set `foreign_keys=` explicitly on any SQLAlchemy relationship between two tables that share more than one FK. `properties` has **four** FKs to `accounts` (`account_id`, `recorded_owner_account_id`, `manager_account_id`, `tax_bill_account_id`) — already burned us twice; be defensive on every new pair, including junction tables (`property_parties`, `marketing_list_members` etc. already pin `foreign_keys=` for exactly this reason even with only one FK column today).
- `merge_accounts` (in `routers/accounts.py`) re-points FKs from a hand-maintained, explicit list of every table that references `accounts.id` — it does **not** introspect this at runtime. Any new FK to `accounts.id` must be added to that function's list in the same commit, or a future merge will silently leave that table's rows pointing at the soft-deleted duplicate.

---

## Operational Protocol

Every action the user must take is spelled out explicitly: the environment, the exact command or click, and the order. No ambiguity about what to run or when.

**Environment labels:**
- `→ CLAUDE CODE` — green terminal, AI coding assistant local
- `→ RENDER DASHBOARD` — browser, Render web UI (logs, env vars, manual deploy — no shell)
- `→ LOCAL TERMINAL` — dark grey terminal on Mac, in repo dir (also where one-off scripts under `scripts/` run, against a local or temporarily-pasted-in `DATABASE_URL`)
- `→ BROWSER` — live site or test page

**Auto-deploy quirk:** Render's auto-deploy webhook occasionally stops firing silently. If a push doesn't trigger a new deploy within a few minutes, queue Manual Deploy → Deploy latest commit from the dashboard.

**Auto-migrate on deploy:** Render runs `alembic upgrade head` during the start command, before `uvicorn` starts (see **Deployment / Git** above for why `db_setup.py` runs first). A silent two-line output (just the two `INFO` lines, no "Running upgrade") is success, not failure.

---

## Data Model

Every table below was re-read from `backend/models/*.py` and the relevant migration on 2026-06-19. Where this doc previously stated something that turned out to be wrong, the correction is called out — don't assume the rest of the codebase is equally clean; verify before relying on any single line here for a write-path change.

### CONTACT
```
id, owner_id, first_name, last_name, email, phone, mobile, title,
photo_url, linkedin, contact_type, source, tags,
tenant_id (FK → tenants, SET NULL),
address, city, state, zip, lat, lng,
notes, created_at, updated_at
```
- `address/city/state/zip` are real columns (migration `3f514cfabf0e`). Default-inherited from the linked Account at Contact-creation time when a row gives no distinct contact address — fill-blank-from-parent, never overwrites an explicit value.
- `lat/lng`: nullable Float, geocoded via the **US Census Bureau** geocoder (`services/geocoding.py`), *not* the Nominatim service Property uses. `geocode_contact_if_address_changed()` (in `services/accounts.py`) only geocodes a Contact directly if its address genuinely differs from its primary linked Account's; otherwise it inherits lat/lng from the Account via `_propagate_account_geocode_to_contacts()`. Triggered from `routers/contacts.py` on create/update, only when address/city/state actually changed.
- No `company` or `account_id` column — company affiliation is exclusively via the `contact_accounts` junction (many-to-many, with `role`), never a direct FK on Contact.
- `Contact.phones` relationship pins `foreign_keys=[ContactPhone.contact_id]` explicitly even though there's only one FK today — defensive per the Coding Rules note above.

### CONTACT_ACCOUNTS (junction — company affiliation)
```
id, contact_id (FK), account_id (FK), role, is_primary, created_at
```
`role`: Owner, Partner, Signatory, Manager, Trustee, etc. (free text). `is_primary` decides which linked Account a Contact inherits address/geocode from when it has none of its own.

### CONTACT_PHONES (multi-phone child table)
```
id, owner_id, contact_id (CASCADE),
label (mobile|office|direct|fax|other), number, is_primary,
created_at
```
- `contacts.phone` retained as legacy mirror, synced to current primary
- Multi-primary guard: setting `is_primary=true` on one row unsets it on the contact's others, same transaction

### ACCOUNT (party model — not just companies)
```
id, owner_id,
merged_into_id (FK → accounts.id, SET NULL)  -- soft-merge pointer, see below
name, normalized_name,
roles text[] NOT NULL DEFAULT '{}',
entity_type (LLC / Corp / Trust / Individual / REIT / Partnership),
ein, website, phone, email,
address, city, state, zip,
lat, lng,
notes, created_at, updated_at
```
- An Account is a **party** — any actor that can own, be owned, or play a role in a deal. A company, a trust, a fund, OR a person (role `individual`, typically paired to a Contact for phone/email).
- Multi-role via `roles` array — additive and sticky, never auto-stripped. `ensure_role()` lives in `services/accounts.py` and reassigns the list (never mutates in place) so SQLAlchemy's ARRAY tracking sees the change.
- `normalized_name`: lowercase, strip punctuation + LLC/Inc/Corp/Co/Trust/LP/LLP/Holdings/Company — used for both Regrid reconciliation (future) and the duplicate-account scanner (live today).
- `merged_into_id` — set when this account was merged away as a duplicate via `POST /api/accounts/merge`. **Never hard-deleted** — audit trail + safety net for any FK reference the merge missed. `services/accounts.py`'s `owned_accounts_query()` helper filters `merged_into_id IS NULL` and should be used (instead of querying `Account` directly) anywhere the result is "which accounts does this owner have," so merged-away duplicates never resurface in lists/search/fuzzy-match candidate pools.
- `lat/lng` — US Census geocoder, set by `geocode_account_if_address_changed()` on create/update whenever address/city/state actually changed, and propagated to any inherited Contact missing its own coordinates.
- No `account_type` column exists (an earlier version of this doc claimed one, marked deprecated — it isn't there; `entity_type` is the only classification column).

### ACCOUNT_ROLES (canonical vocabulary, seeded — 37 entries across 7 categories)
```
slug (PK), display_name, category
```
**Categories:** principals, brokerage_mgmt, capital_finance, legal_professional, diligence_project, government_public, vendor.
Base seed (migration `d8e9f0a1b2c3`) was 33 entries; two later migrations added 4 more roles to `brokerage_mgmt` — `leasing_broker` (`df65bcec62ab`) and `sale_broker` / `tenant_rep` / `sublease_broker` (`55f798901deb`), added to support the property-with-parties importer's column detection. **37 total, still 7 categories** — if this drifts again, recount from `alembic/versions/*account_role*.py` rather than trusting this number.

### PROPERTY_PARTIES (general party↔property↔role junction)
```
id, property_id (FK, CASCADE), account_id (FK, CASCADE, nullable), contact_id (FK, CASCADE, nullable),
role, source (default "import"), note, created_at
```
Either `account_id` or `contact_id` is set (a party is one or the other). `role` is free text (leasing_broker, owner, sale_broker, tenant_rep, manager, tax_bill, etc.) — written mainly by the general-purpose property importer's party fan-out (`routers/import_properties_parties.py`). All three relationships (`property`, `account`, `contact`) pin `foreign_keys=` explicitly.

### PROPERTY
~150 columns covering every property type in one table — see `backend/models/property.py` for the authoritative full list. Core + the most relevant groups:
```
id, owner_id,
account_id (FK accounts, nullable)                  -- general "current owner entity" link;
                                                        used by has_owner filters and /full; no auto-role
recorded_owner_account_id (FK accounts, SET NULL)   -- deed-of-record owner, set via the Public Record
                                                        tab; DOES fire ensure_role(acct, 'owner')
manager_account_id        (FK accounts, SET NULL)   -- property manager; fires ensure_role('property_manager')
tax_bill_account_id       (FK accounts, SET NULL)   -- tax bill recipient, a clue only — no role fired

name, building_name, park_name, address, city, state, zip, county,
property_type, subtype, status (Active/Off Market/Sold/Leased), market, submarket,
year_built, year_renovated, sf_rentable, sf_land, units, stories, construction_type,
zoning, parking_ratio, parking_spaces, occupancy_pct,
asking_price, asking_price_per_sf, assessed_value, tax_amount, tax_year, cap_rate, noi,
parcel_id, legal_desc, photo_urls (array),
lat, lng                                             -- Nominatim (OpenStreetMap), auto-set on save —
                                                         NOT the Census geocoder Account/Contact use
last_sale_price, last_sale_date,
tenant (text)                                        -- simple occupant-name field that predates the
                                                         property_tenants junction; both still coexist,
                                                         still writable/filterable — not deprecated

-- Industrial: clear_height_min/max, dock_doors, drive_in_doors, rail_service(+type),
   power_amps/volts/phase, sprinklers(+type), crane_capacity/height, cross_dock, yard_area, ...
-- Retail: anchor_tenant, traffic_count, frontage_ft, drive_through, pylon_sign, end_cap, ...
-- Office: building_class, leed_certified, fiber_optic, generator, data_center_ready, ...
-- Multifamily: unit_mix, avg_rent_per_unit, laundry, pet_friendly, affordable_units, ...
-- Hospitality: flag, adr, revpar, number_of_rooms, restaurant_seats, ...
-- Medical: exam_rooms, surgical_suites, licensed_beds, medical_gas, ...
-- Land: floodplain(+zone), wetlands(+acres), utilities_to_site, subdivided, ...
-- Extended financial: gross_income, operating_expense, vacancy_allowance, debt_service, ...
-- General: opportunity_zone, enterprise_zone, historic_district, tif_district, franchise(+name), ...
-- Residential (future use, all nullable): bedrooms, bathrooms, hoa_fee, school_district, ...

notes, created_at, updated_at
```
- Four FKs to `accounts` (see above) — `Property.account` relationship pins `foreign_keys=[account_id]` explicitly.
- Owner-isolation validation via `_validate_account_links()` in `routers/properties.py` before any of the three "linked party" FK fields can be assigned.
- `GET /api/properties/` has a `search` query param (free-text) and a very large filter surface (type/status/location/size/price/financial ranges) — there is **no separate `/api/properties/search` endpoint**; an earlier version of this doc claimed one existed.

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
- Type × stage collapses the "Listings I want / Listings I have / Assignments I want / Assignments I have / BOVs" buckets into one entity.
- Kanban by stage at `/pages/pipeline.html`, drag-to-PUT.
- `client_account` / `subject_property` relationships pin `foreign_keys=` explicitly.
- `ensure_role()` fires on create: `listing_sale|listing_lease|bov` → `'owner'`, `buyer_rep` → `'buyer'`, `tenant_rep` → `'tenant'`, `consulting|referral` → no role.

### DEAL (transaction pipeline — distinct from engagements)
```
id, owner_id, property_id (FK, required),
name, deal_type (Listing / Buyer Rep / Lease - Landlord / Lease - Tenant),
stage (Prospecting → Pitching → Active Listing → Under Contract → Closed → Dead),
list_price, sale_price, lease_rate, lease_sf, lease_term_months,
commission_pct, commission_total, our_split_pct, our_commission,
co_broker bool, co_broker_name, co_broker_firm, co_broker_split_pct,
projected_close, actual_close, list_date, days_on_market,
portal_enabled bool, notes, created_at, updated_at
```
**This table has drifted significantly from any earlier version of this doc** — field names are `list_price`/`sale_price` (not `price`), `commission_total` (not `commission_amt`), `projected_close` (not `expected_close`), and the stage list above is the real one (not Lead/Qualified/Proposal/LOI/Under Contract/Closed). Party links are **already implemented** via the `deal_contacts` junction below — this was previously documented as a "Future" item; it isn't anymore.

### DEAL_CONTACTS (junction — party↔deal↔role)
```
id, deal_id (FK), contact_id (FK, nullable), account_id (FK, nullable),
role (Seller / Buyer / Attorney / Lender / Guarantor / Co-Broker / ...), created_at
```
Either `contact_id` or `account_id` is set. No `owner_id` column — scope through the parent Deal's `owner_id` when querying across owners.

### ACTIVITY
```
id, owner_id, contact_id (FK, nullable), property_id (FK, nullable), deal_id (FK, nullable),
activity_type, subject, notes, activity_date, created_at
```
Has a `property_id` link in addition to `contact_id`/`deal_id` — an earlier version of this doc omitted it.

### DOCUMENT
```
id, owner_id, contact_id (FK, nullable), property_id (FK, nullable), deal_id (FK, nullable),
name, doc_type, file_url, file_size (bytes), uploaded_at
```
Already generalized across contact/property/deal (no `account_id`/`tenant_id`/`comp_id` yet, no `kind` field) — an earlier version of this doc described this generalization as entirely "Future"; the contact/property legs are already done. Field is `name`, not `filename`; timestamp column is `uploaded_at`, not `created_at`; there is no `notes` column.

### TENANT (top-level entity)
```
id, owner_id, name, normalized_name,
industry, website, hq_address, hq_city, hq_state, hq_zip,
notes, created_at
```
No `lat`/`lng` on Tenant itself — when the unified Search/Map page returns tenant rows, each row's map pin comes from the specific `PROPERTY_TENANTS` row's property, not from the Tenant entity (a chain tenant occupying 5 properties surfaces as 5 separately-pinned rows). `normalized_name` strips LLC/Corp/Co/Coffee/Inc/Restaurant/Cafe/punctuation, used for fuzzy matching (rapidfuzz `partial_ratio`, threshold 55).

### PROPERTY_TENANTS (space/lease junction)
```
id, owner_id, property_id (FK, CASCADE), tenant_id (FK, CASCADE),
sf, pct_of_building, rent_per_sf,
lease_type, lease_start, lease_expiry, is_available, notes,
source (default "manual")
```

### MARKETING_LISTS / MARKETING_LIST_MEMBERS
```
marketing_lists:        id, owner_id, name, description, created_at, updated_at
marketing_list_members: id, list_id (FK, CASCADE), account_id (FK, SET NULL, nullable),
                         contact_id (FK, SET NULL, nullable), source (default "manual"),
                         note, added_at
```
CHECK constraint `num_nonnulls(account_id, contact_id) = 1` enforces exactly one entity per member row (not zero, not both). `account`/`contact` relationships pin `foreign_keys=` explicitly. Not documented in any earlier version of this file despite already having frontend pages (`marketing-lists.html`, `marketing-list.html`) and nav presence ("Lists").

### SUGGESTIONS (general "hint" substrate — lightbulb pattern)
```
id, owner_id, suggestion_type (default "account_duplicate"),
entity_id_a, entity_id_b (both FK → accounts.id, CASCADE),
score (Numeric 5,2), reasoning, evidence (JSON),
status (new | dismissed | merged), created_at, resolved_at
```
First and currently only producer: the account-duplicate scanner (`POST /api/accounts/scan-duplicates`, rapidfuzz `token_sort_ratio` on `normalized_name`, threshold **65** — constant `DUPLICATE_SCAN_THRESHOLD` in `routers/accounts.py`). `entity_id_a/b` are typed to `accounts.id` specifically for this producer; a future producer comparing other entity types (e.g. Regrid-vs-local-account reconciliation) will need its own columns or its own table — this one isn't generic across entity types yet, only generic across *reasons* a suggestion might exist for two accounts. Not documented in any earlier version of this file despite having a full UI (lightbulb icon on Accounts list/detail, "Review Duplicates" nav page).

### COMPS
```
id, owner_id, property_id (FK, nullable),
address, city, state, property_type, sf, sale_price, price_per_sf, cap_rate,
sale_date, year_built, source (default "Manual"), notes, created_at
```
`property_id` already exists — an earlier version of this doc listed it as "Future." `involved_brokerage_account_id` genuinely does **not** exist yet and `ensure_role()` is not wired to Comps at all — that part of the old "Future" note is still accurate.

### PARCELS (local Oakland County reference table — raw SQL, not a SQLAlchemy model)
```
keypin (PK), pin, revisiondate, cvttaxcode, cvttaxdescription,
classcode, name1, name2, siteaddress, sitecity, sitestate, sitezip5,
postaladdress, assessedvalue, taxablevalue,
num_beds, num_baths, structure_desc, living_area_sqft,
shapearea, shapelen

Indexes: sitezip5, name1, classcode
```
- **No `county` column** — an earlier version of this doc listed one with a default of `'oakland'`; it never existed. "Oakland County" is a hardcoded string in the `/api/finder/parcels` response, not stored per-row.
- Created via raw DDL in `scripts/import_parcels.py` (`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` constants `CREATE_TABLE`/`CREATE_INDEXES`), **not** part of `Base.metadata` — `create_all()` alone would never create it. `db_setup.py` now imports those same constants and runs them unconditionally (idempotent, fresh or existing DB) via `_ensure_parcels_table()`, so the **table** always exists after any deploy. The table still starts **empty** — populating actual parcel **rows** still requires running `scripts/import_parcels.py` directly against `DATABASE_URL` (downloads from ArcGIS Hub, COPY-upserts).
- All access in `backend/routers/finder.py` is raw `db.execute(text("..."))` SQL, not the ORM.
- Row count not independently verified this session (no live DB available) — treat any specific number as unconfirmed until checked against the actual database.
- `name1`/`name2` NULL in Oakland County's public data — Regrid is expected to fill these.

**Oakland County CLASSCODE map** (`backend/routers/finder.py`):
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
id, lookup_type, lookup_key, source,
raw_response (JSON), phone_numbers (array), emails (array), owner_name, confidence_score,
fetched_at, expires_at (default now + 90 days), hit_count
```
**Intentionally has no `owner_id`** — shared cache for public-records data only (the same third-party fact for one parcel is the same regardless of which broker looks it up). Default TTL is **90 days**, not 7 — an earlier version of this doc had both the column list and the TTL wrong (`data` JSON column doesn't exist, it's `raw_response`; no `lookup_type: parcels_v2_by_zip` convention found in current code).

### PORTAL / PORTAL_VIEWS
```
portals:       id, deal_id (FK, unique), token, seller_emails (array), buyer_emails (array),
               pov (text), challenges (text), mutual_steps (text/JSON-encoded),
               show_timeline/show_docs/show_comps/show_offers (bools),
               created_at, updated_at
portal_views:  id, portal_id (FK), email, section, viewed_at
```
**Substantially different from any earlier version of this doc** — there is no `owner_id`, `property_id`, `portal_type`, `access_email`/`access_token` (renamed to `token`), or `sections_viewed` JSON column on Portal itself; per-view tracking is its own table (`PortalView`) with one row per (email, section, timestamp) rather than a JSON blob. A Portal belongs to a Deal (which already has the `property_id`), not directly to a Property.

---

## API Routes

```
/api/auth                              — register, login, /me, Google OAuth (+ callback)
/api/contacts                          — full CRUD; /search typeahead; /{id}/full (incl. phones);
                                          /{id}/accounts; /{id}/phones CRUD
/api/accounts                          — full CRUD; /search typeahead (registered BEFORE /{id} to
                                          avoid route shadowing); /{id}/full (roles_resolved, owned/
                                          managed properties, engagements, contacts); /{id}/contacts;
                                          /scan-duplicates; /merge
/api/properties                        — full CRUD (search is a query param on GET /, not a sub-route);
                                          /{id}/full; /{id}/attach-parcel
/api/deals                             — full CRUD; /pipeline-summary; /{id}/full; /{id}/contacts
/api/activities                        — full CRUD
/api/documents                         — full CRUD
/api/portal                            — POST / (create); GET /{deal_id}; GET/POST /token/{token}
                                          (+ /view for tracking); GET /{deal_id}/views
/api/comps                             — full CRUD; /upload-cre (CRE-platform CSV export)
/api/import                            — sectioned general importer: POST /preview, POST /execute
                                          (Properties · Accounts · Contacts · Tenants · Deals · Comps,
                                          role-aware account creation, phone-slot mapping) — used by
                                          import.html
/api/import/properties-with-parties    — POST /preview, POST (execute) — the general-purpose,
                                          property-centric column-mapping importer (every column maps
                                          to a Standard Field / Party role×attribute / Tenant link /
                                          Ignore; auto-detection is suggestions-only) — used by
                                          import-properties.html, linked from within import.html
/api/finder/parcels?zip=               — local parcels table, zip-scoped, with exists_in_db flag
/api/finder/parcels/search?q=          — typeahead over the local parcels table
/api/finder/parcel/{keypin}            — single lookup (3-step fallback: exact → strip → address)
/api/finder/add                        — add a parcel into the pipeline
/api/tenants                           — full CRUD; /fuzzy?name=; /{id}/contacts; /{id}/news (Google
                                          News RSS); /spaces CRUD (property_tenants)
/api/engagements                       — full CRUD
/api/marketing-lists                   — full CRUD on lists; /{id}/members (single + /bulk); member delete
/api/query                             — POST / — unified query engine behind the Search/Map page;
                                          GET /geo-options?return_type=&field=&q= (geography typeahead)
/api/suggestions                       — GET / (list); POST /{id}/dismiss
/api/portfolio                         — /search — cross-silo intelligence queries
```

### Query engine (`/api/query`)
- **Return types:** `contacts`, `accounts`, `properties`, `tenants`, `deals` (constant `VALID_RETURN_TYPES` in `routers/query.py`).
- Every result row carries map-pin data: Properties/Tenants get their own lat/lng directly (Tenant rows are one-per-occupied-space, pinned to that specific property). Accounts/Contacts/Deals get their own geocoded lat/lng (null for Deal) **plus** a `linked_properties` array of `{id, lat, lng, address}` via the relevant junction (`property_parties` for accounts/contacts, the deal's own `property_id` for deals — 0 or 1 entries).
- **Geography filter assumption** (stated explicitly in code comments, not silently assumed): city/county/state filtering for Properties/Tenants/Deals applies to the property's own location; for Accounts/Contacts it applies to the entity's own city/state only — **no county filter for those two**, since neither table has a county column.

---

## Pages

Nav is built by the single `renderSidebar(activePage)` function in `frontend/js/app.js` — every page calls it; never add a per-page static nav block. Current sections:

- **Workspace:** Dashboard, **Search**, Pipeline, Lists, Query, Review Duplicates
- **Tools:** Comps, Import, Property Finder, Portfolio Intel, Client Portal

The old **Records** section (Properties / Contacts / Accounts / Tenants / Deals as five separate nav items) was removed and replaced by the single **Search** entry, which opens the unified map-driven browse page. The five underlying list pages (`properties.html`, `contacts.html`, `accounts.html`, `tenants.html`, `deals.html`) and every detail page (`property.html`, `contact.html`, `account.html`, `deal.html`, `tenant.html`) **still exist, are still routed in `backend/main.py`, and still work** — they're just no longer in the primary nav. Detail-page URLs are unchanged; Search's list rows link straight to them.

| Page | Status | Notes |
|------|--------|-------|
| Dashboard | ✅ | Pipeline funnel, upcoming closes, activity feed |
| **Search** | ✅ | Unified map + filterable list across Properties/Accounts/Contacts/Tenants/Deals; collapsible map (Zillow/Redfin-style), hover/click pin-sync, debounced live filtering via `/api/query` |
| Property detail | ✅ | Summary / Spaces & Tenants / Contacts / Public Record / Map tabs; Recorded Owner picker + Attach Public Record card |
| Contact detail | ✅ | Phones list (label · number, primary badge, inline edit), collapsible office-location mini-map (lazy-init Leaflet) |
| Account detail | ✅ | Party hub: role badges, owned/managed properties, engagements, contacts, collapsible office-location mini-map |
| Deal detail | ✅ | Commission math, co-broker splits, contacts, documents, portal create/link |
| Pipeline (engagements) | ✅ | Kanban by stage, drag-to-PUT, "+ New Engagement" with account/property typeahead + inline "create new property," listing-type "Set as recorded owner" checkbox |
| Lists (marketing lists) | ✅ | List CRUD, bulk member add (accounts/contacts) |
| Query | ✅ | Earlier general-purpose query/export tool, predates Search — still has its own nav entry, not yet folded into Search |
| Review Duplicates | ✅ | Lightbulb-sourced account-duplicate suggestions, compare-and-merge popup |
| Properties / Contacts / Accounts / Tenants / Deals (list pages) | ✅ | Functional, reachable by URL/in-app links, no longer in primary nav |
| Property Finder | ✅ | ZIP → local parcels table, circleMarker dots — kept separate from Search deliberately (parcel/public-record lookup is a different job than party/deal browsing) |
| Portfolio Intelligence | ⚠️ | Built; not independently re-verified this session (no live DB available to exercise it) |
| Client Portal | ✅ | Token-based access, per-section view tracking via `PortalView` |
| Comps | ✅ | Manual entry + CRE-platform CSV upload |
| Import | ✅ | Two systems: the sectioned general importer (Accounts/Contacts/Tenants/Deals/Comps), with a link through to the property-centric general column-mapping importer for Properties |

---

## Frontend Asset Caching (CRITICAL)

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
Plus a single shared `?v=N` query bumped together across **every** page's `/js/app.js` and `/static/main.css` references whenever either shared asset changes — currently `?v=9`. `main.css`'s own internal `@import url('tokens.css?v=N')` is a second, independent counter — bump it too whenever `tokens.css`'s *content* changes (not just whenever the page-level counter bumps for an unrelated reason). Don't bump only the page you're editing; grep for the current version across `frontend/pages/*.html` and bump all of them in the same commit, or some pages will silently keep serving a stale shared asset. HTML routes themselves are served via explicit `FileResponse` with `_NO_CACHE` headers (`no-store, no-cache, must-revalidate, max-age=0`) — `StaticFiles` can't set per-response headers reliably, which is why HTML pages get dedicated routes instead of a mount.

---

## Key Learnings & Patterns

- **SQLAlchemy FK ambiguity:** `properties` has FOUR FKs to `accounts` (`account_id`, `recorded_owner_account_id`, `manager_account_id`, `tax_bill_account_id`). Any relationship between them needs explicit `foreign_keys=`. Pin defensively on every new pair, even ones with only one FK column today (junction tables already do this preemptively).
- **`merge_accounts`'s FK list is hand-maintained, not introspected** — adding a new FK to `accounts.id` anywhere in the schema requires also adding it to that function, or merges will silently miss it.
- **Two unrelated geocoders, two different entity sets:** Nominatim (OpenStreetMap) auto-geocodes `Property.lat/lng` on save; the US Census Bureau batch/single geocoder handles `Account.lat/lng` and `Contact.lat/lng`. Don't assume one shared geocoding path when extending either.
- **`PARCELS` is raw SQL, not an ORM model** — `db_setup.py`'s `_ensure_parcels_table()` guarantees the empty table+indexes exist on every deploy (fresh or existing, idempotent), importing the DDL from `scripts/import_parcels.py` rather than duplicating it. The table existing is no longer the failure mode; **rows** are — if parcels search ever comes back empty, check whether `scripts/import_parcels.py` has actually been run against that database, not whether the table exists.
- **Auto-migrate on deploy:** silent `alembic upgrade head` output = success; check `alembic heads` against this doc's recorded head if anything seems off.
- **Render webhook flakiness:** sometimes silently stops; manual deploy re-arms it.
- **No Render shell (free tier):** any DB inspection or one-off backfill script runs from a local terminal against `DATABASE_URL`, not in-place on Render.
- **Public/assessor data is reference, not authority:** Oakland County's assessor zip may not match USPS delivery zip. Curated/manual data wins. Never auto-overwrite manually entered fields — fill blanks only. Same fill-blank-from-parent pattern governs Account→Contact address/geocode inheritance.
- **Oakland County strips owner names from ALL public data** (CSV + ArcGIS). Regrid is expected to solve this once the license is active (see **Regrid Status**).
- **ArcGIS field naming:** `Shape.area`, not `Shape__Area` — verify via wildcard `outFields=*`.
- **Hybrid architecture:** local DB for attribute/owner queries, ArcGIS for parcel geometry only.
- **Owner isolation on write, not just read:** validate any FK passed from the client belongs to the current owner before assignment. Established `_validate_account_links()` pattern in `routers/properties.py`; reuse it (or an equivalent owner-scoped lookup) anywhere a client-supplied ID gets assigned to a FK column.
- **Generic, broker-invoked, attestation-logged:** the safe pattern for any feature touching potentially-IP-bearing content (brochure parser, future Chrome extension). No source-specific detection in code; surface warnings at the moment of action; log the user's choice. Same posture as Google Drive, Dropbox.
- **Cache-busting is at the asset-URL level, not headers alone:** hard refresh bypasses browser cache but not all edge/proxy layers; the shared `?v=N` bump is the reliable fix, see **Frontend Asset Caching**.

---

## Regrid Status

- **License:** signed terms — 9-month dev license, Michigan-wide, $1,000 flat, credit applied to nationwide conversion
- **Refresh cadence:** "as available" — urban counties 4-6x/year, rural 1+x/year. Effectively quarterly-or-better on Metro Detroit.
- **Awaiting:** paperwork from Luke + Jake, then CC payment
- **Bonus:** Regrid CRO expressed inbound demand for what UpFront is building; partnership/referral conversation open for the future
- **On arrival:** one-time reconciliation script — fuzzy-match Regrid owner names against `accounts.normalized_name` (owner-scoped), set `property.recorded_owner_account_id`, fire `ensure_role('owner')`. Schema already in place.

*(This section is business/relationship status, not derivable from code — not independently re-verified this session; update it directly when the status changes.)*

---

## Tools & Resources

- **Claude Code** — primary coding interface (green local terminal)
- **Render** — hosting (free tier, no shell), auto-deploy via GitHub webhook from the `new` remote only
- **PostgreSQL** — primary database (Render-hosted)
- **FastAPI / SQLAlchemy / Alembic** — backend framework and ORM/migrations
- **Leaflet.js v1.9.4** (unpkg CDN) + **OpenStreetMap tiles** — the only mapping library, used everywhere maps appear
- **Oakland County ArcGIS API** — parcel geometry/coordinates (rate-limited)
- **Nominatim (OpenStreetMap)** — free geocoder for `Property.lat/lng`
- **US Census Bureau geocoder** — free, no API key, for `Account.lat/lng` / `Contact.lat/lng` (`backend/services/geocoding.py`)
- **Regrid** — incoming, enriched parcel data (owner names, zoning, sale history, coordinates) — see **Regrid Status**
- **rapidfuzz** — fuzzy matching: `token_sort_ratio` (account duplicate scan, threshold 65) and `partial_ratio` (Tenant matching, threshold 55)
- **Google News RSS** — tenant news feed
- **GitHub** — source control; `new` remote is the only one Render watches for auto-deploy
