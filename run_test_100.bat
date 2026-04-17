@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   PROPERSTAR DATA PIPELINE - 100 URL TEST RUN
echo ============================================================

echo [*] Safely backing up previous output directory...
python -c "import os, datetime; ts = datetime.datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'); os.rename('output', 'output_backup_'+ts) if os.path.exists('output') else None"
mkdir output 2>nul

:: 1. Configuration Check
echo [*] Checking dependencies...
pip install -r requirements.txt >nul 2>&1
echo [*] Ensuring browser is ready...
python -m playwright install chromium >nul 2>&1

:: 2. Phase 1 - URL Discovery
echo.
echo [1/7] PHASE 1: Discovery (URL Collection)
:: Limit set to 50 per mode (50 buy + 50 rent = 100 urls roughly)
python phase1_scraper.py --limit 50

:: 3. Phase 2 - Availability Check
echo.
echo [2/7] PHASE 2: Availability Check
python phase2_check.py

:: 4. Phase 3 - Detailed Scraping
echo.
echo [3/7] PHASE 3: Detailed Scraper (4 Workers)
:: Limit set to exactly 100 properties
python phase3_scrape.py --workers 4 --limit 100

:: 5. Phase 3.7 - Agency Cleanup
echo.
echo [4/7] PHASE 3.7: Agency Filtering
python phase3_7_cleanup.py

:: 6. Phase 3.8 - Deduplication
echo.
echo [5/7] PHASE 3.8: Contact Deduplication
python phase3_8_deduplicate.py

:: 7. Phase 5 - API Advertiser Check
echo.
echo [6/7] PHASE 5: API Advertiser Check
python phase5_api_check.py

:: 8. Phase 6 - Categorization & Formatting
echo.
echo [7/7] PHASE 6: Categorization and Swiss Pricing
python phase6_categorize.py

echo.
echo ============================================================
echo   TEST PIPELINE COMPLETE - CHECK output/ FOR RESULTS
echo ============================================================
pause
