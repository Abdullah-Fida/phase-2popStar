import os

# ============================================================
# PORTAL SETTINGS
# ============================================================
PORTAL_NAME = "icasa.ch"
PORTAL_ID = "13"
VENDOR_ID = "7"

# Set to True to bypass agency filter for demo/testing purposes
START_ID = 300000
# Enabled temporarily for demo run
DEMO_MODE = False

# ID Persistence (shared across all scripts)
ID_PERSISTENCE_FILE = "last_id.txt"
ID_RANGE_START = 300000
ID_RANGE_END = 400000

BASE_URL = "https://www.icasa.ch"

# Listing pages
BUY_URL = f"{BASE_URL}/kaufangebote"
RENT_URL = f"{BASE_URL}/mietangebote"

# Pagination
# Production mode: scrape all pages
MAX_PAGES = 5000

# ============================================================
# REQUEST SETTINGS
# ============================================================
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'de-CH,de;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Connection': 'keep-alive',
}

REQUEST_TIMEOUT = 20  # seconds
# Reduced delays for demo/testing (speed up runs)
DELAY_BETWEEN_REQUESTS = 0.1  # seconds
DELAY_BETWEEN_PAGES = 0.1  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# ============================================================
# FILTERING RULES
# ============================================================

# Minimum monthly rent in CHF to include rental listings
MIN_RENT_CHF = 3000

# Keywords that indicate a listing is from an AGENCY (not private person)
# If the advertiser name contains ANY of these -> SKIP the listing
AGENCY_KEYWORDS = [
    # German company forms
    'gmbh', 'ag', 'sa', 'sarl', 's.a.', 's.à r.l.', 'sàrl',
    'gesellschaft', 'holding', 'treuhand', 'verwaltung',
    # Real estate industry terms
    'immobilien', 'immobilier', 'immobiliare', 'real estate',
    'makler', 'broker', 'courtier', 'agentur', 'agency', 'agence',
    'vermittlung', 'beratung', 'consulting',
    'treuhand', 'verwaltung', 'management',
    'immo', 'homes', 'wincasa', 'dom', 'invest', 'properties', 'realestate', 'bau', 'architektur',
    # Company/branding indicators  
    'group', 'gruppe', 'partner', 'associates',
    'corp', 'inc', 'ltd', 'limited',
    # Swiss real estate specific
    'casaone', 'casasoft', 'casatour',
    'neubau', 'projekt',
    'büro', 'office', 'bureau',
    'bauherr', 'promoteur', 'promotore',
    'régie', 'regieimmobilien',
]

# Keywords that indicate a PRIVATE listing
PRIVATE_KEYWORDS = [
    'privat', 'private', 'particulier', 'privato',
    'eigentümer', 'propriétaire', 'proprietario',
    'owner', 'besitzer',
]

# ============================================================
# OUTPUT SETTINGS
# ============================================================
OUTPUT_DIR = "output"
OBJEKTE_FILENAME = os.path.join(OUTPUT_DIR, "Objekte_phase3.csv")
KONTAKTE_FILENAME = os.path.join(OUTPUT_DIR, "Kontakte_phase3.csv")
KONTAKTE_FILTERED_FILENAME = os.path.join(OUTPUT_DIR, "Kontakte_phase3_filtered.csv")
LOG_FILENAME = os.path.join(OUTPUT_DIR, "scraper.log")

# Specific Phase Files
BUY_URLS_FILENAME = os.path.join(OUTPUT_DIR, "buy_urls_phase1.txt")
RENT_URLS_FILENAME = os.path.join(OUTPUT_DIR, "rent_urls_phase1.txt")
PHASE2_TESTED_FILENAME = os.path.join(OUTPUT_DIR, "urls_tested_phase2.txt")
PHASE2_REJECTED_FILENAME = os.path.join(OUTPUT_DIR, "urls_rejected_phase2.txt")
PHASE2_LOG_FILENAME = os.path.join(OUTPUT_DIR, "phase2_check.log")
PHASE1_SCRAPER_LOG = os.path.join(OUTPUT_DIR, "phase1_scraper.log")
PHASE3_LOG_FILENAME = os.path.join(OUTPUT_DIR, "phase3_scrape.log")
PHASE3_REJECTED_FILENAME = os.path.join(OUTPUT_DIR, "rejected_phase3.csv")
LAST_IDS_FILENAME = os.path.join(OUTPUT_DIR, "last_ids.json")

# CSV encoding
CSV_ENCODING = "utf-8"  # Standard UTF-8 without BOM as requested by client
CSV_DELIMITER = ","

# ============================================================
# OBJEKTE.CSV COLUMNS (Property Listings)
# ============================================================
OBJEKTE_COLUMNS = [
    'contact_external_id',
    'portal_id',
    'vendor_id',
    'type_id',
    'detail_url',
    'title',
    'description',
    'street',
    'house_number',
    'zip_code',
    'city',
    'latitude',
    'longitude',
    'price',
    'living_space_area',
    'land_area',
    'rs_category_id',
    'price_value',
    'advertiser_id',
    'advertisement_id',
]

# ============================================================
# KONTAKTE.CSV COLUMNS (Contacts)
# ============================================================
KONTAKTE_COLUMNS = [
    'external_id',
    'first_name',
    'last_name',
    'organization_name',
    'email',
    'phone',
    'street',
    'house_number',
    'zip_code',
    'city',
    'normalized_phone',
    'portal_id',
    'vendor_id',
]
