#!/usr/bin/env python3
"""
Migrate legacy property.tenant text field → tenants + property_tenants tables.

For each property where tenant IS NOT NULL:
  - Splits comma-separated tenant names
  - Finds or creates a Tenant record (normalized_name dedup)
  - Creates a property_tenants space record if one doesn't already exist
  - Does NOT clear the original tenant field (kept as backup)

Usage:
    cd /opt/render/project/src
    python scripts/migrate_tenants.py

DATABASE_URL is read from the environment (Render sets it automatically).
For local dev it falls back to backend/.env.
"""
import os
import re
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras

# ── Name normalisation (must match routers/tenants.py _normalize) ─────────────

_STRIP = {
    'llc', 'corp', 'corporation', 'co', 'inc', 'incorporated', 'ltd', 'limited',
    'coffee', 'restaurant', 'cafe', 'company', 'the', 'group', 'holdings',
    'enterprises', 'bar', 'grill', 'kitchen', 'bistro', 'eatery', 'diner',
    'and', 'of', 'at', 'by',
}


def normalize(name: str) -> str:
    if not name:
        return ''
    n = name.lower().strip()
    n = re.sub(r'[^\w\s]', ' ', n)
    words = [w for w in n.split() if w not in _STRIP]
    return ' '.join(words) if words else n.strip()


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
    # psycopg2 accepts both postgres:// and postgresql://
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_url = get_db_url()
    if not db_url:
        sys.exit('ERROR: DATABASE_URL not set.\n'
                 'Run: DATABASE_URL=postgresql://... python scripts/migrate_tenants.py')

    print(f'[{datetime.now():%H:%M:%S}] Connecting to database…')
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    with conn.cursor() as chk:
        chk.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('tenants', 'property_tenants', 'properties')
        """)
        if chk.fetchone()[0] < 3:
            sys.exit('ERROR: one or more required tables (properties, tenants, '
                     'property_tenants) not found.\nRun: alembic upgrade head')

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, owner_id, name, address, city, tenant
        FROM   properties
        WHERE  tenant IS NOT NULL AND tenant <> ''
        ORDER  BY owner_id, id
    """)
    properties = cur.fetchall()

    print(f'[{datetime.now():%H:%M:%S}] Found {len(properties)} properties with tenant data\n')

    created_tenants = 0
    created_spaces  = 0
    skipped_spaces  = 0

    for prop in properties:
        prop_id   = prop['id']
        owner_id  = prop['owner_id']
        label     = prop['name'] or prop['address'] or f'Property #{prop_id}'
        raw_field = prop['tenant']

        names = [n.strip() for n in raw_field.split(',') if n.strip()]
        if not names:
            continue

        print(f'  [{prop_id}] {label}')
        print(f'       tenant field: "{raw_field}"')

        for raw_name in names:
            norm = normalize(raw_name)
            if not norm:
                print(f'       SKIP empty normalized name for "{raw_name}"')
                continue

            # ── Find or create Tenant ─────────────────────────────────────
            cur.execute("""
                SELECT id, name FROM tenants
                WHERE  owner_id = %s AND normalized_name = %s
                LIMIT  1
            """, (owner_id, norm))
            existing = cur.fetchone()

            if existing:
                tenant_id = existing['id']
                print(f'       "{raw_name}" → existing tenant [{tenant_id}] "{existing["name"]}"')
            else:
                cur.execute("""
                    INSERT INTO tenants (owner_id, name, normalized_name, industry)
                    VALUES (%s, %s, %s, 'Other')
                    RETURNING id
                """, (owner_id, raw_name, norm))
                tenant_id = cur.fetchone()['id']
                created_tenants += 1
                print(f'       "{raw_name}" → created tenant [{tenant_id}]')

            # ── Find or create PropertyTenant space ───────────────────────
            cur.execute("""
                SELECT id FROM property_tenants
                WHERE  property_id = %s AND tenant_id = %s AND owner_id = %s
                LIMIT  1
            """, (prop_id, tenant_id, owner_id))

            if cur.fetchone():
                skipped_spaces += 1
                print(f'       space record already exists — skipped')
            else:
                cur.execute("""
                    INSERT INTO property_tenants
                        (owner_id, property_id, tenant_id, is_available)
                    VALUES (%s, %s, %s, false)
                """, (owner_id, prop_id, tenant_id))
                created_spaces += 1
                print(f'       space record created')

        print()

    conn.commit()
    conn.close()

    print('=' * 55)
    print(f'Done at {datetime.now():%H:%M:%S}')
    print(f'  Properties processed : {len(properties)}')
    print(f'  Tenant records created : {created_tenants}')
    print(f'  Space records created  : {created_spaces}')
    print(f'  Space records skipped  : {skipped_spaces}  (already existed)')
    print()
    print('Original property.tenant field was NOT modified.')


if __name__ == '__main__':
    main()
