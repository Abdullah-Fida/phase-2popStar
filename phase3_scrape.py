"""
Phase 3 — Property Detail Scraper (Rewritten)
==============================================
Reads URLs from phase2_api_tested.txt, visits each listing page,
extracts data using EXACT CSS selectors confirmed from live DOM inspection.

KEY CHANGES vs old version:
  - Name  : .account-content.agent h4.account-name  (agent only, not agency)
  - Phone : .account-content.agent .agent-contacts-value  + click Show button
  - Coords: .static-map-image [style] → Google Maps center=lat%2Clon
  - DISCARD if name OR phone not found (no partial saves)
"""

import asyncio
import csv
import json
import logging
import os
import re
import random
import argparse
from datetime import datetime
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import config
import supabase_helper

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.PHASE3_LOG_FILENAME, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ── Shared State ─────────────────────────────────────────────────────────────
seen_contacts    = {}   # (normalized_phone, lower_name) -> contact_external_id
listing_id_counter  = 0
contact_id_counter  = 0
processed_count     = 0
total_url_count     = 0
buy_url_set         = set()


# ── ID Persistence ───────────────────────────────────────────────────────────
def initialize_id_counter():
    """Dynamically determine the highest external_id already saved to prevent overlap."""
    global contact_id_counter, listing_id_counter
    start_id = getattr(config, 'START_ID', 300000)
    contact_id_counter = start_id
    listing_id_counter = start_id
    
    if os.path.exists(config.KONTAKTE_FILENAME):
        try:
            with open(config.KONTAKTE_FILENAME, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                max_id = start_id
                for row in reader:
                    try:
                        ext_id = int(row.get('external_id', 0))
                        if ext_id > max_id:
                            max_id = ext_id
                    except ValueError:
                        pass
                contact_id_counter = max_id
        except Exception as e:
            logging.error(f"Failed to read highest ID from Kontakte.csv: {e}")
            
    logging.info(f"Initialized contact_id_counter to {contact_id_counter}")


# ── Helpers ──────────────────────────────────────────────────────────────────
def clean_price(price_text):
    if not price_text:
        return None
    cleaned = re.sub(r'[^\d]', '', price_text)
    try:
        return int(cleaned)
    except Exception:
        return None


def normalize_phone(phone_text):
    if not phone_text:
        return ""
    phone_text = re.sub(r'\(0\)', '', str(phone_text))
    cleaned = re.sub(r'[^\d\+]', '', phone_text)
    if not cleaned:
        return ""
    if cleaned.startswith('00'):
        cleaned = '+' + cleaned[2:]
    elif cleaned.startswith('0'):
        cleaned = '+41' + cleaned[1:]
    elif cleaned.startswith('+'):
        pass
    elif cleaned.startswith('41') and len(cleaned) >= 11:
        cleaned = '+' + cleaned
    elif len(cleaned) == 9:
        cleaned = '+41' + cleaned
    else:
        cleaned = '+' + cleaned

    # Swiss numbers: +41 + 9 digits = 12 chars. Strip extra 0 after country code.
    if cleaned.startswith('+410') and len(cleaned) > 12:
        cleaned = '+41' + cleaned[4:]

    return cleaned


# ── WAF Solver ───────────────────────────────────────────────────────────────
async def solve_waf(page, mode_name="SCRAPER"):
    """Wait out Azure WAF / JS challenges (up to 36 s)."""
    for i in range(12):
        try:
            title   = await page.title()
            content = await page.content()
        except Exception:
            return False

        waf_indicators = [
            "azure waf", "bot check", "checking you're not a bot",
            "one moment", "verify you are human"
        ]
        blocked = any(ind in title.lower() or ind in content.lower() for ind in waf_indicators)

        if blocked:
            logging.info(f"[{mode_name}] WAF detected (attempt {i+1}/12). Waiting 3 s…")
            await asyncio.sleep(3)
            try:
                await page.mouse.move(100, 100)
                await page.mouse.move(200, 200)
            except Exception:
                pass
        else:
            if i > 0:
                logging.info(f"[{mode_name}] WAF cleared.")
            return True

    logging.warning(f"[{mode_name}] WAF still present after 36 s.")
    return False


# ── Core Extraction ──────────────────────────────────────────────────────────
async def extract_listing_data(page, url):
    """
    Scrape a single listing page.
    Returns a dict on success, None if the listing must be discarded.
    Discard reasons:
      - Page load failure / WAF timeout
      - No individual contact name found
      - No valid phone number after Show-reveal attempt
    """
    # ── Load page ────────────────────────────────────────────────────────────
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await solve_waf(page)
        await page.wait_for_selector('h1', timeout=20000)
    except Exception as e:
        logging.error(f"Load error for {url}: {e}")
        return None

    data = {'detail_url': url}

    try:
        # ── 1. Title ─────────────────────────────────────────────────────────
        data['title'] = (await page.locator('h1').first.inner_text()).strip()

        # ── 2. Price ─────────────────────────────────────────────────────────
        price_loc = page.locator('.listing-price-main span, .price')
        if await price_loc.count() > 0:
            price_text = (await price_loc.first.inner_text()).strip()
            # Check if the price text is meaningful or just a placeholder
            price_numeric = clean_price(price_text)
            if price_numeric:
                data['price']       = price_text
                data['price_value'] = price_numeric
            else:
                # Price element exists but has no numeric value (e.g., "On request")
                data['price']       = "Contact to get price"
                data['price_value'] = None
        else:
            # No price element at all — must contact for price
            data['price']       = "Contact to get price"
            data['price_value'] = None

        # ── 3. Description ───────────────────────────────────────────────────
        desc_loc = page.locator('.collapse-description, .description-text')
        data['description'] = (await desc_loc.first.inner_text()).strip() if await desc_loc.count() > 0 else ""

        # ── 4. Address ───────────────────────────────────────────────────────
        data.update({'street': '', 'house_number': '', 'zip_code': '', 'city': ''})
        addr_loc  = page.locator('.address span, .item-info-address-inner-address')
        addr_text = (await addr_loc.first.inner_text()).strip() if await addr_loc.count() > 0 else ""

        if addr_text:
            addr_text  = addr_text.split('\n')[0].strip()
            addr_parts = [p.strip() for p in addr_text.split(',')
                          if p.strip() and p.strip().lower() != 'switzerland']

            zip_idx = -1
            for i, part in enumerate(addr_parts):
                m = re.match(r'^(?:[A-Z]{1,2}[-\s])?(\d{4,5})\s+(.*)$', part)
                if m:
                    data['zip_code'] = m.group(1).strip()
                    data['city']     = m.group(2).strip()
                    zip_idx          = i
                    break

            def split_street(st_part):
                m1 = re.match(r'^(.*?)\s+(\d+[a-zA-Z]*)$', st_part)
                m2 = re.match(r'^(\d+[a-zA-Z]*)\s+(.*?)$', st_part)
                if m1:
                    return m1.group(1).strip(), m1.group(2).strip()
                if m2:
                    return m2.group(2).strip(), m2.group(1).strip()
                return st_part, ''

            if zip_idx > 0:
                data['street'], data['house_number'] = split_street(addr_parts[0])
            elif zip_idx == 0 and len(addr_parts) > 1:
                data['street'], data['house_number'] = split_street(addr_parts[1])
            elif zip_idx == -1 and addr_parts:
                if len(addr_parts) == 1:
                    st, hn = split_street(addr_parts[0])
                    if hn:
                        data['street'], data['house_number'] = st, hn
                    else:
                        data['city'] = addr_parts[0]
                else:
                    data['street'], data['house_number'] = split_street(addr_parts[0])
                    data['city'] = addr_parts[-1]

        # ── 5. Coordinates ───────────────────────────────────────────────────
        data['latitude']  = ""
        data['longitude'] = ""

        content = await page.content()
        
        # 5a. Primary: Structural JSON Parse from window.__INITIAL_STATE__
        try:
            # Extract listing ID from URL (e.g., .../listing/12345 or /annonce/12345)
            id_match = re.search(r'/(?:listing|annonce)/(\d+)', url)
            if id_match:
                listing_id = id_match.group(1)
                # Find the INITIAL_STATE script block
                json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});</script>', content, re.DOTALL)
                if not json_match:
                    # Some pages might not have the semicolon or might be slightly different
                    json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?})</script>', content, re.DOTALL)
                
                if json_match:
                    js_data = json.loads(json_match.group(1))
                    listing_obj = js_data.get('entities', {}).get('listing', {}).get(listing_id, {})
                    if not listing_obj:
                        # Fallback: maybe it's the only listing in the dictionary
                        listings = js_data.get('entities', {}).get('listing', {})
                        if len(listings) == 1:
                            listing_obj = list(listings.values())[0]

                    if listing_obj and 'location' in listing_obj:
                        data['latitude']  = str(listing_obj['location'].get('latitude', ''))
                        data['longitude'] = str(listing_obj['location'].get('longitude', ''))
        except Exception as e:
            logging.debug(f"JSON coordinate extraction failed for {url}: {e}")

        # 5b. Fallback: Exact values from generic JSON payload regex
        if not data['latitude'] or not data['longitude']:
            m_lat = re.search(r'"latitude":\s*([\-\d\.]+)', content, re.IGNORECASE)
            m_lng = re.search(r'"longitude":\s*([\-\d\.]+)', content, re.IGNORECASE)
            if m_lat and m_lng:
                data['latitude']  = m_lat.group(1)
                data['longitude'] = m_lng.group(1)

        # 5c. Fallback: Google Maps URL in .static-map-image (check markers first for exact pin, then center)
        if not data['latitude'] or not data['longitude']:
            map_loc = page.locator('.static-map-image')
            if await map_loc.count() > 0:
                style = await map_loc.first.get_attribute('style') or ""
                # markers=color:red|label:C|47.545259%2C8.981492
                m_markers = re.search(r'markers.*?%7C([\-\d\.]+)(?:%2C|,)([\-\d\.]+)', style, re.IGNORECASE)
                if m_markers:
                    data['latitude']  = m_markers.group(1)
                    data['longitude'] = m_markers.group(2)
                else:
                    m_center = re.search(r'center=([\-\d\.]+)(?:%2C|,)([\-\d\.]+)', style, re.IGNORECASE)
                    if m_center:
                        data['latitude']  = m_center.group(1)
                        data['longitude'] = m_center.group(2)

        # ── 6. Property Attributes ───────────────────────────────────────────
        data.update({'rooms': '', 'living_space_area': '', 'land_area': ''})
        for item in await page.query_selector_all('.feature-item'):
            key = await item.query_selector('.property-key')
            val = await item.query_selector('.property-value')
            if key and val:
                k_t = await key.inner_text()
                v_t = await val.inner_text()
                if 'Rooms'       in k_t: data['rooms']            = v_t
                if 'Living area' in k_t: data['living_space_area'] = v_t.replace(' m²', '').replace(',', '')
                if 'Total'       in k_t: data['land_area']         = v_t.replace(' m²', '').replace(',', '')

        # ── 7. Individual Contact & Organization Name ───────────────────────────────
        # Name —— h4.account-name inside the AGENT section
        name_loc     = page.locator('.account-content.agent h4.account-name')
        contact_name = (await name_loc.first.inner_text()).strip() if await name_loc.count() > 0 else ""

        # ── 8. Organization / Agency Name ────────────────────────────────────
        org_name = ""
        org_loc = page.locator('.account-content.agency h4.account-name')
        if await org_loc.count() > 0:
            org_name = (await org_loc.first.inner_text()).strip()
        else:
            org_loc_fallback = page.locator('.account-content.agency .account-name')
            if await org_loc_fallback.count() > 0:
                org_name = (await org_loc_fallback.first.inner_text()).strip()

        if not contact_name and not org_name:
            logging.warning(f"No individual contact or org name — discarding {url}")
            return None

        # Phone —— .agent-contacts-value inside the AGENT block
        phone_loc = page.locator('.account-content.agent .agent-contacts-value')
        phone     = (await phone_loc.first.inner_text()).strip() if await phone_loc.count() > 0 else ""

        # If truncated ("+41 0..."), click the Show button and wait for reveal
        if not phone or '...' in phone:
            show_btn = page.locator('button[data-gtm-click="show-phone-listing-click"]')
            if await show_btn.count() > 0:
                try:
                    await show_btn.first.click()
                    await asyncio.sleep(2.5)
                    # Re-read the same span — it should now contain the full number
                    phone = (await phone_loc.first.inner_text()).strip() if await phone_loc.count() > 0 else ""
                except Exception as e:
                    logging.warning(f"Show button click failed for {url}: {e}")

        # Fallback: check for a tel: link inside the AGENT block
        if not phone or '...' in phone or len(phone) < 5:
            tel_loc = page.locator('.account-content.agent a[href^="tel:"]')
            if await tel_loc.count() > 0:
                href  = await tel_loc.first.get_attribute('href') or ""
                phone = href.replace('tel:', '').strip()

        if not phone or '...' in phone or len(phone) < 5:
            logging.warning(f"No valid phone after Show reveal — discarding {url}")
            return None

        # Split full name → first / last
        name_parts        = contact_name.split(' ', 1)
        data['first_name']  = name_parts[0] if len(name_parts) > 0 else ""
        data['last_name']   = name_parts[1] if len(name_parts) > 1 else ""
        data['contact_name']= contact_name
        data['phone']       = phone.strip()
        data['organization_name'] = org_name

        return data

    except Exception as e:
        logging.error(f"Extraction error for {url}: {e}")
        return None


