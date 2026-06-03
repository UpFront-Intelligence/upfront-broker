# UpFront Broker — Claude Code Context

## What This Is
A B2B CRE CRM built for independent commercial real estate brokers.
Solo-agent, IC-first — the broker owns their data, fully portable.
Built from scratch with lessons learned from UpFront (AI-SalesWizard).

**Live target:** Render (same pattern as UpFront)
**Local dev:** `cd backend && uvicorn main:app --reload`

---

## Tech Stack
- **Backend:** FastAPI (Python) + SQLAlchemy ORM + Alembic migrations
- **Database:** PostgreSQL (Render managed DB)
- **Auth:** Email/password (bcrypt + passlib) + JWT (python-jose)
  — Google OAuth code is present but commented out; restore after product is live
- **Frontend:** Vanilla JS (ES6+), multi-file, no framework
- **Fonts:** DM Sans (body) + DM Serif Display (headings) via Google Fonts
- **Deploy:** Render via render.yaml

---

## Project Structure
```
upfront-broker/
├── backend/
│   ├── main.py              # FastAPI entry point, all routers mounted
│   ├── database.py          # SQLAlchemy engine + get_db dependency
│   ├── auth_utils.py        # JWT create/verify, get_current_user
│   ├── models/
│   │   ├── __init__.py      # imports all models (required for table creation)
│   │   ├── user.py          # broker profile
│   │   ├── contact.py       # center of gravity — Contact is king
│   │   ├── account.py       # LLC/entity layer
│   │   ├── contact_account.py  # junction: 1 contact → many LLCs
│   │   ├── property.py      # CRE property, 9 types
│   │   ├── deal.py          # transaction + DealContact junction
│   │   └── shared.py        # Activity, Document, Portal, PortalView, Comp
│   ├── routers/
│   │   ├── auth.py          # /api/auth — register, login, me
│   │   ├── contacts.py      # /api/contacts — full CRUD
│   │   ├── accounts.py      # /api/accounts — full CRUD + contact linking
│   │   ├── properties.py    # /api/properties — full CRUD
│   │   ├── deals.py         # /api/deals — full CRUD + pipeline-summary
│   │   ├── activities.py    # /api/activities — log calls, emails, tours
│   │   ├── documents.py     # /api/documents — file references
│   │   ├── portal.py        # /api/portal — buyer/seller portal
│   │   └── comps.py         # /api/comps — manual + CRE data import
│   └── requirements.txt
├── frontend/
│   ├── css/
│   │   └── main.css         # full design system + CSS variables
│   ├── js/
│   │   └── app.js           # API, Auth, Toast, Fmt, Modal, renderSidebar
│   └── pages/
│       ├── login.html       # sign in + register
│       ├── dashboard.html   # morning view — pipeline, closes, activity
│       ├── properties.html  # [TODO]
│       ├── contacts.html    # [TODO]
│       ├── accounts.html    # [TODO]
│       ├── deals.html       # [TODO]
│       └── portal.html      # [TODO]
├── alembic/                 # DB migrations (init when ready)
├── .env                     # local env vars (not committed)
├── render.yaml              # Render deploy config
└── CLAUDE.md                # this file
```

---

## Data Model (Critical — Read Before Touching Models)

**Hierarchy: Contact is the center of gravity.**
```
CONTACT (the human, the relationship)
    └── ACCOUNT (LLC/entity they control) — via contact_accounts junction
            └── PROPERTY (what the entity owns)
                    └── DEAL (the transaction)
                            ├── ACTIVITY (log of all touchpoints)
                            ├── DOCUMENT (files attached to the deal)
                            └── PORTAL (buyer/seller client portal)
```

One contact can control many LLCs.
One LLC can own many properties.
One property can have many deals over time.
Every deal tracks both sides (listing + buyer rep), co-broker splits, full commission math.

---

## Data Privacy Architecture

Two distinct isolation models exist in this codebase. **Never mix them.**

