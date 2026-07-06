# UpFront Broker — CLAUDE.md

## Guiding Principle (AI Strategy)

"Within the next six months, I will pursue two concrete commitments. First, I will create a simple AI review checklist for any tool I build or use professionally, including business purpose, data sources, assumptions, human review points, risk level, and stop/pivot criteria. Second, I will add an assumption audit to my AI-enabled sales workflow. Before using AI output in outreach, strategy, or leadership decisions, I will identify which claims are evidence-based, which are inferred, and which require verification."

---

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

B2B CRE broker intelligence platform for independent commercial real estate brokers in Metro Detroit. Solo-agent, IC-first — broker owns their data, fully portable. Live at **upfront-broker-bn4d.onrender.com**.

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
  - **Nominatim (OpenStreetMap)** — `Property.lat/lng`, auto-geocoded on save via a direct `urllib` call in `routers/properties.py` (no API key). Range house-number addresses (e.g. `"29551-29583 5 Mile Rd"`) are normalized inline — the first number is extracted (`"29551 5 Mile Rd"`) before the Nominatim query; the DB address is unchanged. Failures are logged as warnings (not swallowed silently). Returns `(None, None)` on any failure; property is still saved without coordinates. There is **no `geo_address` column** — normalization is purely in the `_geocode()` function at query time. Geocoding runs at all five property write sites including `attach_parcel` (added 2026-07-02). Backfill script: `scripts/backfill_property_geocoding.py` (same normalization, 1 req/s Nominatim rate-limit delay).
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
- **Current migration head:** `04aa60723785` (`add_national_locations_address_normalized`) — 25 migrations total, linear chain, no branches. Verify with `alembic heads` if this drifts.

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
- **`--hint-gold` is exclusive to the lightbulb/suggestion UI** (`main.css`'s `.hint-*` block says so explicitly in a comment). **`--dataviz-amber` / `--dataviz-amber-soft` are the categorical map/chart amber** — used by Property Finder's "Office" legend dot + matching marker badge color (`finder.html`, read live via `getComputedStyle` with a hardcoded `#A8702E` fallback) and Query's `.type-property` result badge (`query.html`). (An earlier version of this doc called this the "Commercial" legend dot — stale; the category-icon rewrite renamed the legend entries to Office/Industrial/Multifamily/Land, matching `parcel_classcode_to_property_type()`'s actual output vocabulary.) Before `--dataviz-amber` existed, both spots hardcoded the old pre-rewrite gold hex `#c9943a` directly — not literally `--hint-gold`, but the same visual conflict (a gold tone doing unrelated categorical work); both are migrated now. Industrial/Unclassified use their own literal hex fallbacks (`#0f1923`/`#8a8278`, no dedicated token), not `--accent`. **`--dataviz-purple` (`#5B4E96`, added 2026-07-06)** is a 5th categorical color, added for Property Finder's new Retail marker/legend entry (reachable only for `wayne_detroit` prospects via `parcel_usedesc_to_property_type_detroit()`, or a "yours" property whose `property_category` is Retail — see PROPERTY's `property_category` note) — deliberately shifted hue away from the existing `--role-tenant` badge color (`#7A5C8F`, also purple-family but a different, unrelated "party has the tenant role" concept) for the same reason `--owned-marker` was named apart from `--role-owner`. **`--owned-marker` (`#D32F2F`, added 2026-07-06)** is a different *kind* of token from the five categorical colors above — those distinguish property TYPE; `--owned-marker` is a semantic status override (property is already in the broker's own portfolio) that replaces whichever category color would otherwise apply, rather than sitting alongside it as a 6th category. Deliberately named `--owned-marker`, not `--role-owner`, to avoid confusion with the existing `--role-owner` account-role badge color (`#2D6B5C`, a green, an unrelated "party has the owner role" concept). If a sixth chart/map *categorical* color is ever needed, add a real token to `tokens.css` rather than reusing `--hint-gold`/`--dataviz-amber`/`--dataviz-purple`/`--accent`/`--owned-marker`/`--role-*` or hardcoding a hex value inline.

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
property_type, property_category, subtype, status (Active/Off Market/Sold/Leased), market, submarket,
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

**`property_category`** — derived from `property_type` via pattern/keyword matching in `backend/services/property_category.py`, **not client-settable** (absent from `PropertyCreate`/`PropertyUpdate`, present only on `PropertyResponse`). Recomputed at every write site that can change `property_type`: `create_property`, `update_property` (only when `property_type` is in the update payload), `attach_parcel` (classcode-derived type), and both bulk importers (`routers/imports.py`, `routers/import_properties_parties.py`).
- **10 categories:** Multi-Family, Office, Industrial, Retail, Health Care, Hospitality, Flex, Land, Sports & Entertainment, Specialty — plus `"Uncategorized"` (matched nothing) and `NULL` (property_type itself was blank — never forced into a bucket).
- Pattern-based on purpose: future imports bring `property_type` values this app has never seen; a literal lookup of today's exact strings would leave them all `NULL`/`Uncategorized` forever. `"General Retail"` (with or without a parenthetical subtype) matches by prefix; everything else matches by case-insensitive substring containment, first rule wins.
- **Judgment call, deliberately flagged as revisitable:** Flex's `"tech/r&d"` pattern is checked *before* Office's bare `"r&d"` pattern, so a compound `"Tech/R&D"` property_type lands in Flex, not Office — this is the opposite of the order the two categories are normally listed in. CoStar's own glossary lists Flex under both Industrial and as its own category inconsistently; nothing in the data seen so far forces a different decision. If real Flex inventory shows up and this ordering turns out wrong, it's a one-line fix in `_CONTAINS_RULES` in `services/property_category.py` — not a sign anything else is broken.
- Unmatched values fall back to `"Uncategorized"` and log a warning (not silently swallowed) — `routers/imports.py` and `routers/import_properties_parties.py` additionally collect the **distinct** set of unmatched `property_type` values seen during a run and return them as `uncategorized_property_types` in the import response, so what's actually falling through is visible without grepping logs.
- One-time backfill for properties that predate this column: `scripts/backfill_property_category.py` — imports (doesn't reimplement) `categorize_property_type` from `backend/services/property_category.py` via the same `sys.path` trick `db_setup.py` uses, so a backfilled row can never categorize differently than a freshly-saved one.
- Search page's Property Type filter (`/pages/search.html`) filters by `property_category` (exact match), not `property_type` — selecting "Retail" returns every `"General Retail*"` subtype variant in one shot, which was the point.
- **`parcel_classcode_to_property_type()` vs. `parcel_usedesc_to_property_type_detroit()` (Property Finder display only, 2026-07-06):** these are two *separate* classifiers in `services/property_category.py`, both distinct from `categorize_property_type()` above (that one drives the real `Property.property_category` column; these two drive `parcels_regrid` prospect display in `finder.py`'s `_parcel_from_regrid_row()` only — no write path). `parcel_classcode_to_property_type()` (8 standard 3-digit MI codes → Office/Industrial/Multifamily/Land, no Retail) is unchanged. A live-data recon confirmed standard counties (Oakland, Wayne non-Detroit, Washtenaw, Livingston, Genesee) have **no reliable retail signal**: `usedesc` is null for 67% of `usecode=201` rows and the populated remainder is boilerplate ("COMMERCIAL", "201-COMMERCIAL IMPROVED"); `zoning_subtype` was also tested and rejected (95% of usedesc-confirmed retail parcels there are zoned "General Commercial", not anything retail-specific). Those counties still have **no Retail output** and keep using `parcel_classcode_to_property_type()` untouched. `wayne_detroit` (76,437 rows) is different — its `usedesc` is real, specific, and populated (STORE-RETAIL, SHOPPING CENTER, SUPERMARKET, DRUG STORE, RESTAURANT, BANK BRANCH, BAR, GAS STATION variants, OFFICE BLDG variants, WAREHOUSE variants, TWO/THREE/FOUR/FIVE/SIX FAMILY, APT variants, DUPLEX, VACANT COMMERCIAL/INDUSTRIAL) — so `parcel_usedesc_to_property_type_detroit()` keyword-matches it (case-insensitive substring, first rule wins) into Retail/Office/Industrial/Multifamily/Land/`None`. `_parcel_from_regrid_row()` branches on `row.source_county == 'wayne_detroit'` to call the new function instead of the classcode one — **this also closes a latent bug** flagged in the recon that led to this change: the classcode function was previously called unscoped on every parcel including Detroit's, with no county-awareness to prevent a 5-digit Detroit code (some with leading zeros that vanish under `int()`, e.g. `"00003"` → `3`) from numerically colliding with one of the 3-digit standard keys. `attach_parcel()` in `routers/properties.py` still calls the classcode function unscoped, but only against the legacy Oakland-only `parcels` table (never Detroit's scheme), so no collision risk there today — **if `attach_parcel` is ever extended to source from `parcels_regrid` instead, it needs the same `source_county` branching, and separately still carries the pre-existing re-classification-on-re-attach risk flagged in earlier recon** (no fill-blank guard on `property_type`, and the UI never hides the "Attach Public Record" search once a parcel is attached) — both out of scope for this change, noted here as follow-ups. **Standard-county retail detection remains a real, separate, unsolved gap** — the leading candidate mechanism there is Overture `national_locations` brand-matching against known retail chains (a fundamentally different signal than usedesc/zoning parsing), not attempted in this change.

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
entity_id_a (FK → accounts.id, CASCADE, required),
entity_id_b (FK → accounts.id, CASCADE, NULLABLE),
score (Numeric 5,2), reasoning, evidence (JSON),
status (new | dismissed | merged), created_at, resolved_at
```
Two producers now: the account-duplicate scanner (`POST /api/accounts/scan-duplicates`, rapidfuzz `token_sort_ratio` on `normalized_name`, threshold **65** — constant `DUPLICATE_SCAN_THRESHOLD` in `routers/accounts.py`, both `entity_id_a`/`entity_id_b` populated), and the Regrid owner-match reconciler (`POST /api/regrid/reconcile`, `suggestion_type="regrid_owner_match"`, `entity_id_a` = candidate matched account, `entity_id_b` = **NULL** — the other side of that comparison is a `parcels_regrid` row, not an `accounts.id`, so it lives in `evidence.parcel_regrid_id`/`evidence.parcel` instead — see **PARCELS_REGRID** below). `entity_id_b` was made nullable (migration `432360b14f75`) specifically to support this second producer; an earlier version of this doc predicted this exact need before building it. `routers/suggestions.py`'s `dismiss_suggestion()` has one `suggestion_type`-specific side effect: for `regrid_owner_match`, it also flips the linked `parcels_regrid` row to `reconciliation_status='no_match'`. Confirm/create-account actions for that suggestion type live in `routers/regrid.py` instead (materially different business logic, not a fit for this generic router). UI: lightbulb icon on Accounts list/detail (account_duplicate only, via `Hints.bulb()`) and the "Review Duplicates" page, which now has two tabs (Account Duplicates / Regrid Hints) — see **PARCELS_REGRID**.

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
- All access to the legacy `parcels` table in `backend/routers/finder.py` is raw `db.execute(text("..."))` SQL, not the ORM. The one exception is `get_public_record()` (added 2026-07-02), which queries `parcels_regrid` via the ORM (`ParcelRegrid`), matching how `services/regrid.py` already interacts with that specific table.
- **CONFIRMED (2026-06-29):** In production the `parcels` table is empty, so `/api/finder/parcels` falls through to LIVE Oakland County ArcGIS calls on every request — making parcel data dependent on ArcGIS uptime and rate limits. Regrid ingestion into `parcels_regrid` is the intended replacement for this live-ArcGIS dependency: once populated, `parcels_regrid` becomes the local parcel source (geometry + owner included), removing the per-request external dependency for covered counties. **Superseded — as of 2026-07-06, `/api/finder/parcels?zip=` (Property Finder's ZIP search) is fully `parcels_regrid`-backed**, not the old local-`parcels`/ArcGIS path this paragraph originally described as still-pending; that migration happened in an earlier session and this doc had drifted. `_get_parcels_legacy_arcgis()` (the old function) is kept in `finder.py` but is dead code, unreachable from any route. The property detail Public Record tab (`GET /api/finder/public-record/{property_id}`) separately reads `parcels_regrid` first, ArcGIS as fallback — see PARCELS_REGRID's 2026-07-02 update above. `property.html`'s "Show Nearby Parcels" Map tab toggle also hits `/api/finder/parcels?zip=`, so it too is now `parcels_regrid`-backed, unchanged code, just a different data source underneath.
- `name1`/`name2` NULL in Oakland County's public data — Regrid is expected to fill these.
- **Property Finder unified search (2026-07-06):** `GET /api/finder/parcels` now merges the broker's own owner-scoped `properties` ("yours") with `parcels_regrid` prospects ("prospect") into one ranked/deduped list, instead of the old `exists_in_db` boolean-flag/opacity-dimming approach. Two independent, small, capped queries (`_parcel_from_regrid_row()` / new `_property_row_to_finder_shape()` in `finder.py`) are shaped into one common dict contract and merged in Python — not a SQL `UNION` — because `normalize_address()` (the dedupe key) is Python-only and the two tables' column shapes are too different for a clean `UNION`; this follows the same per-source-shaping pattern the `/api/query` engine already uses. Dedup: if a "yours" property and a "prospect" parcel normalize to the same address, only "yours" is kept — the prospect is dropped, not shown twice. The dedupe address-set itself is deliberately **unfiltered** (every one of the broker's properties regardless of the current search's price/size filters), so a prospect is correctly dropped even when the matching owned property falls outside this particular search's range.
  - Filter param compatibility for the new `Property` side of the query: `zip`/`city`/`street` map directly; `assessed_value_min/max` maps directly (confirmed same dollar concept, not just same field name — `attach_parcel` and Finder's own `/add` endpoint both already write `Property.assessed_value` straight from parcel data); `sale_price_min/max` maps to `Property.last_sale_price`; `lot_acres_min/max` converts `Property.sf_land / 43560.0` (Property stores land size in **square feet**, Regrid in **acres** — a real unit mismatch, handled at query time, not by adding a new column). `owner` and `usecode` have no `Property` equivalent (no owner-name text field; no county classcode column) and are simply skipped for that side of the query, not treated as errors.
  - `_property_row_to_finder_shape()` sets `property_type` from `Property.property_category` (already computed/stored — see property_category's own note above), **not** `parcel_classcode_to_property_type()` — that function's input is a raw county classcode, which `Property` doesn't have a column for; it already stores its own classification directly. `finder.html` aliases the one vocabulary mismatch (`'Multi-Family'` → the badge system's `'Multifamily'` key) client-side; every other `property_category` value that isn't one of the 4 badge categories (Office/Industrial/Multifamily/Land) falls through to the same Unclassified badge any unrecognized prospect type already gets.
  - Response now includes `yours_total`, `prospect_total`, `yours_missing_coords` (count of "yours" results excluded from the map for lacking `lat`/`lng` — a live DB check on 2026-07-06 found 121/1,453 properties, 8.3%, null, matching the already-tracked Nominatim geocode gap) alongside the existing `parcels`/`total`/`zip` fields.
  - Frontend: the old opacity-dimming (0.55) for `exists_in_db` is retired — a "yours" result is now a first-class merged entry, not a de-emphasized duplicate sitting next to a separate prospect pin. **Superseded again, same day (2026-07-06):** the first pass replaced dimming with an additive corner checkmark badge (`.yours-badge`, `var(--accent)`); that was itself replaced with a **fill-color override** — `--owned-marker` (`#D32F2F`, a red distinct in hue from all 4 category colors) replaces the marker's category color entirely for any "yours" result, while the glyph/shape still comes from `property_type` as before (shape = type, color = ownership). The checkmark badge and `.yours-badge` CSS class are removed entirely — one signal, not two stacked. `openPanel()` branches on `parcel.source` ("yours" vs "prospect"): a "yours" panel shows real CRM-summary fields — `status`, `asking_price`, `cap_rate`, `assessed_value`, `sale_price`, building SF/year built/units/lot acres/zoning, and `tenant` (a single free-text occupant field on `Property`, not the full `property_tenants` roster — that would need a per-property join, not "cheap") — plus a direct link to `/property.html?id={property_id}`, instead of the generic regrid-only fields/link it showed before. A dismissible banner near the result count surfaces the `yours_missing_coords` count honestly rather than silently dropping those pins with no explanation.
  - **Live Regrid enrichment for "yours" results (2026-07-06):** a "yours" pin only carries stored `Property` fields by default — it lost the live `parcels_regrid` data (assessed_value, sale_price, usecode, zoning, etc.) it used to show back when it was just a dimmed regrid pin. Fixed by extracting `get_public_record()`'s own matching logic (opportunistic `parcel_id` match, then zip-scoped `normalize_address()` match, both scoped to the property's own `source_county` via `_property_source_county()`) into a shared `_match_parcel_regrid_for_property(db, prop)` helper — reused by both `get_public_record()` (unchanged response shape) and `get_parcels()`'s "yours" loop, rather than a second implementation of the same matching. When a match exists, `_public_record_subobject()` attaches a `public_record` sub-object (`assessed_value`, `sale_price`, `sale_date`, `usecode`, `usedesc`, `lot_acres`, `zoning` — a compact subset of `ParcelRegrid` columns, distinct from `get_public_record()`'s own richer response shape, which serves the full property detail page's Public Record tab, a separate UI surface). When no match exists, the key is omitted entirely — never fabricated as nulls/zeros. `finder.html`'s `openPanel()` renders a labeled "Public Record" section below the CRM fields only when `parcel.public_record` is present; nothing extra otherwise (no "not found" message — that's the full property page's Public Record tab's job). Accepted cost: one extra per-property match lookup for every "yours" result in a search — same nested-query-per-row tradeoff `scan_duplicates()`/`reconcile()` already accept elsewhere in this app, not re-optimized here.

**Oakland County CLASSCODE map** (`backend/routers/finder.py`):
```
401 → Residential          407 → Residential Vacant Land
402 → Residential Condo    403 → Residential Apartment
201 → Commercial           202 → Commercial Condo
207 → Commercial Vacant    203 → Commercial Other
301 → Industrial           302 → Industrial Condo
101/102 → Agricultural     001/002/006 → Exempt
```

### PARCELS_REGRID (multi-county Regrid reconciler — distinct from PARCELS above)
```
id, parcel_id (text, not null), owner_raw, owner_normalized,
address, city, state, zip, county,
geometry_wkt (raw WKT string — no PostGIS, deferred deliberately),
raw_data (JSON — every Regrid column not pulled into a dedicated field above),
ingested_at, source_county (text, not null),
reconciliation_status (default 'pending': pending | auto_linked | suggested | no_match),
matched_account_id (FK → accounts.id, SET NULL), matched_property_id (FK → properties.id, SET NULL)

Indexes: owner_normalized, parcel_id, reconciliation_status
Unique: (parcel_id, source_county)
```
Built **2026-06-24, entirely against synthetic data** — Regrid hasn't delivered a real county CSV yet (expected the following week; see **Regrid Status**). Everything below, especially the exact column-name guesses, needs verification the moment a real file lands — flagged explicitly rather than buried, per this file's maintenance rule.

- **Why a second parcels table:** the existing `PARCELS` table above is Oakland-County-only with a fixed raw-SQL schema (Oakland's specific assessor export shape). Regrid ships one CSV per Michigan county (83 total) on its own ~191-column standardized schema — a structurally different shape, different source, different cadence. Reusing `PARCELS` would mean cramming a different schema into Oakland-specific columns; `parcels_regrid` is a clean SQLAlchemy model instead (migration `432360b14f75`).
- **No `owner_id`** — same reasoning as `ENRICHMENT_CACHE` below and the legacy `PARCELS` table: raw parcel facts (owner name, address, geometry) are shared public-record reference data, the same regardless of which broker looks them up, not a per-broker entity.
- **Full-schema retention via `raw_data` JSON:** ingestion (`backend/services/regrid.py: ingest_csv()`) never enumerates or hardcodes Regrid's ~191 columns. It pulls out only the matching-critical ones (below) into dedicated columns and dumps everything else into `raw_data` untouched, so nothing is lost and future enrichment/agent use can read any column without a schema change.
- **Matching-critical column names** — confirmed where stated against Regrid's public schema docs (support.regrid.com/parcel-data/schema); their full schema spreadsheet 404'd when fetched for this build, so the long tail of ~191 names is unconfirmed. `_first_present()` in `services/regrid.py` tries each candidate in order, case-insensitively:
  - `parcelnumb` — **CONFIRMED** (Regrid's primary parcel-number field).
  - `keypin` — **NOT a Regrid field.** It's this app's own legacy `PARCELS` table's primary key column name. Kept only as a fallback because the original task spec named it explicitly. If `parcelnumb` is ever blank on a real row, Regrid's actual fallbacks are reportedly `parcelnumb_no_formatting` / `state_parcelnumb` / `account_number` / `tax_id` — **unconfirmed, verify against the first real county CSV.**
  - `owner`, `address` — **CONFIRMED.**
  - `city`/`scity`, `state`/`state2`, `zip`/`szip`, `county`/`county_name` — first name in each pair seen directly in Regrid's docs/API examples; the second is a same-doc-sourced fallback, not independently confirmed.
  - `geometry`/`geom`/`wkt` — Regrid confirms WKT, EPSG:4326 is the geometry format; the literal CSV column name is unconfirmed.
- **Ingestion is a streaming UPSERT**, keyed on `(parcel_id, source_county)`: reads the upload via the raw file handle (`UploadFile.file`, not `await file.read()`) wrapped in `io.TextIOWrapper` + `csv.DictReader`, so a multi-hundred-MB county file never has to fit in memory at once; commits every 500 rows. Re-running ingestion for a county (Regrid's quarterly-ish refresh) updates the raw columns on existing `(parcel_id, source_county)` rows in place — it deliberately never touches `reconciliation_status`/`matched_*_id`, so a refreshed file can't silently undo a confirmed match. A row missing both `parcelnumb` and `keypin` is skipped (collected in the response's `errors[]`, capped at 100 entries) since `parcel_id` is `NOT NULL`.
- **Reconciliation is a separate step**, `POST /api/regrid/reconcile`, scoped to the calling owner's accounts/properties only (never another owner's — enforced via `owned_accounts_query()` / `Property.owner_id` filters, same as everywhere else in this app) and optionally to one `county`. Moderate decision thresholds, applied per pending row:
  - owner-name `token_sort_ratio` (reusing the duplicate scanner's exact rapidfuzz approach, not a parallel implementation) **≥ 95** *and* the parcel's address normalize-matches an existing property (reusing `normalize_address()`, promoted from the property importer into `services/naming.py` alongside `normalize_name()` specifically so this and the importer share one real function instead of two copies) → **auto_linked**: sets `matched_account_id`/`matched_property_id`, and — mirroring the Public Record tab's existing behavior — sets `properties.recorded_owner_account_id` and fires `ensure_role(account, 'owner')`.
  - owner score **≥ 65** (and not auto-linked) → **suggested**: writes a row to the existing `SUGGESTIONS` table (`suggestion_type="regrid_owner_match"`, see above) rather than a parallel table.
  - otherwise → **no_match**. Optional `auto_create_accounts` flag (request body, **default `false`**) creates a fresh `Account` from the Regrid owner string instead of leaving the row stranded — defaults off so the first real run against an actual county doesn't flood the accounts table with one new account per unmatched parcel before anyone's reviewed the shape of the data.
- **Known scaling gap, accepted deliberately for this pass:** reconciliation is an O(pending_rows × owner_accounts) nested loop — the exact same tradeoff `scan_duplicates` already accepts in this codebase (see that function's docstring in `routers/accounts.py`). Wayne County alone is several hundred thousand parcels; a full-county reconcile call against an owner with many accounts will be slow. Not addressed now — scope `reconcile` calls by `county` to keep each call bounded, same as before blocking/batching gets built.
- **Known multi-tenant gap, accepted deliberately for this pass:** `matched_account_id`/`matched_property_id`/`reconciliation_status` are single columns on `parcels_regrid`, not owner-scoped (the table has no `owner_id` — see above). If this app ever has more than one `owner_id` reconciling against the *same* county's data, the first owner to resolve a row flips it out of `'pending'` and no other owner's `reconcile()` call will ever see that row again. Fine for this app's current solo-broker-per-deployment shape; would need an owner-scoped junction table (like `property_parties`, not a single FK column) to support more than one owner sharing the same ingested county data.
- **Suggestion UI** — "Review Duplicates" page (`frontend/pages/review-duplicates.html`) now has two tabs: "Account Duplicates" (unchanged) and "Regrid Hints" (`suggestion_type=regrid_owner_match`). `frontend/js/app.js`'s `Hints` module is extended, not duplicated — `Hints.open()` branches on `suggestion_type` to render either the original two-account comparison or a parcel-vs-candidate-account comparison, reusing the same modal harness and `.hint-card`/`.hint-compare`/`.hint-actions` CSS. Three actions: "Confirm match" (`POST /api/regrid/suggestions/{id}/confirm` — applies the same link auto-link would have), "Create as new account instead" (`POST /api/regrid/suggestions/{id}/create-account`), "Not a match — dismiss" (reuses the existing generic `POST /api/suggestions/{id}/dismiss`, extended per the SUGGESTIONS note above).
- **`merge_accounts`** (`routers/accounts.py`) now also re-points `parcels_regrid.matched_account_id` when merging two accounts — added to that function's hand-maintained FK list in the same commit that added the column, per this file's Coding Rules note on that function.
- **Built and tested against synthetic data only**, ahead of real Regrid CSVs (see **Regrid Status**): `tests/fixtures/regrid_sample_wayne.csv` (generated by `scripts/generate_regrid_fixture.py`, not hand-edited — re-run that script if the row design needs to change) is 191 columns × 20 rows, designed and rapidfuzz-verified to produce exactly 5 `auto_linked` / 8 `suggested` / 7 `no_match` against five seeded test accounts/properties. `scripts/test_regrid_reconciler.py` is a one-shot, no-pytest-required runner (`python scripts/test_regrid_reconciler.py`) that seeds the test data, runs ingest→reconcile, prints the expected-vs-actual split, and cleans up after itself; `tests/test_regrid_reconciler.py` (pytest — first test suite in this repo, see `pytest.ini` and `backend/requirements-dev.txt`) imports and reuses that same `run_verification()` rather than re-seeding. Both run against the real `DATABASE_URL` (same convention as the one-off `scripts/backfill_*.py` files) — there is no SQLite/mock-DB indirection, so point `DATABASE_URL` at a local/dev database before running either. **Not independently executed this session** — built and statically verified (imports cleanly, routes register, pytest collects all 7 tests with zero import errors, FastAPI request-parsing for both endpoints verified directly, rapidfuzz score bands verified directly) on a sandbox with no local Postgres available; running them for real against a live database is the next step.

### NATIONAL_LOCATIONS (Overture Maps Places — **background** reference dataset)
```
id, overture_id (text, unique), brand_primary, brand_normalized,
name_primary, category_primary, category_top,
address, city, state, zip,
lat, lng (Numeric 9,6),
websites (JSON), phones (JSON),
confidence (Numeric 4,3),
raw_data (JSON — all extracted Overture fields except geometry binary),
release_version (text, e.g. "2026-06-17.0"),
ingested_at timestamptz default now()

Indexes: overture_id (unique), brand_normalized, category_top,
         (state, city), (lat, lng)
```
- **Product framing: background, not foreground.** national_locations is infrastructure that *supports* the broker's own data — it never competes with Properties/Accounts/Contacts/Tenants/Deals for primary attention. The broker interacts with it via (a) the **NatLocs map layer toggle** (any map surface — shows amber pins for nearby retail/restaurants) and (b) the **per-pin "Find owner via public records"** button (cross-references the pin's address against `parcels_regrid`). It does NOT appear as a top-level Search record type (the "Locations" dropdown option was intentionally removed from `search.html`; the backend query path `VALID_RETURN_TYPES` keeps `national_locations` for future agent use, but the UI no longer exposes it directly).
- **No `owner_id`** — same reasoning as `ENRICHMENT_CACHE` and `PARCELS_REGRID`: a Starbucks at 123 Main St is the same regardless of which broker looks it up. Owner-scoping happens via `property_national_location_links` below.
- **Source:** Overture Maps Foundation, Places theme (`s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*`). Michigan-only: bbox + `addresses[1].region = 'MI'`. Quarterly-ish release cadence; see **Quarterly refresh** below.
- **Ingestion:** `scripts/ingest_overture_michigan.py` — uses DuckDB's httpfs extension to query Parquet files directly from public S3 (no download, no API key). Streams in 1000-row batches, UPSERTs by `overture_id`. Run: `DATABASE_URL="..." python3 scripts/ingest_overture_michigan.py`. Set `OVERTURE_RELEASE=YYYY-MM-DD.N` to override auto-detection (STAC catalog → S3 listing fallback). **Run `scripts/backfill_national_location_links.py` after the first ingest** to populate links for properties that already existed.
- **`GET /api/national-locations/in-bbox` response shape** — 10 fields per item: `id`, `brand_primary` (null ~60%), `name_primary` (always set), `category_top` (Overture top-level), `category_primary` (leaf, e.g. `'fast_food_restaurant'`), `address`, `city`, `lat`, `lng`, `website` (bare hostname from `websites[0]`, e.g. `'mcdonalds.com'`, or null). Added `category_primary` and `website` (2026-06-25) to support the two-level segment filter panel and logo rendering in `national_locations_layer.js`.
- **`frontend/js/broker_segments.js`** — client-side segment taxonomy: `SEGMENTS` (15 named segments), `LEAF_TO_SEGMENT` (maps category_primary leaf → segment id), `segmentForLeaf(cat_primary, cat_top)` returns the segment id or `"other_<category_top>"` catch-all. Every location belongs to some visible group — unmapped leaves roll up to "Other <Top>" so no location vanishes from the map.
- **Ingestion filter uses `taxonomy.hierarchy[1]` (1-based in DuckDB SQL), NOT `categories.primary`.** `categories.primary` is the leaf node (e.g. `'fast_food_restaurant'`, `'gas_station'`), not a hierarchical prefix. The taxonomy's top-level is in a separate `taxonomy.hierarchy` array. The initial ingestion used the wrong field with wrong assumed names, producing only 6,146 rows (mostly catch-all leaf values that happened to match by accident). The correct top-level names are **confirmed from live Overture 2026-06-17.0 data** (verified 2026-06-25). Do not revert to `categories.primary ILIKE` filtering.
- **Category scope — confirmed Overture 2026 top-level taxonomy names (`INCLUDE_TOP_LEVELS` in the script):**
  - `food_and_drink` — restaurants, cafes, bars, coffee shops, fast food. **NOT** `eat_and_drink` (the old assumed name that doesn't exist in Overture 2026).
  - `shopping` — retail stores, pharmacies (under `shopping > specialty_store > pharmacy`), grocery, clothing, auto parts, discount stores. **NOT** `retail`.
  - `travel_and_transportation` — gas stations (`fueling_station > gas_station`), repair shops (`vehicle_service > automotive_repair`), car washes. **NOT** `automotive`.
  - `lifestyle_services` — beauty salons, hair salons, nail salons, spas, barbers. **NOT** `beauty_and_spa`.
  - `services_and_business` — sub-filtered to `SERVICES_BUSINESS_LEAVES` (see below); the full top-level has ~70K rows in Wayne County alone including non-CRE-relevant categories.
  - EXCLUDED: `health_care`, `cultural_and_historic`, `sports_and_recreation`, `community_and_government`, `education`, `arts_and_entertainment`, `lodging`, `geographic_entities`.
- **`services_and_business` sub-filter (`SERVICES_BUSINESS_LEAVES` in the script) — confirmed from live Wayne County data 2026-06-25:** `atms`, `bank_credit_union`, `banks`, `credit_union`, `money_transfer_services`, `financial_service`, `financial_advising`, `insurance_agency`, `tax_services`, `mortgage_broker`, `mortgage_lender`, `check_cashing_payday_loans`, `installment_loans`, `post_office`, `shipping_center`, `package_locker`, `self_storage_facility`, `storage_facility`, `laundromat`, `dry_cleaning`, `car_rental_agency`, `rental_kiosks`, `employment_agencies`, `commercial_real_estate`, `property_management`. Scope covers both retail storefronts AND office-tenant chains (Edward Jones, OneMain Financial, Allstate, H&R Block). **Excluded from this sub-filter** (too noisy): `real_estate_agent`/`real_estate` (individual agents, not offices), `lawyer`/`legal_services` (solo attorneys), `professional_services` (catch-all), `accountant` (individual-heavy), `courier_and_delivery_services` (fleet/gig), `coworking_space` (mislabeled in Overture data), `marketing_agency`/`advertising_agency`/`software_development`/`it_service_and_computer_repair`.
- **`category_top`** — now sourced directly from `taxonomy.hierarchy[1]` in DuckDB (e.g. `'food_and_drink'`, `'shopping'`), not derived in Python. The old `categories.primary.split(".")[0]` derivation was removed; it returned the leaf value unchanged since there are no dots in leaf category names.
- **`categories.primary`** (leaf node) is stored in the `category_primary` column for full detail — e.g. `'fast_food_restaurant'`, `'gas_station'`, `'beauty_salon'`.
- **Known source data quality issue — inconsistent brand tagging across major chains:** Overture's `brand.names.primary` coverage varies wildly by chain, verified against Michigan retail data after the first production ingest (2026-06-25):
  - **CVS**: 207 locations tagged (171 "CVS Pharmacy" + 34 "CVS Beauty" + 2 "CVS Health") — matches expected MI footprint. ✓ Reliable.
  - **Walgreens**: 28 locations tagged — should be ~200 in Michigan. Real Walgreens stores exist in the dataset with correct addresses but `brand = null`. Off by ~85%. ✗ Unreliable.
  - **Rite Aid**: 5 locations tagged — should be 100+. ✗ Unreliable.
  - Other chains with good coverage (anecdotally): McDonald's, Subway, Dollar Tree, gas station chains (Shell, BP, Speedway), Edward Jones.

  This is not a script bug — `TRY(brand.names.primary)` extracts correctly; the field is genuinely absent in Overture's source data for the affected rows. Cannot be fixed downstream.

  **Product framing implication:** "find every Walgreens in Michigan" will return a small fraction of reality. Do not present Overture pin counts as authoritative chain footprints — present them as *Overture-tagged* locations only. The chain-prospecting workflow is reliable for chains Overture tags consistently and misleading for chains with sparse coverage. Do not show a message like "247 Walgreens in Michigan" or similar implied completeness.

  **Future mitigation paths** (not built, documented for future sessions):
  - Brand normalization backfill: pattern-match `names.primary` against a known chain name list (e.g., `names.primary ILIKE '%walgreens%'`) and backfill `brand_primary` / `brand_normalized` for matching rows. Non-destructive — leaves rows with correct existing brands untouched.
  - Supplement with a paid data source (SafeGraph, Foursquare Places) for major chains specifically.
  - Broker corrections in the UI: surface a "suggest brand" action so brokers can flag known chains that show as unbranded.
- **`brand_normalized`** — reuses `normalize_name()` from `services/naming.py` (the same function that normalizes `accounts.normalized_name` and Regrid owner names) for consistent fuzzy matching if ever needed.
- **Quarterly refresh procedure:** Re-run `scripts/ingest_overture_michigan.py` against the new release. The UPSERT on `overture_id` updates existing rows in place (all non-ingested_at columns) without duplicating. Overture IDs became UUIDs in the 2025-06-25 release (stable per their announcement); prior releases used a different GERS-format ID — if a release ever resets IDs, a full truncate+reingest would be needed.
- **Schema — confirmed from live Overture 2026-06-17.0 data (2026-06-25):**
  - `brand.names.primary` — confirmed from full McDonald's row dump: `brand = {'wikidata': None, 'names': {'primary': "McDonald's", ...}}`.
  - `taxonomy.hierarchy` — confirmed present; `[1]` (1-based) = top-level (e.g. `'food_and_drink'`), `[2]` = mid-level, `[3]` = leaf.
  - `addresses[1].{freeform,locality,region,postcode,country}` — confirmed from live data; 1-indexed in DuckDB SQL; `len(addresses) = 1` for all Michigan places sampled.
  - `bbox.xmin`/`bbox.ymin`/`bbox.xmax`/`bbox.ymax` — confirmed current 2026 names (older alpha releases used `minx`/`miny`).
  - `websites`/`phones` — may be JSON strings or native arrays; script handles both.

### REGRID OAKLAND PILOT — findings 2026-06-29

- **Ingest pipeline VALIDATED:** streamed 245k Oakland rows cleanly (zero parse errors, ~350 rows/s, schema mapping correct: parcelnumb/owner/address/szip5/wkt all landed). The ingest code works.
- **STORAGE DOES NOT SCALE IN-DB:** 245k rows = 602MB. Full Oakland ~1.2GB; national_locations is 191MB; all broker business data combined is <4MB. The production Postgres (small tier) ran OUT OF DISK at ~245k rows — DiskFull, mid-Oakland. Statewide (83 counties) parcel data is tens of GB and will NOT fit this tier.
- **`parcels_regrid` was DROPPED to recover the full disk** (recreates empty via `db_setup.py` on deploy).
- **RESOLVED ARCHITECTURE DECISION (2026-06-29):** Parcel data will live in a **SEPARATE, dedicated Postgres instance** — NOT in the main app DB. Rationale: business data (<4MB, hot/transactional) and parcel reference data (GBs, cold/rarely-queried) have opposite shapes; co-locating them caused tonight's DiskFull incident. Separation guarantees parcel data can never again threaten broker data, while keeping full Postgres/PostGIS querying (geometry + owner lookup are required, so object storage / flat-file lookups are ruled out).
  - **SCOPE:** load ONLY the ~5 Metro Detroit counties brokers actually work — Oakland, Wayne, Macomb, Washtenaw, Livingston (~4–7GB total, fits a modest paid tier). NOT statewide/83 counties. Add a county on-demand when a broker actually needs it.
  - The main app DB keeps the existing live-ArcGIS fallback for any county not yet loaded.
  - Host TBD (Render second instance, or Neon/Supabase for the parcel DB specifically) — that's an optimization, the architecture is "separate parcels Postgres" regardless.
  - **BUILD TRIGGER:** do NOT stand up this infrastructure until AFTER the Regrid commercial conversation succeeds (payment not yet made; Oakland data is 2024-06 vintage — confirm freshness + terms before paying for new infra). Architecture is decided; building waits on the Regrid go/no-go.
- **Also pending:** rotate the production DB password (exposed during this session's debugging).

- **UPDATE 2026-07-02 — filtered ingest into the MAIN DB, deviating from the "separate Postgres instance" plan above:** `backend/services/regrid_usecode_filter.py` was added — a per-county SFR/vacant-residential drop filter (standard MI counties: drop usecode 401/402/407; Detroit's own 5-digit scheme: drop 41110/00003; Macomb: no reliable filter exists yet — see that file's docstring for why — every row would be tagged `source_note=macomb_unfiltered` instead of filtered). Filtering cut per-county row counts enough (~30K–102K per standard/Detroit county vs. Oakland's unfiltered 245K that caused the DiskFull incident above) that `scripts/ingest_regrid_metro.py` was run against the **main production DB**, not a separate instance. `parcels_regrid` itself had to be recreated first via a **targeted single-migration Alembic re-run** (`stamp 81816f53fdda` → `upgrade 432360b14f75` → `stamp head`), not a full `downgrade`/`upgrade` round-trip — the naive round-trip would have run `1323d6d9faea`'s `downgrade()`, which drops `national_locations` and `property_national_location_links` (both hold real ingested data), so it was rejected. Six of the seven files were ingested (**Oakland, Washtenaw, Livingston, Wayne, Wayne-Detroit, Genesee — ~215K rows total**); **Macomb was deliberately NOT ingested** (its unfiltered volume, 332,871 rows, was judged not worth the disk risk without a real filter). The "separate Postgres instance" resolution immediately above has NOT been carried out — this deviates from that plan and should be revisited if more counties are added or Macomb's filter gets solved, since disk headroom on the main DB isn't unlimited.
- **`GET /api/finder/public-record/{property_id}`** (routers/finder.py) reads `parcels_regrid` first — opportunistic `parcel_id` match, then zip-scoped `normalize_address()` exact match (reusing the same function `services/regrid.py`'s `reconcile()` already uses, run in the opposite direction) — falling back to the legacy local-`parcels`/live-ArcGIS 3-step lookup (`get_parcel_by_keypin`) only for counties `parcels_regrid` doesn't cover yet (Macomb). Backs the property detail Public Record tab; read-only against `parcels_regrid`, no writes. **Extended 2026-07-06** (see the field-sync bullet below) to also merge in `_public_record_subobject()`'s fields (assessed_value, sale_price, sale_date, usecode, usedesc, lot_acres, zoning — the same enrichment already built for Property Finder's "yours" pins, reusing the matched row rather than re-querying), plus two new fields specific to this endpoint: `bldg_sqft` (via the shared `_bldg_sqft_from_raw_data()` extraction) and `derived_property_type` (via the shared `_derive_property_type_for_parcel()` branching — `parcel_usedesc_to_property_type_detroit()` for `wayne_detroit`, `parcel_classcode_to_property_type()` otherwise, same branching `_parcel_from_regrid_row()` uses).
- **Public Record → Property field-sync (2026-07-06):** property.html's Public Record tab can now push a Public Record value onto the actual `Property` row, per-field rather than one "Accept All" button (the four candidate fields have genuinely different mechanics/risk — see the recon report). An accept affordance only renders when a field's Public Record value differs from (or fills a null in) the stored value.
  - **Owner** (`recorded_owner_account_id`, a FK→Account — not a scalar field) — `renderRecordedOwner()` shows "Public Record shows: X · Use this" next to "Change" when `PUBLIC_RECORD.owner` case-insensitively differs from the linked account's name. Calls **`POST /api/finder/public-record/{property_id}/accept-owner`** (new endpoint — this field genuinely needs one, unlike the three below), which calls **`create_and_link_account_from_parcel_owner()`** in `services/regrid.py` — a new function, but built entirely from existing pieces: `_account_from_parcel_owner()` (newly extracted from `create_account_from_suggestion()`, so the two share one real implementation instead of two copies) + `_apply_auto_link()` (already existed, used unchanged). Deliberately a **new trigger path, not a duplicate of the Suggestions flow**: `reconcile()`'s `regrid_owner_match` Suggestions only get created when the parcel's owner-name fuzzy score is ≥65 against an existing account — a property whose recorded owner has genuinely changed (the exact scenario this feature targets) scores nowhere near that, lands in `reconcile()`'s `no_match` branch, and would never produce a Suggestion for a broker to see. This refactor also fixed a real gap surfaced along the way: `create_account_from_suggestion()`'s hand-rolled linking never called `ensure_role()`, unlike every other linking path in that file — now fixed by routing it through `_apply_auto_link()` too.
  - **"Owner-accept doesn't link" investigation (2026-07-06):** a bug report claimed `recorded_owner_account_id` never gets set after accepting. Traced end-to-end (both by reading and by direct execution of `create_and_link_account_from_parcel_owner()`/`_apply_auto_link()` against stand-in objects) — the write path is correct: the new Account is created, `prop.recorded_owner_account_id` is set to its id, and both commits succeed. The reported symptoms ("Owner panel still shows 'No linked account'", "Contacts tab shows nothing") trace to a **different, pre-existing field**: the literal string "No linked account" appears exactly once in `property.html`, on the sidebar "Owner" card driven by `Property.account_id` (a separate FK — "current owner entity," used by `has_owner` filters, no relation to the deed-of-record concept this feature targets), and the Contacts tab is likewise queried via `prop.account_id` (`routers/properties.py`'s `get_property_full()`), not `recorded_owner_account_id`. Neither was ever in scope for this feature — the field it actually updates is reflected in the separate "Recorded Owner" card. No code fix was needed for the link itself. **Resolved as a scope decision (2026-07-06):** `create_and_link_account_from_parcel_owner()` now also fills `prop.account_id` when it's currently `None` — fill-blank-only, never overwrites an existing `account_id` (that field can legitimately diverge from the deed-of-record owner, e.g. a sale not yet reflected in county records — this only helps the specific case of a property with no owner link at all yet). This is scoped to this one ad-hoc accept-owner path only, NOT added to the shared `_apply_auto_link()` — the `reconcile()`/Suggestions confirm flow's existing, already-tested auto-link behavior is deliberately left unchanged.
  - **Account mailing address on create (2026-07-06):** `_account_from_parcel_owner()` now populates the new Account's address from the parcel's **owner mailing address** (`raw_data`'s `mailadd`/`mail_city`/`mail_state2`/`mail_zip` — real Regrid columns, not promoted to dedicated `ParcelRegrid` columns) instead of the parcel's own site address (`ParcelRegrid.address/city/state/zip`) — an out-of-state LLC's mailing address is very often different from the property it owns, and the Property record already stores the site address itself. Falls back to the site address only when no mailing field is present at all, so a newly created Account is never left with no address. `Account`'s own columns are plain `address`/`city`/`state`/`zip` (confirmed against `models/account.py` — no "mailing_" prefix on that side). Shared by both `create_account_from_suggestion()` and `create_and_link_account_from_parcel_owner()`; `reconcile()`'s own separate `auto_create_accounts` branch has its own inline Account-construction copy that was NOT touched by this change (pre-existing triplication, out of scope here — a real follow-up if that branch is ever revisited).
  - **Assessed Value, Parcel ID, and Class/Type** — all three are simple scalar fields, so no new endpoint: the frontend calls the exact same `PUT /api/properties/{id} {[field]: value}` contract the existing generic `ef()` inline-edit handler already uses. Class/Type requires an extra click (`classTypeConfirming` toggle → "Overwrite X with Y? Confirm") given the lossiness risk already flagged in recon (the classcode/usedesc classifiers only produce 4-5 buckets and can downgrade a more specific manually-set `property_type`); the other two are one-click.
  - **Building SF** — deliberately **not** offered as a same-concept overwrite. `parcels_regrid`'s `bldg_sqft` (general building SF) and `Property.sf_rentable` (commercial rentable SF) are different concepts, so the old "Living Area" row (which — bug found via recon — was silently just echoing `Property.sf_rentable` back, never actually live Public Record data) is now two honest rows: "Rentable SF" (the property's own stored value) and "Building SF (Public Record)" (the live `bldg_sqft` value), with an explicitly-labeled "Copy to Rentable SF" cross-concept action, one click.
  - **Every accept action logs an `Activity` row** (`activity_type: "public_record_sync"`) instead of adding a new audit column — `Property.updated_at` is a whole-row timestamp that fires for any change for any reason, so it can't answer "was this field synced from Public Record, and when," and a dedicated column would only ever remember the most recent sync anyway. The owner-accept logs its Activity server-side (`_log_public_record_sync()` in `finder.py`, atomic with the account-link, since that path already needed a new endpoint); the other three log via a direct frontend call to the existing `POST /api/activities` endpoint right after the PUT succeeds. `property.html` already renders an Activity feed on the same page — no new UI surface needed. Note format: `"{field_label} updated from Public Record: {old_display} → {new_display}"` (e.g. `"Assessed Value updated from Public Record: — → $2,050,000"`).

### PROPERTY_NATIONAL_LOCATION_LINKS (junction — owner-scoped match)
```
id, property_id (FK → properties.id, CASCADE), national_location_id (FK → national_locations.id, CASCADE),
match_confidence (Numeric 4,3), created_at timestamptz default now()
Unique: (property_id, national_location_id)
```
- Owner-scoping lives here: a link is only visible to the broker who owns the referenced `property_id` (via `properties.owner_id`). `national_locations` itself is shared.
- **Populated passively at property write time**, not on-demand. `services/national_locations.py`'s `link_property_to_national_locations(db, prop)` is called at every property write site (flush-only — the caller's `db.commit()` picks up the rows). The four documented write sites (same list as geocoding):
  1. `create_property` (routers/properties.py) — after geocoding
  2. `update_property` (routers/properties.py) — only when `address`/`city`/`state` changed
  3. `attach_parcel` (routers/properties.py) — always (address may have just been set from parcel data)
  4. `_upsert_property` (routers/import_properties_parties.py) — after `db.flush()` gives prop.id
  5. Property section of `execute` (routers/imports.py) — after geocoding (5th write site for completeness; task spec listed 4, but the general importer also creates properties)
- **Never add a sixth write site without also adding it to this list.** Same maintenance discipline as `merge_accounts`'s hand-maintained FK table list.
- The link uses `national_locations.address_normalized` (indexed) for O(1) lookup per property save — not a Python-side loop over every location in the city. `address_normalized` is populated by the ingestion script using the same `normalize_address()` from `services/naming.py`.
- **`POST /api/national-locations/link-to-my-properties`** remains as an **admin/utility endpoint** (no UI button calls it) — useful for manual bulk re-linking if the passive write-site mechanism ever drifts, or for initial setup before the write-site approach was in place.
- **`scripts/backfill_national_location_links.py`** — one-time population of links for properties that existed before the passive cross-linking was wired in. Run AFTER the first Overture ingest. Same pattern as `scripts/backfill_property_category.py`.
- **The "of 247 Walgreens in Michigan, you have 3" moment** — the NatLocs map layer's amber pins show "In book ✓" when the pin's national_location has a `property_national_location_links` row for the current broker, populated automatically as properties are saved.

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
/api/finder/parcels?zip=               — unified search: parcels_regrid prospects + the broker's own
                                          owner-scoped properties ("yours"), merged/deduped by
                                          normalize_address() into one list (see PARCELS_REGRID's
                                          2026-07-06 update) — zip/city/street/owner filters, at
                                          least one required, 500-row cap per source
/api/finder/parcels/search?q=          — typeahead over the local parcels table
/api/finder/parcel/{keypin}            — single lookup (3-step fallback: exact → strip → address)
/api/finder/public-record/{property_id} — Public Record tab: parcels_regrid first (parcel_id, then
                                          zip-scoped normalize_address() match), legacy local-parcels/
                                          ArcGIS fallback for counties parcels_regrid doesn't cover yet;
                                          also returns assessed_value/sale_price/sale_date/usecode/
                                          usedesc/lot_acres/zoning/bldg_sqft/derived_property_type for
                                          the field-sync accept affordances (see PARCELS_REGRID)
/api/finder/public-record/{property_id}/accept-owner — POST: field-sync owner accept — find/create an
                                          Account from the matched parcel's owner_raw and link it as
                                          recorded_owner_account_id (see PARCELS_REGRID)
/api/finder/add                        — add a parcel into the pipeline
/api/tenants                           — full CRUD; /fuzzy?name=; /{id}/contacts; /{id}/news (Google
                                          News RSS); /spaces CRUD (property_tenants)
/api/engagements                       — full CRUD
/api/marketing-lists                   — full CRUD on lists; /{id}/members (single + /bulk); member delete
/api/query                             — POST / — unified query engine behind the Search/Map page;
                                          GET /geo-options?return_type=&field=&q= (geography typeahead;
                                          national_locations also supports field=brand and field=category_top)
/api/suggestions                       — GET / (list); POST /{id}/dismiss
/api/portfolio                         — /search — cross-silo intelligence queries
/api/regrid                            — POST /ingest (multipart CSV + county, streaming UPSERT into
                                          parcels_regrid); POST /reconcile (owner-scoped fuzzy match,
                                          optional county/auto_create_accounts body); POST
                                          /suggestions/{id}/confirm, POST /suggestions/{id}/create-account
                                          — see PARCELS_REGRID in Data Model
/api/national-locations                — POST /link-to-my-properties (per-broker exact-address match
                                          against national_locations, writes property_national_location_links)
                                          — see NATIONAL_LOCATIONS in Data Model
```

### Query engine (`/api/query`)
- **Return types:** `contacts`, `accounts`, `properties`, `tenants`, `deals`, `national_locations` (constant `VALID_RETURN_TYPES` in `routers/query.py`).
- Every result row carries map-pin data: Properties/Tenants get their own lat/lng directly (Tenant rows are one-per-occupied-space, pinned to that specific property). Accounts/Contacts/Deals get their own geocoded lat/lng (null for Deal) **plus** a `linked_properties` array of `{id, lat, lng, address}` via the relevant junction (`property_parties` for accounts/contacts, the deal's own `property_id` for deals — 0 or 1 entries).
- **Geography filter assumption** (stated explicitly in code comments, not silently assumed): city/county/state filtering for Properties/Tenants/Deals applies to the property's own location; for Accounts/Contacts it applies to the entity's own city/state only — **no county filter for those two**, since neither table has a county column.
- `property` filter dict accepts both `property_type` (exact match on the raw value) and `property_category` (exact match on the 10-category taxonomy — see PROPERTY's `property_category` note above). The Search page sends `property_category`; `property_type` filtering still works for any other caller that wants the granular value.

---

## Pages

Nav is built by the single `renderSidebar(activePage)` function in `frontend/js/app.js` — every page calls it; never add a per-page static nav block. Current sections:

- **Workspace:** Dashboard, **Search**, Pipeline, Lists, Query, Review Duplicates
- **Tools:** Comps, Import, Property Finder, Portfolio Intel, Client Portal

The old **Records** section (Properties / Contacts / Accounts / Tenants / Deals as five separate nav items) was removed and replaced by the single **Search** entry, which opens the unified map-driven browse page. The five underlying list pages (`properties.html`, `contacts.html`, `accounts.html`, `tenants.html`, `deals.html`) and every detail page (`property.html`, `contact.html`, `account.html`, `deal.html`, `tenant.html`) **still exist, are still routed in `backend/main.py`, and still work** — they're just no longer in the primary nav. Detail-page URLs are unchanged; Search's list rows link straight to them.

| Page | Status | Notes |
|------|--------|-------|
| Dashboard | ✅ | Pipeline funnel, upcoming closes, activity feed |
| **Search** | ✅ | Unified map + filterable list across Properties/Accounts/Contacts/Tenants/Deals; collapsible map, hover/click pin-sync, debounced live filtering via `/api/query`. national_locations is surfaced as a **map layer overlay** (NatLocs toggle button on the map, amber pins) — not a top-level record type. |
| Property detail | ✅ | Summary / Spaces & Tenants / Contacts / Public Record / Map tabs; Recorded Owner picker + Attach Public Record card |
| Contact detail | ✅ | Phones list (label · number, primary badge, inline edit), collapsible office-location mini-map (lazy-init Leaflet) |
| Account detail | ✅ | Party hub: role badges, owned/managed properties, engagements, contacts, collapsible office-location mini-map |
| Deal detail | ✅ | Commission math, co-broker splits, contacts, documents, portal create/link |
| Pipeline (engagements) | ✅ | Kanban by stage, drag-to-PUT, "+ New Engagement" with account/property typeahead + inline "create new property," listing-type "Set as recorded owner" checkbox |
| Lists (marketing lists) | ✅ | List CRUD, bulk member add (accounts/contacts) |
| Query | ✅ | Earlier general-purpose query/export tool, predates Search — still has its own nav entry, not yet folded into Search |
| Review Duplicates | ✅ | Two tabs: Account Duplicates (lightbulb-sourced, compare-and-merge popup) and Regrid Hints (`regrid_owner_match` suggestions — see PARCELS_REGRID) |
| Properties / Contacts / Accounts / Tenants / Deals (list pages) | ✅ | Functional, reachable by URL/in-app links, no longer in primary nav |
| Property Finder | ✅ | ZIP → unified `parcels_regrid` prospects + the broker's own owner-scoped properties, merged/deduped into one map — category-icon badges (Retail/Office/Industrial/Multifamily/Land/Unclassified; Retail reachable only for Detroit prospects or a "yours" match) plus a red `--owned-marker` fill-color override for owned matches; kept separate from Search deliberately (parcel/public-record lookup is a different job than party/deal browsing) |
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
Plus a single shared `?v=N` query bumped together across **every** page's `/js/app.js` and `/static/main.css` references whenever either shared asset changes — currently `?v=14`. `main.css`'s own internal `@import url('tokens.css?v=N')` is a second, independent counter — bump it too whenever `tokens.css`'s *content* changes (not just whenever the page-level counter bumps for an unrelated reason). Don't bump only the page you're editing; grep for the current version across `frontend/pages/*.html` and bump all of them in the same commit, or some pages will silently keep serving a stale shared asset. HTML routes themselves are served via explicit `FileResponse` with `_NO_CACHE` headers (`no-store, no-cache, must-revalidate, max-age=0`) — `StaticFiles` can't set per-response headers reliably, which is why HTML pages get dedicated routes instead of a mount.

---

## Key Learnings & Patterns

- **`RecordNav` (in `frontend/js/app.js`)** — shared back/prev/next utility used identically by `property.html`/`account.html`/`contact.html`/`tenant.html`; not five per-page implementations. `search.html` encodes its filters as URL query params (`?return=...&city=...`, synced via `history.replaceState` on every search, never `pushState` — filter tweaks don't spam browser history) and, right before navigating to a detail page, calls `RecordNav.captureSearchContext(items, searchUrl)`, which stores `{searchUrl, type, ids}` in `sessionStorage` (key `ufb_nav_ctx`) — too many ids for a clean URL param. Each detail page calls `RecordNav.render('record-nav', '<type>', ID)` on load; if there's no context or the current id isn't in the stored list (direct link/bookmark), it renders nothing rather than a broken/stale control. The "Back" link is a real `<a href>` to the stored search URL, never `history.back()` — that breaks the moment there's been any intermediate navigation (e.g. Prev/Next).
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
- **`PARCELS_REGRID` is not `PARCELS`:** the legacy Oakland-only raw-SQL table and the new multi-county Regrid SQLAlchemy table are deliberately separate (different schemas, different sources) — don't conflate them when extending either. See **PARCELS_REGRID** in Data Model.
- **`normalize_address()` lives in `services/naming.py`** alongside `normalize_name()` — promoted there from a private helper in `routers/import_properties_parties.py` when the Regrid reconciler needed the exact same address normalization. If a third caller needs address normalization, import from `services/naming.py`; don't add a third copy.
- **First test suite in this repo** — `tests/` (pytest, see `pytest.ini` + `backend/requirements-dev.txt`) and `scripts/test_regrid_reconciler.py` (no-pytest-required one-shot runner) both run against the real `DATABASE_URL`, same convention as the one-off `scripts/backfill_*.py` files — there is no SQLite/mock-DB test path anywhere in this app. Point `DATABASE_URL` at a local/dev database before running either.

---

## Regrid Status

- **License:** signed terms — 9-month dev license, Michigan-wide, $1,000 flat, credit applied to nationwide conversion
- **Refresh cadence:** "as available" — urban counties 4-6x/year, rural 1+x/year. Effectively quarterly-or-better on Metro Detroit.
- **Awaiting:** paperwork from Luke + Jake, then CC payment
- **Bonus:** Regrid CRO expressed inbound demand for what UpFront is building; partnership/referral conversation open for the future
- **On arrival:** the ingestion + reconciliation infrastructure is already built (2026-06-24, against synthetic data — see **PARCELS_REGRID** in Data Model) and ready to run the moment a real county CSV lands: `POST /api/regrid/ingest` (one call per county CSV) then `POST /api/regrid/reconcile` (owner-scoped fuzzy match, sets `recorded_owner_account_id` + fires `ensure_role('owner')` on auto-link). This superseded the earlier plan for a one-off backfill script — verify the column-name guesses flagged in PARCELS_REGRID against the first real file before trusting auto-link results.

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
