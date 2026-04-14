import asyncio
import httpx
import json
import logging
import os
import config
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.PHASE2_LOG_FILENAME, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

API_URL = "https://api.we-net.ch/api/listings/check-url"
CONCURRENT_REQUESTS = 20  # Limit to 20 concurrent requests

async def check_url(client, url, semaphore):
    async with semaphore:
        for attempt in range(3):
            try:
                response = await client.post(
                    API_URL, 
                    json={"detail_url": url}, 
                    timeout=10.0
                )
                if response.status_code in [200, 404]:
                    return response.json()
                elif response.status_code == 429:
                    logging.warning(f"Rate limited (429) for {url}. Waiting 5s...")
                    await asyncio.sleep(5)
                else:
                    logging.error(f"Error {response.status_code} for {url}: {response.text}")
            except Exception as e:
                logging.error(f"Exception for {url} (Attempt {attempt+1}): {e}")
                await asyncio.sleep(1)
        return None

async def process_file(file_path, mode):
    if not os.path.exists(file_path):
        logging.error(f"File not found: {file_path}")
        return

    new_file = config.PHASE2_TESTED_FILENAME
    rejected_file = config.PHASE2_REJECTED_FILENAME
    
    # Read URLs
    with open(file_path, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    
    total = len(urls)
    logging.info(f"Starting Phase 2 for {mode}: {total} URLs found.")
    
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    
    async with httpx.AsyncClient() as client:
        tasks = [check_url(client, url, semaphore) for url in urls]
        
        # We process them in chunks or all at once with semaphore
        # all at once with semaphore is fine for httpx
        results = await asyncio.gather(*tasks)
        
    new_count = 0
    rejected_count = 0
    error_count = 0
    
    with open(new_file, 'a', encoding='utf-8') as n_f, \
         open(rejected_file, 'a', encoding='utf-8') as r_f:
        
        for url, res in zip(urls, results):
            if res is None:
                error_count += 1
                logging.error(f"Failed to check: {url}")
                continue
            
            if res.get("exists") is False:
                n_f.write(f"{url}\n")
                new_count += 1
            else:
                exists_id = res.get("id", "N/A")
                scraped_at = res.get("scraped_at", "N/A")
                r_f.write(f"{url} | Reason: Already exists (ID: {exists_id}, Scraped At: {scraped_at})\n")
                rejected_count += 1
                
    logging.info(f"--- {mode} Summary ---")
    logging.info(f"Total processed: {total}")
    logging.info(f"Accepted (New): {new_count}")
    logging.info(f"Rejected (Exists): {rejected_count}")
    logging.info(f"Errors: {error_count}")
    logging.info(f"New URLs saved to {new_file}")

async def main():
    # Process Buy URLs
    await process_file(config.BUY_URLS_FILENAME, "buy")
    
    # Process Rent URLs
    await process_file(config.RENT_URLS_FILENAME, "rent")

if __name__ == "__main__":
    asyncio.run(main())
