from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from routers import contacts, accounts, properties, deals, activities, documents, portal, comps, auth, imports

# Table creation is handled exclusively by Alembic (alembic upgrade head on startup).
# create_all is intentionally absent — it conflicts with migration-managed schema.

app = FastAPI(title="UpFront Broker API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(auth.router,         prefix="/api/auth",         tags=["auth"])
app.include_router(contacts.router,     prefix="/api/contacts",     tags=["contacts"])
app.include_router(accounts.router,     prefix="/api/accounts",     tags=["accounts"])
app.include_router(properties.router,   prefix="/api/properties",   tags=["properties"])
app.include_router(deals.router,        prefix="/api/deals",        tags=["deals"])
app.include_router(activities.router,   prefix="/api/activities",   tags=["activities"])
app.include_router(documents.router,    prefix="/api/documents",    tags=["documents"])
app.include_router(portal.router,       prefix="/api/portal",       tags=["portal"])
app.include_router(comps.router,        prefix="/api/comps",        tags=["comps"])
app.include_router(imports.router,      prefix="/api/import",       tags=["import"])

# ── Static assets (CSS + JS) — cacheable ─────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
pages_path    = os.path.join(frontend_path, "pages")

app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "css"), html=False), name="css")
app.mount("/js",     StaticFiles(directory=os.path.join(frontend_path, "js"),  html=False), name="js")

# ── HTML pages — never cached ─────────────────────────────────────────────────
# StaticFiles cannot set response headers reliably; explicit FileResponse routes
# guarantee every HTML page carries Cache-Control: no-store on every request.

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma":  "no-cache",
    "Expires": "0",
}

def _page(name: str) -> FileResponse:
    return FileResponse(os.path.join(pages_path, name), headers=_NO_CACHE)

@app.get("/pages/login.html")
async def page_login():      return _page("login.html")

@app.get("/pages/dashboard.html")
async def page_dashboard():  return _page("dashboard.html")

@app.get("/pages/properties.html")
async def page_properties(): return _page("properties.html")

@app.get("/pages/contacts.html")
async def page_contacts():   return _page("contacts.html")

@app.get("/pages/accounts.html")
async def page_accounts():   return _page("accounts.html")

@app.get("/pages/deals.html")
async def page_deals():      return _page("deals.html")

@app.get("/pages/portal.html")
async def page_portal():     return _page("portal.html")

@app.get("/pages/import.html")
async def page_import():     return _page("import.html")

@app.get("/")
async def serve_root():
    return FileResponse(os.path.join(frontend_path, "index.html"), headers=_NO_CACHE)

@app.get("/portal/{token}")
async def serve_portal(token: str):
    return _page("portal.html")

@app.get("/health")
async def health():
    return {"status": "ok", "app": "UpFront Broker"}
