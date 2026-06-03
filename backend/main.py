from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from database import engine, Base
from routers import contacts, accounts, properties, deals, activities, documents, portal, comps, auth

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="UpFront Broker API",
    version="1.0.0",
    lifespan=lifespan
)

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

# Serve frontend static files
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "css"), html=False), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(frontend_path, "js"), html=False), name="js")
app.mount("/pages", StaticFiles(directory=os.path.join(frontend_path, "pages"), html=False), name="pages")

@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(frontend_path, "index.html"))

@app.get("/portal/{token}")
async def serve_portal(token: str):
    return FileResponse(os.path.join(frontend_path, "pages", "portal.html"))

@app.get("/health")
async def health():
    return {"status": "ok", "app": "UpFront Broker"}
