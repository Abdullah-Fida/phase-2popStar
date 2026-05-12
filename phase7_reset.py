import os
import csv
import logging
import config
import supabase_helper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_max_ids_from_csvs():
    max_contact_id = getattr(config, 'START_ID', 300000)
    max_listing_id = getattr(config, 'START_ID', 300000)

    # 1. Kontakte
    if os.path.exists(config.KONTAKTE_FILENAME):
        try:
            with open(config.KONTAKTE_FILENAME, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ext_id = int(row.get('external_id', 0))
                        if ext_id > max_contact_id:
                            max_contact_id = ext_id
                    except ValueError:
                        pass
        except Exception as e:
            logging.error(f"Failed to read {config.KONTAKTE_FILENAME}: {e}")

    # 2. Objekte
    if os.path.exists(config.OBJEKTE_FILENAME):
        try:
            with open(config.OBJEKTE_FILENAME, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ext_id = int(row.get('advertisement_id', 0))
                        if ext_id > max_listing_id:
                            max_listing_id = ext_id
                    except ValueError:
                        pass
        except Exception as e:
            logging.error(f"Failed to read {config.OBJEKTE_FILENAME}: {e}")

    return max_listing_id, max_contact_id

def main():
    logging.info("=== Phase 7: State Persistence & Cleanup ===")
    
    # 1. Determine max IDs from the finalized CSVs
    logging.info("Calculating highest IDs from local CSV files...")
    max_listing, max_contact = get_max_ids_from_csvs()
    logging.info(f"Calculated Max Listing ID: {max_listing}")
    logging.info(f"Calculated Max Contact ID: {max_contact}")

    # 2. Save this state to Supabase
    logging.info("Saving highest IDs to Supabase scraper_state table...")
    supabase_helper.save_scraper_state(max_listing, max_contact)

    # 3. Clear all tracking tables in Supabase so the next run starts fresh
    logging.info("Clearing Supabase tracking tables (scraped_listings, scraped_contacts, phase2_urls)...")
    supabase_helper.clear_all_supabase_data()
    
    logging.info("=== Phase 7 COMPLETE ===")

if __name__ == "__main__":
    main()
