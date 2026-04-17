import asyncio
import re
import os
import logging
import config
import argparse
import math
import random
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.PHASE1_SCRAPER_LOG, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

async def solve_waf(page, mode_name="SCRAPER"):
    """Deeper check and wait for Azure WAF or JS challenges to pass."""
    for i in range(12): # Wait up to 36 seconds
        try:
            title = await page.title()
            content = await page.content()
        except:
            return False

        waf_indicators = [
            "Azure WAF",
            "bot check",
            "checking you're not a bot",
            "One moment",
            "Verify you are human"
        ]
        
        is_blocked = False
        for indicator in waf_indicators:
            if indicator.lower() in title.lower() or indicator.lower() in content.lower():
                is_blocked = True
                break
        
        if is_blocked:
            logging.info(f"[{mode_name}] WAF/Challenge detected (Attempt {i+1}/12). Waiting 60s (COOLDOWN)...")
            await asyncio.sleep(60) # Increased cooldown to let session settle
            # Try some basic interaction to help JS challenges
            try:
                await page.mouse.move(100, 100)
                await page.mouse.move(200, 200)
            except: pass
        else:
            if i > 0:
                logging.info(f"[{mode_name}] WAF/Challenge cleared!")
            return True
            
    logging.warning(f"[{mode_name}] WAF/Challenge still present after 36s.")
    return False