# ── Worker ───────────────────────────────────────────────────────────────────
async def worker(queue, results_obj, results_con, results_rej, semaphore, worker_id):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={'width': 1280, 'height': 800}
        )
        stealth = Stealth()

        while True:
            try:
                url = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            global listing_id_counter, contact_id_counter, processed_count

            async with semaphore:
                page = await context.new_page()
                await stealth.apply_stealth_async(page)

                try:
                    logging.info(f"[W{worker_id}] Processing: {url}")

                    # Up to 3 attempts per URL
                    listing = None
                    for attempt in range(3):
                        listing = await extract_listing_data(page, url)
                        if listing is not None:
                            break
                        if attempt < 2:
                            logging.warning(f"[W{worker_id}] Retry {attempt+1}/3 for {url}")
                            await asyncio.sleep(3)

                    processed_count += 1
                    if processed_count % 50 == 0:
                        remaining = total_url_count - processed_count
                        logging.info(
                            f"--- Progress: {processed_count}/{total_url_count} done "
                            f"| {remaining} remaining ---"
                        )

                    if listing:
                        # Buy / Rent detection
                        is_buy = url in buy_url_set

                        # Skip very cheap rent listings ONLY if price is known
                        # If price_value is None ("Contact to get price"), always keep the listing
                        if (not is_buy
                                and listing['price_value'] is not None
                                and listing['price_value'] < config.MIN_RENT_CHF):
                            logging.info(
                                f"Skipping low rent {url} ({listing['price_value']} CHF)"
                            )
                            results_rej.append({
                                'url': url,
                                'reason': f"Low rent ({listing['price_value']} CHF)"
                            })
                        else:
                            # ── Contact deduplication ──────────────────────
                            norm_phone  = normalize_phone(listing['phone'])
                            hash_name   = listing['contact_name'] if listing['contact_name'] else listing['organization_name']
                            contact_key = (norm_phone, hash_name.lower())

                            if contact_key not in seen_contacts:
                                contact_id_counter += 1
                                c_id = str(contact_id_counter)
                                seen_contacts[contact_key] = c_id
                                contact_obj = {
                                    'external_id':       c_id,
                                    'first_name':        listing['first_name'],
                                    'last_name':         listing['last_name'],
                                    'organization_name': listing['organization_name'],
                                    'email':             '',
                                    'phone':             listing['phone'],
                                    'street':            '',
                                    'house_number':      '',
                                    'zip_code':          '',
                                    'city':              '',
                                    'normalized_phone':  norm_phone,
                                    'portal_id':         config.PORTAL_ID,
                                    'vendor_id':         config.VENDOR_ID,
                                }
                                results_con.append(contact_obj)
                                if use_supabase:
                                    try:
                                        supabase_helper.save_contact(contact_obj)
                                    except Exception as e:
                                        logging.error(f"[W{worker_id}] Supabase save_contact failed: {e}")

                            c_ext_id = seen_contacts[contact_key]

                            # ── Listing record ─────────────────────────────
                            listing_id_counter += 1
                            listing_obj = {
                                'contact_external_id': c_ext_id,
                                'portal_id':           config.PORTAL_ID,
                                'vendor_id':           config.VENDOR_ID,
                                'type_id':             "1" if is_buy else "2",
                                'detail_url':          url,
                                'title':               listing.get('title', ''),
                                'description':         listing.get('description', ''),
                                'street':              listing.get('street', '')[:255],
                                'house_number':        listing.get('house_number', ''),
                                'zip_code':            listing.get('zip_code', ''),
                                'city':                listing.get('city', ''),
                                'latitude':            listing.get('latitude', ''),
                                'longitude':           listing.get('longitude', ''),
                                'price':               listing.get('price', ''),
                                'living_space_area':   listing.get('living_space_area', ''),
                                'land_area':           listing.get('land_area', ''),
                                'rs_category_id':      '',
                                'price_value':         listing.get('price_value', ''),
                                'advertiser_id':       '',
                                'advertisement_id':    str(listing_id_counter),
                            }
                            results_obj.append(listing_obj)
                            if use_supabase:
                                try:
                                    supabase_helper.save_listing(listing_obj)
                                    supabase_helper.mark_url_done(url)
                                except Exception as e:
                                    logging.error(f"[W{worker_id}] Supabase save_listing/mark_url_done failed: {e}")
                                    
                            logging.info(
                                f"[W{worker_id}] OK: {listing['title']}"
                                f" | {listing['first_name']} {listing['last_name']}"
                                f" | {listing['phone']}"
                            )
                    else:
                        results_rej.append({'url': url, 'reason': 'No valid contact or load failure'})
                        if use_supabase:
                            try:
                                supabase_helper.mark_url_failed(url)
                            except Exception as e:
                                logging.error(f"[W{worker_id}] Supabase mark_url_failed failed: {e}")

                except Exception as e:
                    logging.error(f"[W{worker_id}] Exception for {url}: {e}")
                    results_rej.append({'url': url, 'reason': f"Worker exception: {e}"})
                    if use_supabase:
                        try:
                            supabase_helper.mark_url_failed(url)
                        except Exception as sup_e:
                            logging.error(f"[W{worker_id}] Supabase mark_url_failed failed: {sup_e}")
                finally:
                    await page.close()

            queue.task_done()
            await asyncio.sleep(random.uniform(0.4, 1.0))

        await browser.close()


