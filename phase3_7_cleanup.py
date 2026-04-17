import csv
import os
import re
import logging
import config

# ============================================================
# CONFIGURATION
# ============================================================
OUTPUT_DIR = "output"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_DIR, "phase3_7_cleanup.log"), mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

INPUT_OBJEKTE  = config.OBJEKTE_FILENAME
INPUT_KONTAKTE = config.KONTAKTE_FILENAME

OUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase3_7.csv")
OUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase3_7.csv")
OUT_REJECTED = os.path.join(OUTPUT_DIR, "rejected_agencies_phase3_7.csv")

# ============================================================
# AGENCY FILTER SETTINGS (Merged Phase 3.5 & 7)
# ============================================================

# Keywords that indicate a company name if found in first_name or last_name
# Uses both regex boundaries (\b) and literal strings
AGENCY_KEYWORDS = [
    # German/French/English Company Forms
    r"\bAG\b", r"\bGmbH\b", r"\bSA\b", r"\bS\.A\.?\b", r"\bSàrl\b", r"\bSarl\b", 
    r"\bSagl\b", r"\bGba\b", r"\bLtd\b", r"\bInc\b", r"\bS\.à\.r\.l\.?\b", r"\bLLC\b",
    r"\bCORP\b", r"\bINC\b",
    
    # Real Estate Terms (Industry)
    "Immobilien", "Immobilier", "Immobilière", "Immobiliere", "Immobiliare",
    "Agency", "Agence", "Agenzia", "Real Estate", "Promotions", "Promotion", "Courtage", 
    "Fiduciaire", "Fiduciaria", "Regie", "Régie", "Gestion", "Solutions", "Services", 
    "Management", "Consulting", "Partner", "Partners", "Residence", "Residences",
    "Conseils", "Immobiliario", "Immobiliaria", "Associates", "Properties",
    "Investissement", "Investments", "Development", "Developments",
    "Estate", "Realty", "Propriétés", "Proprietà", "Invest", "Advisory", "Partenaire",
    "Estates", "Homes", "Living", "L'Agence", "Conseil",
    
    # Internal Departments / Generic terms
    "Team", "Staff", "Service", "Department", "Département", "Secrétariat",
    "Administration", "Vente", "Location", "Home", "House", "Houses",
    "Immo", "Immob", "ImmoGérance", "Build", "Building", "Station",
    
    # Specific Agency Names detected in ProperStar
    "HOYOU", "NEHO", "VIMOVA", "PROPERTI"
]

# Patterns for URLs, Domains, or other non-human names
NAME_BLOCK_PATTERNS = [
    r"\.ch\b", r"\.com\b", r"\.net\b", r"\.fr\b", r"\.it\b", r"\.li\b", # Domains
    r"^[\*\s\-]+$", # Pure symbols
    r"\d{3,}", # Long numbers in name
]

def is_agency(first_name, last_name):
    """
    Checks if the given name likely belongs to an agency/company.
    Returns (True, reason) if agency, (False, None) if individual.
    """
    fn = str(first_name or "").strip()
    ln = str(last_name or "").strip()
    full_name = f"{fn} {ln}".strip()
    
    if not full_name:
        return True, "Empty Name"
        
    full_name_lower = full_name.lower()
    
    # 1. Check against agency keywords
    for kw in AGENCY_KEYWORDS:
        # If it looks like a regex pattern (has \b)
        if "\\" in kw:
            if re.search(kw, full_name, re.IGNORECASE):
                return True, f"Regex Match: {kw}"
        else:
            # Literal substring check (case-insensitive)
            if kw.lower() in full_name_lower:
                return True, f"Keyword Match: {kw}"
            
    # 2. Check against block patterns
    for pattern in NAME_BLOCK_PATTERNS:
        if re.search(pattern, full_name, re.IGNORECASE):
            return True, f"Block Pattern Match: {pattern}"
            
    # 3. Heuristic: Specific department phrases
    phrases = ["de vente", "de location", "service des", "service de", "département de"]
    for phrase in phrases:
        if phrase in full_name_lower:
            return True, f"Department Phrase: {phrase}"

    return False, None

# ============================================================
# EXECUTION
# ============================================================
def main():
    logging.info("--- UNIFIED AGENCY CLEANUP (MIXED PHASE 3.5 & 7) ---")
    
    if not os.path.exists(INPUT_KONTAKTE):
        logging.error(f"Input file not found: {INPUT_KONTAKTE}")
        return

    # ── Process Kontakte ─────────────────────────────────────
    logging.info(f"Reading Kontakte from: {INPUT_KONTAKTE}")
    valid_contacts = []
    rejected_contacts = []
    agency_ids = set()

    with open(INPUT_KONTAKTE, "r", encoding="utf-8", newline='') as f:
        reader = csv.DictReader(f)
        k_fields = list(reader.fieldnames)
        
        for row in reader:
            fn = row.get("first_name", "")
            ln = row.get("last_name", "")
            ext_id = row.get("external_id")
            
            is_comm, reason = is_agency(fn, ln)
            
            if is_comm:
                row['rejection_reason'] = reason
                rejected_contacts.append(row)
                if ext_id:
                    agency_ids.add(ext_id)
            else:
                valid_contacts.append(row)

    logging.info(f"Analyzed {len(valid_contacts) + len(rejected_contacts)} contacts.")
    logging.info(f"  - Removed: {len(rejected_contacts)} (Agencies)")
    logging.info(f"  - Kept:    {len(valid_contacts)} (Individuals)")

    # ── Process Objekte ──────────────────────────────────────
    logging.info(f"Reading Objekte from : {INPUT_OBJEKTE}")
    if not os.path.exists(INPUT_OBJEKTE):
        logging.warning(f"{INPUT_OBJEKTE} not found. Skipping object filtering.")
        kept_objects = []
    else:
        kept_objects = []
        removed_objects_count = 0

        with open(INPUT_OBJEKTE, "r", encoding="utf-8", newline='') as f:
            reader = csv.DictReader(f)
            o_fields = list(reader.fieldnames)

            for row in reader:
                contact_id = row.get("contact_external_id", "")
                if contact_id and contact_id in agency_ids:
                    removed_objects_count += 1
                else:
                    kept_objects.append(row)

        logging.info(f"Analyzed {len(kept_objects) + removed_objects_count} objects.")
        logging.info(f"  - Removed: {removed_objects_count} (Linked to agencies)")
        logging.info(f"  - Kept:    {len(kept_objects)} (Individuals)")

    # ── Write Results ─────────────────────────────────────────
    # 1. Cleaned Kontakte
    with open(OUT_KONTAKTE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=k_fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(valid_contacts)

    # 2. Rejected Kontakte (with reason)
    if rejected_contacts:
        rej_fields = k_fields + ['rejection_reason']
        with open(OUT_REJECTED, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rej_fields, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rejected_contacts)

    # 3. Cleaned Objekte
    if kept_objects:
        with open(OUT_OBJEKTE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=o_fields, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(kept_objects)

    logging.info(f"=== CLEANUP COMPLETE ===")
    logging.info(f"Saved Kept:     {OUT_KONTAKTE} and {OUT_OBJEKTE}")
    logging.info(f"Saved Rejected: {OUT_REJECTED}")

if __name__ == "__main__":
    main()
