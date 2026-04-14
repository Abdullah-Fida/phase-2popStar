@echo off
echo Starting Phase 3 Scraper (ProperStar)...
echo Optimization: Using 8 workers for safe maximum speed.

:: Ensure dependencies are installed
pip install -r requirements.txt
playwright install chromium

:: Run the scraper
python phase3_scrape.py --workers 8 --limit 50

echo.
echo Scrape complete. Check output/ folder for results.
pause