# ── Resume Helper ─────────────────────────────────────────────────────────────
def load_already_processed_urls():
    """Read phase3 log to find all URLs already attempted."""
    done    = set()
    pattern = re.compile(r'\] Processing: (https?://\S+)')
    log_path = config.PHASE3_LOG_FILENAME
    if not os.path.exists(log_path):
        return done
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                done.add(m.group(1).strip())
    return done


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Phase 3 — ProperStar listing scraper")
    parser.add_argument("--workers", type=int, default=14, help="Number of parallel browser workers")
    parser.add_argument("--limit",   type=int, default=0,  help="Max URLs to process (0 = all)")
    parser.add_argument("--supabase", action="store_true", help="Enable Supabase resume/save mode")
    args = parser.parse_args()

    global use_supabase
    use_supabase = args.supabase

    initialize_id_counter()

    # Load buy URL set for type_id determination
    global buy_url_set
    if os.path.exists(config.BUY_URLS_FILENAME):
        with open(config.BUY_URLS_FILENAME, 'r', encoding='utf-8') as f:
            buy_url_set = {line.strip() for line in f if line.strip()}
        logging.info(f"Loaded {len(buy_url_set)} buy URLs.")
    else:
        logging.warning("buy_urls.txt not found — all listings will default type_id=2 (rent).")

    # Initialise CSVs if they don't exist yet
    for filename, columns in [
        (config.OBJEKTE_FILENAME,         config.OBJEKTE_COLUMNS),
        (config.KONTAKTE_FILENAME,        config.KONTAKTE_COLUMNS),
        (config.PHASE3_REJECTED_FILENAME, ['url', 'reason']),
    ]:
        if not os.path.exists(filename):
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                csv.DictWriter(f, fieldnames=columns).writeheader()

    if use_supabase:
        logging.info("Supabase mode enabled: fetching pending URLs...")
        # 1. Fetch ALL urls from Supabase to rebuild buy_url_set (we still need this to know if it's buy or rent)
        # 2. Fetch PENDING urls for processing
        try:
            all_db_urls = supabase_helper.fetch_all_urls()
            # Overwrite global buy_url_set based on Supabase type='buy'
            buy_url_set = {row['url'] for row in all_db_urls if row.get('type') == 'buy'}
            logging.info(f"Supabase mode: Rebuilt buy_url_set with {len(buy_url_set)} items.")

            # Filter only pending
            pending_db_rows = [r for r in all_db_urls if r.get('status') == 'pending']
            urls = [row['url'] for row in pending_db_rows]
            logging.info(f"Supabase mode: Found {len(urls)} PENDING URLs to scrape.")
            
            # Since Supabase manages state, we don't strictly need local log resume, 
            # but we can still exclude any we just scraped this session if the queue gets messed up.
            already_done = load_already_processed_urls()
            urls = [u for u in urls if u not in already_done]
            logging.info(f"Remaining after local log check: {len(urls)}")
            
        except Exception as e:
            logging.error(f"Failed to fetch URLs from Supabase: {e}")
            import sys
            sys.exit(1)
            
    else:
        # ── Old Local File Logic ──
        if not os.path.exists(config.PHASE2_TESTED_FILENAME):
            logging.error(f"Input file not found: {config.PHASE2_TESTED_FILENAME}")
            return

        with open(config.PHASE2_TESTED_FILENAME, 'r') as f:
            all_urls = [line.strip() for line in f if '/listing/' in line or '/annonce/' in line]
        
        logging.info(f"Loaded {len(all_urls)} total URLs from master list.")

        # Skip already-processed URLs (resume support)
        already_done = load_already_processed_urls()
        urls = [u for u in all_urls if u not in already_done]

        logging.info(
            f"Total: {len(all_urls)} | Done: {len(already_done)} | Remaining: {len(urls)}"
        )

    if args.limit > 0:
        urls = urls[:args.limit]
        logging.info(f"LIMIT: processing first {args.limit} remaining URLs.")

    global total_url_count
    total_url_count = len(urls)

    # Fill queue
    queue = asyncio.Queue()
    for url in urls:
        queue.put_nowait(url)

    results_obj = []
    results_con = []
    results_rej = []
    semaphore   = asyncio.Semaphore(20)  # max concurrent pages

    tasks = [
        asyncio.create_task(
            worker(queue, results_obj, results_con, results_rej, semaphore, i)
        )
        for i in range(args.workers)
    ]

    # Periodic saver — flushes every 20 s
    async def saver():
        while not queue.empty() or any(not t.done() for t in tasks):
            await asyncio.sleep(20)
            _flush(results_obj, results_con, results_rej)

    def _flush(obj_buf, con_buf, rej_buf):
        if obj_buf:
            with open(config.OBJEKTE_FILENAME, 'a', newline='', encoding='utf-8') as f:
                csv.DictWriter(
                    f, fieldnames=config.OBJEKTE_COLUMNS,
                    extrasaction='ignore', quoting=csv.QUOTE_ALL
                ).writerows(obj_buf)
            obj_buf.clear()
        if con_buf:
            with open(config.KONTAKTE_FILENAME, 'a', newline='', encoding='utf-8') as f:
                csv.DictWriter(
                    f, fieldnames=config.KONTAKTE_COLUMNS,
                    extrasaction='ignore', quoting=csv.QUOTE_ALL
                ).writerows(con_buf)
            con_buf.clear()
        if rej_buf:
            with open(config.PHASE3_REJECTED_FILENAME, 'a', newline='', encoding='utf-8') as f:
                csv.DictWriter(
                    f, fieldnames=['url', 'reason'],
                    extrasaction='ignore', quoting=csv.QUOTE_ALL
                ).writerows(rej_buf)
            rej_buf.clear()

    saver_task = asyncio.create_task(saver())
    await asyncio.gather(*tasks)
    # Final flush after all workers finish
    _flush(results_obj, results_con, results_rej)
    await saver_task

    logging.info("=== PHASE 3 COMPLETE ===")


if __name__ == "__main__":
    asyncio.run(main())
