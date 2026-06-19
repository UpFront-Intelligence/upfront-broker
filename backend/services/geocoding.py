"""
US Census Bureau geocoder — free, no API key required.

Docs/behavior confirmed against the live endpoints (not assumed):
  - Single address returns {"result": {"addressMatches": [...]}} — an empty
    list means no match (non-US address, or just unmatchable). HTTP 200
    either way; there is no error status for "not found."
  - Batch takes a headerless CSV (id, street, city, state, zip) as
    multipart form file "addressFile" + a "benchmark" field, and returns a
    headerless CSV: "id,input,Match|No_Match[,Exact|Non_Exact,matched_addr,
    "lon,lat",tiger_line_id,side]". The coordinate pair is one quoted CSV
    cell as "lon,lat" — longitude first.
  - Census limits batch requests to 10,000 records.

Both only handle US addresses. Non-US addresses (e.g. the Toronto entries
in the Michigan data) come back as No_Match / empty addressMatches — treat
that as a graceful skip (log it, leave lat/lng null), never an exception.
"""
import csv
import io
import logging

import requests

logger = logging.getLogger(__name__)

ONELINE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
BATCH_MAX_RECORDS = 10000


def geocode_address(address, city=None, state=None, zip_code=None, timeout=10):
    """Single US address -> (lat, lng) rounded to 6 decimals, or None if
    there's no match or the request itself fails. Never raises."""
    if not address:
        return None
    one_line = ", ".join(p for p in (address, city, state, zip_code) if p)
    try:
        resp = requests.get(ONELINE_URL, params={
            "address": one_line, "benchmark": BENCHMARK, "format": "json",
        }, timeout=timeout)
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", [])
    except Exception as exc:
        logger.warning("Census geocode request failed for %r: %s", one_line, exc)
        return None
    if not matches:
        logger.info("Census geocode: no match for %r (non-US or unmatchable)", one_line)
        return None
    coords = matches[0]["coordinates"]
    return round(coords["y"], 6), round(coords["x"], 6)  # y=lat, x=lng


def geocode_batch(records, timeout=120):
    """records: list of (account_id: int, address, city, state, zip).
    Returns {account_id: (lat, lng) | None} — None for no-match/non-US rows
    and (on total request failure) for every row. Never raises."""
    if not records:
        return {}
    if len(records) > BATCH_MAX_RECORDS:
        raise ValueError(f"Census batch geocoder allows at most {BATCH_MAX_RECORDS} "
                          f"records per request, got {len(records)}")

    buf = io.StringIO()
    writer = csv.writer(buf)
    for rid, address, city, state, zip_code in records:
        writer.writerow([rid, address or "", city or "", state or "", zip_code or ""])

    try:
        resp = requests.post(
            BATCH_URL,
            files={"addressFile": ("batch.csv", buf.getvalue().encode("utf-8"), "text/csv")},
            data={"benchmark": BENCHMARK},
            timeout=timeout,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Census batch geocode request failed for %d records: %s", len(records), exc)
        return {rid: None for rid, *_ in records}

    results = {}
    for row in csv.reader(io.StringIO(resp.text)):
        if len(row) < 3:
            continue
        try:
            rid = int(row[0])
        except ValueError:
            continue
        if row[2] != "Match" or len(row) < 6:
            results[rid] = None
            continue
        try:
            lon_str, lat_str = row[5].split(",")
            results[rid] = (round(float(lat_str), 6), round(float(lon_str), 6))
        except (ValueError, IndexError):
            results[rid] = None

    for rid, *_ in records:
        results.setdefault(rid, None)
    return results
