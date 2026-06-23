#!/usr/bin/env python3
"""
One-time backfill: derive property_category for every Property that has a
property_type but no category yet, using the exact same pattern-matching
rules the live app applies at write-time (backend/services/property_category.py
— imported, not re-implemented, so a backfilled row can never categorize
differently than a freshly-saved one).

Idempotent — only ever selects rows with property_category IS NULL, so
re-running only catches what's new since the last run (new imports already
categorize themselves at write-time; this just catches anything that
existed before that wiring went in).

Usage:
    cd /opt/render/project/src
    python scripts/backfill_property_category.py

DATABASE_URL is read from the environment (Render sets it automatically).
For local dev it falls back to backend/.env.
"""
import os
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras

REPO_ROOT = os.path.dirname(os.path.abspath(__file__)) + '/..'
sys.path.insert(0, os.path.join(REPO_ROOT, 'backend'))
from services.property_category import categorize_property_type  # noqa: E402


# ── DB connection ─────────────────────────────────────────────────────────────

def get_db_url() -> str:
    url = os.getenv('DATABASE_URL', '')
    if not url:
        env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
        if os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if line.startswith('DATABASE_URL='):
                    url = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_url = get_db_url()
    if not db_url:
        sys.exit('ERROR: DATABASE_URL not set.\n'
                  'Run: DATABASE_URL=postgresql://... python scripts/backfill_property_category.py')

    print(f'[{datetime.now():%H:%M:%S}] Connecting to database…')
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, property_type
        FROM   properties
        WHERE  property_category IS NULL
        ORDER  BY id
    """)
    properties = cur.fetchall()
    print(f'[{datetime.now():%H:%M:%S}] {len(properties)} properties have no property_category yet\n')

    if not properties:
        print('Nothing to do.')
        conn.close()
        return

    by_category = {}
    uncategorized_types = set()
    still_null = 0

    for p in properties:
        category = categorize_property_type(p['property_type'])
        if category is None:
            still_null += 1
            continue   # property_type itself is blank — leave category NULL, don't touch the row
        cur.execute("UPDATE properties SET property_category = %s WHERE id = %s",
                    (category, p['id']))
        by_category[category] = by_category.get(category, 0) + 1
        if category == 'Uncategorized':
            uncategorized_types.add(p['property_type'])

    conn.commit()
    conn.close()

    print('=' * 60)
    print(f'Done at {datetime.now():%H:%M:%S}')
    print(f'  Properties with no property_category (before) : {len(properties)}')
    print(f'  Left NULL (property_type itself is blank)       : {still_null}')
    print(f'  Categorized                                     : {sum(by_category.values())}')
    print()
    print('  By category:')
    for category, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        print(f'    {category:24s} {count}')
    if uncategorized_types:
        print()
        print(f'  {len(uncategorized_types)} distinct property_type value(s) fell through to '
              f'"Uncategorized" — review these against the rules in services/property_category.py:')
        for t in sorted(uncategorized_types):
            print(f'    - {t!r}')


if __name__ == '__main__':
    main()
