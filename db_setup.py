#!/usr/bin/env python3
"""
Pre-start DB setup, run before uvicorn on every deploy (see render.yaml).

The core tables (accounts, properties, contacts, etc.) predate Alembic —
they were created via Base.metadata.create_all() before migrations were
adopted, so no migration under alembic/versions/ creates them from
scratch. `alembic upgrade head` against a brand-new, empty database fails
partway through the first migration that ALTERs one of those tables.

Fresh database: create every table from the current ORM metadata, then
stamp alembic_version at head so the schema is considered fully migrated.
Existing database: just run `alembic upgrade head` as normal.
"""
import importlib
import os
import pkgutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


def _import_all_models():
    # models/__init__.py already imports the known model modules by hand;
    # walk the package too so a file added without updating __init__.py
    # still registers its table with Base.metadata.
    import models
    for _, module_name, _ in pkgutil.walk_packages(models.__path__, prefix="models."):
        importlib.import_module(module_name)


def _run_alembic(*args):
    result = subprocess.run(["alembic", *args], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed (exit {result.returncode})")


def main():
    from sqlalchemy import inspect
    from database import Base, engine

    _import_all_models()

    is_fresh = not inspect(engine).has_table("accounts")

    if is_fresh:
        print("No accounts table found — treating as a fresh database.")
        Base.metadata.create_all(bind=engine)
        created = sorted(Base.metadata.tables.keys())
        print(f"Created {len(created)} tables:")
        for name in created:
            print(f"  - {name}")
        print("Stamping alembic_version at head...")
        _run_alembic("stamp", "head")
    else:
        print("Existing database detected — running alembic upgrade head.")
        _run_alembic("upgrade", "head")

    print("db_setup.py complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"db_setup.py failed: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
