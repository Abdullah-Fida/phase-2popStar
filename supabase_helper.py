"""
supabase_helper.py — Shared Supabase bridge for the 3-part pipeline
====================================================================
All three parts (A, B, C) use this module to read/write the shared state.

Tables used:
  - phase2_urls        : URL handoff from Part A to Part B/C
  - scraped_listings   : Live Phase 3 results (mirrors Objekte_phase3.csv)
  - scraped_contacts   : Live Phase 3 results (mirrors Kontakte_phase3.csv)
"""

import os
import csv
import logging
import time
import config

# ── Supabase client (lazy init) ──────────────────────────────────────────────
_client = None

def get_client():
    """Return a cached Supabase client, initialising on first call."""
    global _client
    if _client is None:
        try:
            from supabase import create_client, Client
        except ImportError:
            raise RuntimeError(
                "supabase-py is not installed. Run: pip install supabase"
            )
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY env vars must be set."
            )
        _client = create_client(url, key)
        logging.info("Supabase client initialised.")
    return _client


# ── PART A helpers ────────────────────────────────────────────────────────────

def upload_urls(urls: list[str], url_type: str, run_date: str, batch_size: int = 500):
    """
    Bulk-upsert a list of URLs into the phase2_urls table.
    url_type : 'buy' or 'rent'
    run_date : ISO-8601 string, e.g. datetime.utcnow().isoformat()
    Skips duplicates via ON CONFLICT DO NOTHING (upsert with ignore_duplicates=True).
    """
    sb = get_client()
    rows = [
        {
            "url":      u,
            "type":     url_type,
            "status":   "pending",
            "run_date": run_date,
        }
        for u in urls
        if u.strip()
    ]
    total = len(rows)
    logging.info(f"Uploading {total} {url_type} URLs to Supabase in batches of {batch_size}…")

    for i in range(0, total, batch_size):
        chunk = rows[i : i + batch_size]
        _retry(
            lambda c=chunk: sb.table("phase2_urls")
                              .upsert(c, on_conflict="url", ignore_duplicates=True)
                              .execute()
        )
        logging.info(f"  Uploaded {min(i + batch_size, total)}/{total}")

    logging.info(f"Upload complete: {total} {url_type} URLs.")


# ── PART B / C helpers ────────────────────────────────────────────────────────

def fetch_pending_urls() -> list[dict]:
    """
    Return all rows from phase2_urls where status = 'pending'.
    Each row is a dict with keys: id, url, type, status, run_date
    """
    sb = get_client()
    response = _retry(
        lambda: sb.table("phase2_urls")
                  .select("id,url,type,status")
                  .eq("status", "pending")
                  .execute()
    )
    rows = response.data or []
    logging.info(f"Fetched {len(rows)} pending URLs from Supabase.")
    return rows


def fetch_all_urls() -> list[dict]:
    """Return ALL rows (pending + done) — used to rebuild buy_url_set in Part C."""
    sb = get_client()
    response = _retry(
        lambda: sb.table("phase2_urls")
                  .select("id,url,type,status")
                  .execute()
    )
    return response.data or []


def mark_url_done(url: str):
    """Mark a single URL as status='done' in phase2_urls."""
    sb = get_client()
    _retry(
        lambda: sb.table("phase2_urls")
                  .update({"status": "done"})
                  .eq("url", url)
                  .execute()
    )


def mark_url_failed(url: str):
    """Mark a single URL as status='failed' in phase2_urls."""
    sb = get_client()
    _retry(
        lambda: sb.table("phase2_urls")
                  .update({"status": "failed"})
                  .eq("url", url)
                  .execute()
    )


def save_listing(listing_row: dict):
    """
    Upsert one row into scraped_listings.
    Duplicate detail_url → update in place (handles Part C re-running).
    """
    sb = get_client()
    _retry(
        lambda: sb.table("scraped_listings")
                  .upsert(listing_row, on_conflict="detail_url")
                  .execute()
    )


def save_contact(contact_row: dict):
    """
    Upsert one row into scraped_contacts.
    Duplicate external_id → update in place.
    """
    sb = get_client()
    _retry(
        lambda: sb.table("scraped_contacts")
                  .upsert(contact_row, on_conflict="external_id")
                  .execute()
    )


# ── PART C — download back to CSV ────────────────────────────────────────────

def download_to_csv():
    """
    Pull all data from scraped_listings and scraped_contacts
    and write them to the local CSV files expected by phases 3.7, 3.8, 5, 6.
    This recreates Objekte_phase3.csv and Kontakte_phase3.csv from Supabase.
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    sb = get_client()

    # ── Download listings ──────────────────────────────────────────────────
    logging.info("Downloading scraped_listings from Supabase…")
    listings = _paginate(sb, "scraped_listings")
    logging.info(f"  Got {len(listings)} listing rows.")

    if listings:
        # Use config column order so downstream phases don't break
        _write_csv(config.OBJEKTE_FILENAME, listings, config.OBJEKTE_COLUMNS)
        logging.info(f"  Written → {config.OBJEKTE_FILENAME}")

    # ── Download contacts ──────────────────────────────────────────────────
    logging.info("Downloading scraped_contacts from Supabase…")
    contacts = _paginate(sb, "scraped_contacts")
    logging.info(f"  Got {len(contacts)} contact rows.")

    if contacts:
        _write_csv(config.KONTAKTE_FILENAME, contacts, config.KONTAKTE_COLUMNS)
        logging.info(f"  Written → {config.KONTAKTE_FILENAME}")

    return len(listings), len(contacts)


# ── Internal utilities ────────────────────────────────────────────────────────

def _paginate(sb, table: str, page_size: int = 1000) -> list[dict]:
    """Fetch all rows from a table using cursor-based pagination."""
    all_rows = []
    offset = 0
    while True:
        resp = _retry(
            lambda o=offset: sb.table(table)
                               .select("*")
                               .range(o, o + page_size - 1)
                               .execute()
        )
        chunk = resp.data or []
        all_rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return all_rows


def _write_csv(filepath: str, rows: list[dict], columns: list[str]):
    """Write rows to a CSV with a fixed column order. Extra keys are ignored."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=columns, extrasaction="ignore", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(rows)


def _retry(fn, retries: int = 5, delay: float = 10.0):
    """
    Retry a Supabase call up to `retries` times on any exception.
    Waits `delay` seconds between attempts (doubles each retry).
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = delay * (2 ** attempt)
            logging.warning(
                f"Supabase call failed (attempt {attempt+1}/{retries}): {e}. "
                f"Retrying in {wait:.0f}s…"
            )
            time.sleep(wait)
