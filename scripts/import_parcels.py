#!/usr/bin/env python3
"""
Download Oakland County parcel data from ArcGIS Hub and bulk-upsert
into a local PostgreSQL parcels table.

Uses COPY + temp-table pattern — not row-by-row inserts.
No owner_id: this is shared public county data (Option A cache).

Usage (from project root):
    DATABASE_URL=postgresql://user:pass@host/db python scripts/import_parcels.py

Or with the app's .env:
    cd backend && python ../scripts/import_parcels.py
"""
import csv
import io
import os
import sys
import urllib.request
from datetime import datetime

import psycopg2

# ── Config ────────────────────────────────────────────────────────────────────

URL = (
    "https://opendata.arcgis.com/datasets/"
    "e2910cc3a8f84549ab7f0f8e8f99817b_1.csv"
)
BATCH_SIZE = 50_000

# ── Column mapping: CSV header → DB column ────────────────────────────────────
# Keys are the exact CSV header names from the ArcGIS Hub export.
# Values are the snake_case DB column names.
COLUMN_MAP = {
    "KEYPIN":            "keypin",
    "PIN":               "pin",
    "REVISIONDATE":      "revisiondate",
    "CVTTAXCODE":        "cvttaxcode",
    "CVTTAXDESCRIPTION": "cvttaxdescription",
    "CLASSCODE":         "classcode",
    "NAME1":             "name1",
    "NAME2":             "name2",
    "SITEADDRESS":       "siteaddress",
    "SITECITY":          "sitecity",
    "SITESTATE":         "sitestate",
    "SITEZIP5":          "sitezip5",
    "POSTALADDRESS":     "postaladdress",
    "ASSESSEDVALUE":     "assessedvalue",
    "TAXABLEVALUE":      "taxablevalue",
    "NUM_BEDS":          "num_beds",
    "NUM_BATHS":         "num_baths",
    "STRUCTURE_DESC":    "structure_desc",
    "LIVING_AREA_SQFT":  "living_area_sqft",
    "Shape.area":        "shapearea",
    "Shape.len":         "shapelen",
}

DB_COLS = list(COLUMN_MAP.values())

INT_COLS   = {"assessedvalue", "taxablevalue", "num_beds", "num_baths", "living_area_sqft"}
FLOAT_COLS = {"shapearea", "shapelen"}

# ── DDL ───────────────────────────────────────────────────────────────────────

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS parcels (
    keypin            VARCHAR PRIMARY KEY,
    pin               VARCHAR,
    revisiondate      VARCHAR,
    cvttaxcode        VARCHAR,
    cvttaxdescription VARCHAR,
    classcode         VARCHAR,
    name1             VARCHAR,
    name2             VARCHAR,
    siteaddress       VARCHAR,
    sitecity          VARCHAR,
    sitestate         VARCHAR,
    sitezip5          VARCHAR,
    postaladdress     VARCHAR,
    assessedvalue     INTEGER,
    taxablevalue      INTEGER,
    num_beds          INTEGER,
    num_baths         INTEGER,
    structure_desc    VARCHAR,
    living_area_sqft  INTEGER,
    shapearea         FLOAT,
    shapelen          FLOAT
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_parcels_sitezip5   ON parcels (sitezip5);",
    "CREATE INDEX IF NOT EXISTS idx_parcels_name1      ON parcels (name1);",
    "CREATE INDEX IF NOT EXISTS idx_parcels_classcode  ON parcels (classcode);",
]

CREATE_STAGING = """
CREATE TEMP TABLE IF NOT EXISTS parcels_staging (
    LIKE parcels INCLUDING DEFAULTS
) ON COMMIT DELETE ROWS;
"""

