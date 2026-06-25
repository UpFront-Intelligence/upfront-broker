#!/usr/bin/env python3
"""Backfill property_national_location_links for properties that existed before
passive cross-linking was wired into the property write sites (2026-06-25).

Run AFTER deploying the new code AND after running
scripts/ingest_overture_michigan.py (no national_locations rows = nothing
to link against). Safe to re-run (idempotent).

Usage (from repo root):
    DATABASE_URL="postgresql://..." python3 scripts/backfill_national_location_links.py

Same pattern as scripts/backfill_property_category.py and
scripts/backfill_property_geocoding.py.
"""
import os
import sys
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def main():
    db_url = get_db_url()
    if not db_url:
        sys.exit(
            "ERROR: DATABASE_URL not set.\n"
            "Run: DATABASE_URL=postgresql://... python3 scripts/backfill_national_location_links.py"
        )

    from database import SessionLocal
    from models.property import Property
    from models.national_location import NationalLocation
    from services.national_locations import link_property_to_national_locations

    db = SessionLocal()

    print("=" * 60)
    print("Backfill: property_national_location_links")
    print(f"Started: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    # Quick sanity check: if national_locations is empty, skip.
    nl_count = db.query(NationalLocation).count()
    if nl_count == 0:
        print("\nnational_locations table is empty — run")
        print("  scripts/ingest_overture_michigan.py first, then re-run this script.")
        db.close()
        return

    print(f"\nnational_locations rows:  {nl_count:,}")

    properties = (
        db.query(Property)
        .filter(Property.address.isnot(None))
        .order_by(Property.id)
        .all()
    )
    total = len(properties)
    print(f"Properties to check:      {total:,}\n")

    new_links = 0
    checked = 0
    batch_size = 500

    for prop in properties:
        added = link_property_to_national_locations(db, prop)
        new_links += added
        checked += 1
        if checked % batch_size == 0:
            db.commit()
            print(f"  {checked:,}/{total:,} properties checked — {new_links:,} links so far")

    db.commit()
    db.close()

    print()
    print("=" * 60)
    print(f"Done: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Properties checked: {checked:,}")
    print(f"  New links created:  {new_links:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