class ProperStarPhase1:
    def __init__(self, mode="buy", start_min=0, max_limit=10000000, concurrency=5):
        self.mode = mode # "buy" or "rent"
        self.start_min = start_min
        self.max_limit = max_limit
        self.concurrency = concurrency
        self.base_url = f"https://www.properstar.ch/switzerland/{self.mode}/apartment-house"
        
        self.output_file = config.BUY_URLS_FILENAME if mode == "buy" else config.RENT_URLS_FILENAME
        self.scraped_urls = set()
        self.stop_requested = False
        self.load_existing_urls()
        self.semaphore = asyncio.Semaphore(self.concurrency)

    def load_existing_urls(self):
        if os.path.exists(self.output_file):
            with open(self.output_file, 'r', encoding='utf-8') as f:
                for line in f:
                    self.scraped_urls.add(line.strip())
            logging.info(f"Loaded {len(self.scraped_urls)} existing URLs for {self.mode}.")

    def append_urls(self, urls, limit=0):
        if self.stop_requested: return []
        new_urls = []
        for url in urls:
            if url not in self.scraped_urls:
                self.scraped_urls.add(url)
                new_urls.append(url)
        
        if new_urls:
            with open(self.output_file, 'a', encoding='utf-8') as f:
                for url in new_urls:
                    f.write(url + '\n')
            logging.info(f"[{self.mode.upper()}] Appended {len(new_urls)} new URLs to {self.output_file}")
            
            if limit > 0 and len(self.scraped_urls) >= limit:
                logging.info(f"[{self.mode.upper()}] TARGET LIMIT REACHED ({len(self.scraped_urls)}). Requesting stop.")
                self.stop_requested = True

        return new_urls

    async def get_page_data(self, browser_context, min_price, max_price, page_num=1):
        """Fetches a single page of results and returns (total_count, urls)"""
        async with self.semaphore:
            url = self.base_url
            params = []
            if min_price > 0:
                params.append(f"price.min={min_price}")
            if max_price > 0:
                params.append(f"price.max={max_price}")
            if page_num > 1:
                params.append(f"p={page_num}")
                
            if params:
                url += "?" + "&".join(params)
                
            logging.info(f"[{self.mode.upper()}] Loading Page {page_num}: {url}")
            
            # Anti-detection Jitter
            jitter = random.uniform(0.5, 3.0)
            await asyncio.sleep(jitter)
            
            # User Agent Rotation
            ua_list = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            ]
            
            page = await browser_context.new_page()
            await page.set_extra_http_headers({"User-Agent": random.choice(ua_list)})
            await Stealth().apply_stealth_async(page)
            
            try:
                for attempt in range(3):
                    try:
                        await page.goto(url, wait_until="commit", timeout=45000)
                        # Use the new solve_waf logic
                        if not await solve_waf(page, mode_name=self.mode.upper()):
                            logging.warning(f"[{self.mode.upper()}] Failed to bypass WAF on Page {page_num}.")
                            return None, []

                        # Wait for results to be sure
                        try:
                            await page.wait_for_selector('a[href*="/listing/"], a[href*="/annonce/"]', timeout=10000)
                        except:
                            pass
                        
                        await asyncio.sleep(2)
                        
                        # Extra check after sleep
                        if not await solve_waf(page, mode_name=self.mode.upper()):
                            logging.warning(f"[{self.mode.upper()}] WAF Block detected (after settling).")
                            return None, []
                        
                        results_text = await page.evaluate(r"""() => {
                            const selectors = ['.total-results', 'h1 + div', '.total-results span', '.breadcrumb-text + div'];
                            for (const s of selectors) {
                                const el = document.querySelector(s);
                                if (el && el.innerText.includes('result')) return el.innerText;
                            }
                            // Don't use title as fallback if it looks like a generic/WAF title
                            const title = document.title;
                            if (title && (title.includes('results') || title.includes('Properties'))) return title;
                            const match = document.body.innerText.match(/(\d[\d,\.]*)\s+results/i);
                            return match ? match[0] : '';
                        }""")
                        
                        total_results = 0
                        if results_text:
                            match = re.search(r'([\d,\.\']+)', results_text)
                            if match:
                                num_str = match.group(1).replace(',', '').replace('.', '').replace("'", "")
                                try: total_results = int(num_str)
                                except: total_results = 2001
                        elif await page.evaluate("() => !!document.querySelector('a[href*=\"/listing/\"], a[href*=\"/annonce/\"]')"):
                            total_results = 2001

                        urls = await page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('a[href*="/listing/"], a[href*="/annonce/"]'))
                                        .map(a => a.getAttribute('href'));
                        }""")
                        
                        clean_urls = []
                        if urls:
                            for u in urls:
                                if u and ('/listing/' in u or '/annonce/' in u):
                                    base = u.split('?')[0]
                                    if base.startswith('/'): base = "https://www.properstar.ch" + base
                                    clean_urls.append(base)
                        
                        if not clean_urls:
                            # Diagnostic: Save HTML if we see nothing but think we cleared WAF
                            debug_file = "debug_empty_results.html"
                            with open(debug_file, "w", encoding="utf-8") as df:
                                df.write(await page.content())
                            logging.warning(f"[{self.mode.upper()}] SELECTOR FAIL: Found 0 listing URLs. Saved HTML to {debug_file}")

                        return total_results, list(set(clean_urls))
                        
                    except Exception as e:
                        if attempt == 2: raise e
                        await asyncio.sleep(5)
            except Exception as e:
                logging.warning(f"[{self.mode.upper()}] Failed page {page_num}: {e}")
                return None, []
            finally:
                await page.close()
                
        logging.error(f"Failed to fetch {url} after 3 attempts.")
        return None, []

    async def find_optimal_step(self, context, min_price, current_step, limit=0):
        """Finds the largest possible max_price such that results are <= 2000."""
        if self.stop_requested: return None, None, current_step
        logging.info(f"[{self.mode.upper()}] Probing range starting at {min_price}...")
        
        max_price = min_price + current_step
        total, _ = await self.get_page_data(context, min_price, max_price, 1)
        
        if total is None or self.stop_requested:
            return None, None, current_step
            
        if total > 2000:
            low = min_price
            high = max_price
            best_max = min_price + 100
            for _ in range(4):
                mid = (low + high) // 2
                t, _ = await self.get_page_data(context, min_price, mid, 1)
                if t is None: return None, None, current_step
                if t > 2000: high = mid
                else: best_max = mid; low = mid
            return best_max, min(2000, t), max(1000, best_max - min_price)
        return max_price, total, current_step

    async def run(self, browser, limit=0):
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
        
        # Initial Setup (WAF)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        logging.info(f"[{self.mode.upper()}] Solving initial WAF challenge...")
        try:
            await page.goto("https://www.properstar.ch", wait_until="commit")
            await asyncio.sleep(5)
        except: pass
        await page.close()
            
        min_price = self.start_min
        step = 500000 if self.mode == "buy" else 5000
        
        # ── FAST TEST BYPASS ──────────────────────────────────────
        if limit > 0:
            logging.info(f"[{self.mode.upper()}] FAST TEST MODE: Grabbing first page only.")
            total, urls = await self.get_page_data(context, 0, 0, 1) # No price filter
            if urls:
                self.append_urls(urls[:limit], limit=limit)
            return # Finish immediately
            
        while min_price <= self.max_limit and not self.stop_requested:
            # Find optimal max_price
            max_price, total, step = await self.find_optimal_step(context, min_price, step, limit=limit)
            
            if total is None:
                logging.warning(f"[{self.mode.upper()}] Bucket probe failed (WAF). Retrying bucket in 15s...")
                await asyncio.sleep(15)
                continue
                
            if total == 0:
                min_price = max_price + 1
                continue
                
            total_pages = min(math.ceil(total / 20), 100)
            logging.info(f"[{self.mode.upper()}] Bucket [{min_price} - {max_price}] has {total} results ({total_pages} pages)")
            
            # Fetch all pages in this bucket concurrently
            tasks = [self.get_page_data(context, min_price, max_price, p) for p in range(1, total_pages + 1)]
            
            # Use as_completed to process and log results as soon as they finish
            for task in asyncio.as_completed(tasks):
                try:
                    p_total, page_urls = await task
                    if p_total is None or self.stop_requested:
                        logging.warning(f"[{self.mode.upper()}] Stopping task processing.")
                        continue
                    if page_urls and not self.stop_requested:
                        self.append_urls(page_urls, limit=limit)
                except Exception as e:
                    logging.error(f"[{self.mode.upper()}] Task failed: {e}")
                    
            min_price = max_price + 1

            
        logging.info(f"[{self.mode.upper()}] Finished. Total URLs: {len(self.scraped_urls)}")


async def main():
    parser = argparse.ArgumentParser(description="ProperStar Phase 1 Scraper (High Speed)")
    parser.add_argument("--concurrency", type=int, default=2, help="Pages per mode (total = 2 * concurrency)")
    parser.add_argument("--limit", type=int, default=0, help="Stop after finding N URLs per mode")
    args = parser.parse_args()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        buy_scraper = ProperStarPhase1(mode="buy", start_min=0, max_limit=50000000, concurrency=args.concurrency)
        rent_scraper = ProperStarPhase1(mode="rent", start_min=0, max_limit=100000, concurrency=args.concurrency)
        
        logging.info(f"Starting concurrent scrapers (Concurrency: {args.concurrency} per mode, Limit: {args.limit})")
        await asyncio.gather(
            buy_scraper.run(browser, limit=args.limit),
            rent_scraper.run(browser, limit=args.limit)
        )
        
        await browser.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user. Exiting gracefully...")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
