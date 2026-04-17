@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   PROPERSTAR DATA PIPELINE - MASTER RUN
echo ============================================================

:: 1. Configuration Check
echo [*] Safely backing up previous output directory...
python -c "import os, datetime; ts = datetime.datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'); os.rename('output', 'output_backup_'+ts) if os.path.exists('output') else None"
mkdir output 2>nul

echo [*] Checking dependencies...
pip install -r requirements.txt >nul 2>&1
echo [*] Ensuring browser is ready...
python -m playwright install chromium >nul 2>&1

:: 2. Phase 1 - URL Discovery
echo.
echo [1/7] PHASE 1: Discovery (URL Collection)
python phase1_scraper.py

:: 3. Phase 2 - Availability Check
echo.
echo [2/7] PHASE 2: Availability Check
python phase2_check.py

:: 4. Phase 3 - Detailed Scraping
echo.
echo [3/7] PHASE 3: Detailed Scraper (8 Workers)
:: Defaulting to 8 workers and target limit as per latest instructions
python phase3_scrape.py --workers 8 --limit 26000

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
echo   PIPELINE COMPLETE - CHECK output/ FOR RESULTS
echo ============================================================
pause
