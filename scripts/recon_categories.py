#!/usr/bin/env python3
"""One-off recon: leaf-category inventory and website coverage for national_locations.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/recon_categories.py

Reads PROD_DATABASE_URL from the environment — never hardcoded, never in .env.
Do not commit any URL alongside this file.
"""
import os
import sys

url = os.environ.get("PROD_DATABASE_URL", "").strip()
if not url:
    sys.exit("ERROR: set PROD_DATABASE_URL as an env var for this invocation.")

if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

import sqlalchemy as sa

engine = sa.create_engine(url)

with engine.connect() as conn:
    print("=== category_primary × category_top counts ===")
    rows = conn.execute(sa.text("""
        SELECT category_primary, category_top, COUNT(*) AS n
        FROM   national_locations
        GROUP  BY category_primary, category_top
        ORDER  BY category_top, COUNT(*) DESC
    """)).fetchall()
    cur_top = None
    for cat_primary, cat_top, n in rows:
        if cat_top != cur_top:
            print(f"\n  [{cat_top}]")
            cur_top = cat_top
        print(f"    {n:>6,}  {cat_primary}")

    print()
    print("=== website coverage ===")
    (n_with_site,) = conn.execute(sa.text("""
        SELECT COUNT(*)
        FROM   national_locations
        WHERE  websites IS NOT NULL
          AND  websites::text != '[]'
    """)).fetchone()
    (n_total,) = conn.execute(sa.text("SELECT COUNT(*) FROM national_locations")).fetchone()
    print(f"  rows with at least one website : {n_with_site:,} / {n_total:,}"
          f"  ({100 * n_with_site // n_total}%)")
