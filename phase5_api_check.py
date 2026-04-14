import asyncio
import csv
import json
import logging
import os
import aiohttp
import config

# ============================================================
# SETTINGS
# ============================================================
API_URL     = "https://api.we-net.ch/api/advertisers/check"
CONCURRENCY = 10      # simultaneous API calls

INPUT_KONTAKTE = os.path.join(config.OUTPUT_DIR, "Kontakte_phase4.csv")
INPUT_OBJEKTE  = os.path.join(config.OUTPUT_DIR, "Objekte_phase4.csv")

OUT_KONTAKTE   = os.path.join(config.OUTPUT_DIR, "Kontakte_phase5.csv")
OUT_OBJEKTE    = os.path.join(config.OUTPUT_DIR, "Objekte_phase5.csv")
REJ_KONTAKTE   = os.path.join(config.OUTPUT_DIR, "rejected_kontakte_phase5.csv")
REJ_OBJEKTE    = os.path.join(config.OUTPUT_DIR, "rejected_objekte_phase5.csv")
PROGRESS_FILE  = os.path.join(config.OUTPUT_DIR, "phase5_progress.json")
PHASE5_LOG     = os.path.join(config.OUTPUT_DIR, "phase5.log")

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(PHASE5_LOG, mode="a", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# ============================================================
# ID GENERATION
# ============================================================
def load_last_external_id() -> int:
    """Load the highest existing external_id from Kontakte_phase4 so new IDs continue forward."""
    max_id = 0
    if os.path.exists(INPUT_KONTAKTE):
        with open(INPUT_KONTAKTE, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    val = int(row.get("external_id", 0))
                    if val > max_id:
                        max_id = val
                except (ValueError, TypeError):
                    pass
    return max_id


_next_id_counter = 0

def get_next_external_id() -> str:
    global _next_id_counter
    _next_id_counter += 1
    return str(_next_id_counter)


# ============================================================
# HELPERS
# ============================================================
def build_payload(contact: dict) -> dict:
    """Build POST JSON with only non-empty fields."""
    # Strip Excel ="..." wrappers if present
    def unwrap(v):
        v = str(v).strip()
        if v.startswith('="') and v.endswith('"'):
            v = v[2:-1]
        return v

    field_map = {
        "first_name":        unwrap(contact.get("first_name", "")),
        "last_name":         unwrap(contact.get("last_name", "")),
        "organization_name": unwrap(contact.get("organization_name", "")),
        "phone":             unwrap(contact.get("normalized_phone", "")),
        "email":             unwrap(contact.get("email", "")),
    }
    return {k: v for k, v in field_map.items() if v}


async def check_contact(session: aiohttp.ClientSession, contact: dict) -> dict:
    """
    POST contact to API. Returns:
      {"action": "skip_contact", "advertiser_id": int}   — found & not blocked
      {"action": "keep",         "advertiser_id": None}  — not found (404 or found=false)
      {"action": "drop",         "advertiser_id": None}  — blocked
    Retries indefinitely on network/5xx errors (60s back-off).
    """
    payload = build_payload(contact)
    ext_id  = contact.get("external_id", "?")

    while True:
        try:
            async with session.post(
                API_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:

                if resp.status == 400:
                    # Bad request — payload rejected permanently, treat as drop
                    logging.warning(f"[{ext_id}] HTTP 400 (bad payload) → drop (no retry)")
                    return {"action": "drop", "advertiser_id": None}

                if resp.status in (200, 404):
                    if resp.status == 404:
                        logging.info(f"[{ext_id}] NOT FOUND (404) → keep")
                        return {"action": "keep", "advertiser_id": None}

                    data = await resp.json()

                    # Blocked → drop everything
                    if data.get("blocked") is True:
                        logging.info(f"[{ext_id}] BLOCKED → drop")
                        return {"action": "drop", "advertiser_id": None}

                    # Found + not blocked → skip contact, keep objects with advertiser_id
                    if data.get("found") is True:
                        adv_id = data.get("id")
                        logging.info(f"[{ext_id}] FOUND (not blocked) → skip_contact, advertiser_id={adv_id}")
                        return {"action": "skip_contact", "advertiser_id": adv_id}

                    # 200 but found=false → not found → keep
                    logging.info(f"[{ext_id}] NOT FOUND (200/found=false) → keep")
                    return {"action": "keep", "advertiser_id": None}

                else:
                    logging.warning(f"[{ext_id}] HTTP {resp.status}. Waiting 60s to retry...")
                    await asyncio.sleep(60)

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logging.warning(f"[{ext_id}] Network error: {e}. Waiting 60s to retry...")
            await asyncio.sleep(60)
        except Exception as e:
            logging.error(f"[{ext_id}] Unexpected error: {e}. Waiting 60s to retry...")
            await asyncio.sleep(60)


# ============================================================
# PROGRESS (RESUME SUPPORT)
# ============================================================
def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ============================================================
# MAIN
# ============================================================
async def main():
    global _next_id_counter

    logging.info("=" * 60)
    logging.info("PHASE 5: API ADVERTISER CHECK (new logic)")
    logging.info("=" * 60)

    # ── Load contacts ────────────────────────────────────────
    if not os.path.exists(INPUT_KONTAKTE):
        logging.error(f"Input file not found: {INPUT_KONTAKTE}")
        return

    with open(INPUT_KONTAKTE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        kontakte_fields = list(reader.fieldnames)
        all_contacts = list(reader)

    # ── Load objects grouped by contact_external_id ──────────
    objekte_by_contact = {}
    objekte_fields = []
    if os.path.exists(INPUT_OBJEKTE):
        with open(INPUT_OBJEKTE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            objekte_fields = list(reader.fieldnames)
            for row in reader:
                cid = row["contact_external_id"]
                objekte_by_contact.setdefault(cid, []).append(row)

    # Ensure advertiser_id column exists in objekte schema
    if "advertiser_id" not in objekte_fields:
        objekte_fields = objekte_fields + ["advertiser_id"]

    # ── Seed the ID counter above all existing IDs ───────────
    _next_id_counter = load_last_external_id()
    logging.info(f"ID counter seeded at {_next_id_counter} (will assign from {_next_id_counter + 1})")

    # ── Resume: skip already-processed contacts ───────────────
    progress = load_progress()
    remaining = [c for c in all_contacts if c["external_id"] not in progress]
    logging.info(
        f"Total contacts: {len(all_contacts)} | "
        f"Already done: {len(progress)} | "
        f"Remaining: {len(remaining)}"
    )

    # ── Result buckets ────────────────────────────────────────
    valid_contacts = []   # action == "keep"
    valid_objekte  = []   # objects for kept contacts + skip_contact objects
    rej_contacts   = []   # action == "drop"
    rej_objekte    = []   # objects for dropped contacts

    # Pre-fill results from already-processed contacts
    for c in all_contacts:
        ext_id = c["external_id"]
        if ext_id not in progress:
            continue
        result = progress[ext_id]
        action = result["action"]
        objs   = objekte_by_contact.get(ext_id, [])
        adv_id = result.get("advertiser_id")

        if action == "keep":
            new_ext_id = result.get("new_external_id", ext_id)
            c["external_id"] = new_ext_id
            valid_contacts.append(c)
            for obj in objs:
                obj = dict(obj)
                obj["contact_external_id"] = new_ext_id
                valid_objekte.append(obj)

        elif action == "skip_contact":
            # Objects kept but contact_external_id blanked, advertiser_id set
            for obj in objs:
                obj = dict(obj)
                obj["contact_external_id"] = ""
                obj["advertiser_id"] = str(adv_id) if adv_id else ""
                valid_objekte.append(obj)

        else:  # drop
            rej_contacts.append({**c, "reject_reason": result.get("reason", "blocked")})
            for obj in objs:
                rej_objekte.append({**obj, "reject_reason": result.get("reason", "blocked")})

    # ── Process remaining concurrently ────────────────────────
    semaphore = asyncio.Semaphore(CONCURRENCY)
    processed_batch = {}

    async def process_one(session, contact):
        async with semaphore:
            result = await check_contact(session, contact)
            return contact, result

    async with aiohttp.ClientSession() as session:
        tasks = [process_one(session, c) for c in remaining]
        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            contact, result = await coro
            ext_id = contact["external_id"]
            action = result["action"]
            adv_id = result.get("advertiser_id")
            objs   = objekte_by_contact.get(ext_id, [])

            if action == "keep":
                new_ext_id = get_next_external_id()
                contact["external_id"] = new_ext_id
                valid_contacts.append(contact)
                for obj in objs:
                    obj = dict(obj)
                    obj["contact_external_id"] = new_ext_id
                    valid_objekte.append(obj)
                result["new_external_id"] = new_ext_id

            elif action == "skip_contact":
                # Objects kept; contact_external_id cleared; advertiser_id set
                for obj in objs:
                    obj = dict(obj)
                    obj["contact_external_id"] = ""
                    obj["advertiser_id"] = str(adv_id) if adv_id else ""
                    valid_objekte.append(obj)

            else:  # drop
                rej_contacts.append({**contact, "reject_reason": "blocked by API"})
                for obj in objs:
                    rej_objekte.append({**dict(obj), "reject_reason": "blocked by API"})

            # Save progress every 50
            processed_batch[ext_id] = result
            completed += 1
            if completed % 50 == 0:
                progress.update(processed_batch)
                save_progress(progress)
                processed_batch.clear()
                logging.info(f"--- Progress: {completed}/{total} API checks done ---")

        # Final progress flush
        if processed_batch:
            progress.update(processed_batch)
            save_progress(progress)

    # ── Write output files ────────────────────────────────────

    # Kontakte_phase5.csv — only "keep" contacts
    with open(OUT_KONTAKTE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kontakte_fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(valid_contacts)

    # Objekte_phase5.csv — keep + skip_contact objects
    with open(OUT_OBJEKTE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=objekte_fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(valid_objekte)

    # rejected_kontakte_phase5.csv
    rej_k_fields = kontakte_fields + ["reject_reason"]
    with open(REJ_KONTAKTE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rej_k_fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rej_contacts)

    # rejected_objekte_phase5.csv
    rej_o_fields = objekte_fields + ["reject_reason"]
    with open(REJ_OBJEKTE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rej_o_fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rej_objekte)

    # ── Summary ───────────────────────────────────────────────
    logging.info("")
    logging.info("=" * 60)
    logging.info("PHASE 5 COMPLETE — SUMMARY")
    logging.info("=" * 60)
    logging.info(f"  Contacts checked        : {len(all_contacts)}")
    logging.info(f"  ✅ Kept (not found)     : {len(valid_contacts)}")
    logging.info(f"  ⏭️  Skip contact (found) : {sum(1 for r in progress.values() if r['action'] == 'skip_contact')}")
    logging.info(f"  ❌ Dropped (blocked)    : {len(rej_contacts)}")
    logging.info(f"  ✅ Valid objects         : {len(valid_objekte)}")
    logging.info(f"  ❌ Rejected objects      : {len(rej_objekte)}")
    logging.info("")
    logging.info(f"  OUTPUT FILES:")
    logging.info(f"    {OUT_KONTAKTE}")
    logging.info(f"    {OUT_OBJEKTE}")
    logging.info(f"    {REJ_KONTAKTE}")
    logging.info(f"    {REJ_OBJEKTE}")


if __name__ == "__main__":
    asyncio.run(main())