UPSERT_SQL = """
INSERT INTO parcels ({cols})
SELECT {cols} FROM parcels_staging
ON CONFLICT (keypin) DO UPDATE SET
    {updates};
""".format(
    cols=", ".join(DB_COLS),
    updates=",\n    ".join(
        f"{c} = EXCLUDED.{c}" for c in DB_COLS if c != "keypin"
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def coerce(value: str, col: str):
    """Return typed Python value or None for empty/invalid strings."""
    v = value.strip()
    if not v:
        return None
    if col in INT_COLS:
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None
    if col in FLOAT_COLS:
        try:
            return float(v)
        except (ValueError, TypeError):
            return None
    return v or None


def rows_to_csv_buf(rows: list) -> io.StringIO:
    """Serialise a list of tuples to a CSV buffer, using empty string for NULL."""
    buf = io.StringIO()
    w   = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    buf.seek(0)
    return buf


def upsert_batch(cur, rows: list) -> int:
    """COPY rows into staging, then upsert into parcels. Returns row count."""
    buf = rows_to_csv_buf(rows)
    cur.execute("TRUNCATE parcels_staging;")
    cur.copy_expert(
        f"COPY parcels_staging ({', '.join(DB_COLS)}) FROM STDIN WITH (FORMAT CSV, NULL '')",
        buf,
    )
    cur.execute(UPSERT_SQL)
    return len(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    if not db_url:
        # Try loading from backend/.env
        env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
        if os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    db_url = line.split("=", 1)[1].strip().strip('"')
                    if db_url.startswith("postgres://"):
                        db_url = db_url.replace("postgres://", "postgresql://", 1)
                    break
    if not db_url:
        sys.exit("ERROR: DATABASE_URL not set. Run: DATABASE_URL=... python scripts/import_parcels.py")

    print(f"[{datetime.now():%H:%M:%S}] Connecting to database…")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    with conn.cursor() as cur:
        print(f"[{datetime.now():%H:%M:%S}] Creating parcels table and indexes…")
        cur.execute(CREATE_TABLE)
        for idx_sql in CREATE_INDEXES:
            cur.execute(idx_sql)
        cur.execute(CREATE_STAGING)
        conn.commit()

    print(f"[{datetime.now():%H:%M:%S}] Streaming CSV from ArcGIS Hub…")
    print(f"  URL: {URL}")

    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "UpFrontBroker/1.0 (credetroit@gmail.com)"},
    )

    total_rows  = 0
    batch       = []
    col_indices = None   # maps DB_COLS positions once header is parsed

    with urllib.request.urlopen(req, timeout=120) as resp:
        # Wrap the binary stream in a text reader so csv can decode it
        reader = csv.reader(io.TextIOWrapper(resp, encoding="utf-8-sig"))

        for row_num, raw_row in enumerate(reader):
            if row_num == 0:
                # Parse header and build column index list
                header     = raw_row
                col_indices = []
                missing    = []
                for csv_col, db_col in COLUMN_MAP.items():
                    try:
                        col_indices.append((header.index(csv_col), db_col))
                    except ValueError:
                        missing.append(csv_col)
                if missing:
                    print(f"  WARNING: these expected columns were not found in CSV: {missing}")
                print(f"  Mapped {len(col_indices)} of {len(COLUMN_MAP)} columns from header.")
                continue

            # Build typed tuple in DB column order
            row_dict = {}
            for csv_idx, db_col in col_indices:
                try:
                    row_dict[db_col] = coerce(raw_row[csv_idx], db_col)
                except IndexError:
                    row_dict[db_col] = None

            # keypin is required
            if not row_dict.get("keypin"):
                continue

            # Fill any missing DB cols with None
            typed_row = tuple(row_dict.get(c) for c in DB_COLS)
            batch.append(typed_row)

            if len(batch) >= BATCH_SIZE:
                with conn.cursor() as cur:
                    upsert_batch(cur, batch)
                    conn.commit()
                total_rows += len(batch)
                batch = []
                print(f"  [{datetime.now():%H:%M:%S}] {total_rows:,} rows upserted…")

    # Final partial batch
    if batch:
        with conn.cursor() as cur:
            upsert_batch(cur, batch)
            conn.commit()
        total_rows += len(batch)

    conn.close()
    print(f"[{datetime.now():%H:%M:%S}] Done. Total rows upserted: {total_rows:,}")


if __name__ == "__main__":
    main()