### Option A — Shared cache (no `owner_id`)
Used for data sourced entirely from third-party public records. The same
county parcel record has the same assessed value regardless of which broker
looks it up. Caching it per-user wastes space, burns API quota, and produces
stale divergence between brokers who enriched on different days.

**Table:** `enrichment_cache`
- No `owner_id` column.
- Keyed on `(lookup_type, lookup_key)` — e.g. `("parcel_id", "12-34-567-890")`.
- 90-day TTL via `expires_at`; stale rows are re-fetched transparently.
- `hit_count` tracks demand for cache warming and quota planning.
- All writes come from the enrichment service, never from broker input.

### Option B — Per-user isolation (`owner_id` on every row)
Used for everything the broker creates, edits, or appends. Two brokers can
track the same property address and never see each other's data.

**All other tables** (`properties`, `contacts`, `accounts`, `deals`,
`activities`, `documents`, `comps`, `portals`, …) carry `owner_id` and every
query filters on it. This is the product promise.

### The boundary
```
Public-records fetch  →  enrichment_cache (Option A, shared)
                      ↓
Broker confirms diff  →  properties / accounts (Option B, per-user)
```
Raw third-party responses live in the shared cache. The moment a broker
accepts an enrichment result, the data is written into their own isolated
`Property` record. The cache entry is never exposed directly to the frontend.

---

## Property Types (v1 — Commercial Only)
Office, Industrial, Retail, Land, Multifamily, STNL, Self Storage, Hospitality, Medical

Residential is on the roadmap but explicitly out of scope for v1.

---

## Deal Stages (in order)
Prospecting → Pitching → Active Listing → Under Contract → Closed → Dead

---

## Commission Math (auto-calculated on save — see routers/deals.py)
- `commission_total` = sale_price × commission_pct
- `our_commission`   = commission_total × our_split_pct
- Co-broker split tracked separately
- Lease deals: base = lease_rate × sf × (term_months / 12)

---

## Design System (CSS Variables — do not freestyle)
```
--navy:        #0f1923   (sidebar, primary UI)
--navy-mid:    #16263a
--navy-light:  #1e3450
--gold:        #c9943a   (accent, active states)
--gold-light:  #e0b060
--cream:       #f7f4ef   (main background)
--cream-dark:  #ede9e2   (borders, hover states)
--stone:       #8a8278   (secondary text)
--green:       #2d7d4f   (success, commission)
--amber:       #c47c20   (warning)
--red:         #a83232   (error, dead deals)

Fonts:
--font-body:   'DM Sans', sans-serif
--font-serif:  'DM Serif Display', serif    (headings, titles)
--font-mono:   'JetBrains Mono', monospace  (numbers, stats)
```

---

## Frontend Patterns (follow these exactly)

### Every page needs:
```html
<div id="sidebar"></div>
<div id="main">
  <div id="topbar">...</div>
  <div id="page-content" class="fade-in">...</div>
</div>
<script src="/js/app.js"></script>
<script>
  if (!Auth.requireAuth()) throw new Error('Not authenticated');
  renderSidebar('PAGE_NAME');  // matches nav-item data-page
  // page logic here
</script>
```

### API calls:
```javascript
// GET
const data = await API.get('/contacts/');

// POST
const result = await API.post('/contacts/', { first_name: 'John', ... });

// PUT
await API.put(`/contacts/${id}`, updates);

// DELETE
await API.delete(`/contacts/${id}`);
```

### Toast notifications:
```javascript
Toast.success('Contact saved');
Toast.error('Something went wrong');
Toast.info('Loading...');
```

### Format utilities:
```javascript
Fmt.currency(1500000)     // → '$1,500,000'
Fmt.sf(25000)             // → '25,000 SF'
Fmt.pct(6.5)              // → '6.5%'
Fmt.date('2026-06-01')    // → 'Jun 1, 2026'
Fmt.propType('Office')    // → '🏢'
Fmt.stageClass('Under Contract')  // → CSS class string
```

### Modals:
```javascript
Modal.open('modal-id');
Modal.close('modal-id');
Modal.closeOnOverlay('modal-id');
```

---

## Environment Variables
```
DATABASE_URL          — PostgreSQL connection string (Render injects automatically)
SECRET                — JWT signing key (Render generates on deploy)
GOOGLE_CLIENT_ID      — From Google Cloud Console → APIs & Services → Credentials
GOOGLE_CLIENT_SECRET  — Same
CALLBACK_URL          — https://YOUR-APP.onrender.com/api/auth/callback
                        Must also be added as an Authorised Redirect URI in Google Cloud Console
```

Local `.env` file has defaults for dev. Never commit real credentials.

---

## Coding Rules
- **ES6+ OK** — arrow functions, const/let, template literals, async/await all fine
- **No frameworks** — vanilla JS only on the frontend
- **No confirmation prompts** — auto-approve, just do it
- **Surgical edits** — don't rewrite what works
- **One file per concern** — no monster files, keep pages under 500 lines
- **CSS variables always** — never hardcode colors or fonts inline
- **owner_id on every query** — data isolation is the product promise

---

## Local Dev Setup
```bash
cd backend
pip install -r requirements.txt
# set DATABASE_URL in .env
uvicorn main:app --reload --port 8000
# frontend served from /frontend via FastAPI StaticFiles
# open http://localhost:8000/pages/login.html
```

---

## What's Built (v1 Session 1)
- [x] Full FastAPI backend — all models, all routers, auth
- [x] Design system (CSS) — navy/gold/cream, DM Sans + DM Serif
- [x] Shared JS utilities — API, Auth, Toast, Fmt, Modal, renderSidebar
- [x] Login page — sign in + register with split layout
- [x] Dashboard — morning view with pipeline funnel, upcoming closes, activity feed

## What's Next (build in this order)
- [x] properties.html — list view + add/edit modal + detail panel
- [x] contacts.html   — list view + add/edit modal + detail panel
- [x] accounts.html   — list view + add/edit modal + detail panel
- [x] deals.html      — kanban + list + map views, commission math, detail panel
- [x] portal.html     — client-facing portal (buyer + seller), email gate, section logging
- [x] import.html     — 5-step CSV/XLSX wizard, fuzzy field mapping, duplicate detection
- [ ] comps.html      — comp table + CRE data import
- [x] finder.html     — Property Finder (Oakland County ArcGIS, zip search, parcel map, Add to Pipeline)
- [ ] GitHub init + Render deploy

## Property Finder (next feature)
Market-facing property discovery tool powered by Oakland County ArcGIS public data.

**Core flow:**
1. Broker enters a zip code (or clicks a map area)
2. App queries Oakland County ArcGIS REST API for all parcels in that zip
3. Results rendered as parcel overlays on a Leaflet map
4. Each parcel is clickable — shows assessor card (owner, address, SF, year built,
   assessed value, tax, zoning, legal description)
5. "Add to Pipeline" button on each parcel card → pre-fills a new Property record
   and optionally creates a Prospecting deal in one click

**ArcGIS source:**  `MICHIGAN_PUBLIC_RECORDS.md` — Oakland County endpoint
**Map:**            Leaflet.js (already used in deals.html)
**Dedup:**          Check against existing properties by parcel_id before adding
**Enrichment:**     Feeds the ENRICHMENT_CACHE table (see Data Privacy Architecture)
**Route:**          `/pages/finder.html` + `GET /api/finder/parcels?zip={zip}`

**Key decisions to make before building:**
- Zip code → ArcGIS bounding box vs. ArcGIS `where ZIPCODE='48226'` filter
- How many parcels to show (cap at ~500 for map performance)
- Whether parcel overlays use actual geometry or centroid points
- "Add to Pipeline" flow: modal or direct create?

---

## Out of Scope (v1)
BOV Generator, Residential, Mobile app, MLS integration,
Stripe/billing, Skip tracing API, Chrome extension
