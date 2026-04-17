import csv
import os
import re
import logging

# ============================================================
# SETTINGS
# ============================================================
OUTPUT_DIR = "output"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_DIR, "phase6_categorize.log"), mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Pick newest available phase input
INPUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase5.csv")  if os.path.exists(os.path.join(OUTPUT_DIR, "Objekte_phase5.csv"))  else os.path.join(OUTPUT_DIR, "Objekte_phase3_8.csv")
INPUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase5.csv") if os.path.exists(os.path.join(OUTPUT_DIR, "Kontakte_phase5.csv")) else os.path.join(OUTPUT_DIR, "Kontakte_phase3_8.csv")

OUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase6.csv")
OUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase6.csv")

logging.info(f"Reading Objekte from : {INPUT_OBJEKTE}")
logging.info(f"Reading Kontakte from: {INPUT_KONTAKTE}")

# ============================================================
# CATEGORY → KEYWORDS MAPPING
# Priority order: more specific categories first
# ============================================================
# Each entry: (rs_category_id, [keywords to match in title/description/url])
# Lower index = higher priority (matched first)

CATEGORY_RULES = [
    # ── Specific apartment sub-types first ──────────────────
    (4,  ["penthouse"]),
    (10, ["attika", "attica"]),
    (9,  ["half-basement", "basement flat", "sous-sol"]),
    (1,  ["roof storey", "attic", "dachgeschoss", "attique", "sous les toits", "top floor", "sunny attic"]),
    (2,  ["loft"]),
    (3,  ["maisonette"]),
    (5,  ["terraced flat", "terrassenw"]),
    (8,  ["raised ground floor", "hochparterre"]),
    (6,  ["ground floor apartment", "ground-floor", "erdgeschoss", "rez-de-chaussée", "rez de chaussee", "rez-de-jardin"]),

    # ── Specific house sub-types ─────────────────────────────
    (25, ["castle", "château", "chateau", "manor", "schloss", "burg"]),
    (24, ["villa"]),
    (21, ["bungalow"]),
    (22, ["farmhouse", "bauernhaus", "ferme", "farm house"]),
    (20, ["finca"]),
    (28, ["chalet", "holiday house", "holiday home", "ferienhaus", "vacation home", "maison de vacances"]),
    (23, ["semi-detached", "semidetached", "doppelhaushälfte", "doppelhaus"]),
    (27, ["twin single"]),
    (19, ["townhouse", "town-house", "stadthaus"]),
    (17, ["corner house", "end-of-terrace", "corner terraced"]),
    (16, ["end-terrace house", "terrace end"]),
    (15, ["mid-terrace", "reihenmittelhaus"]),
    (14, ["terrace house", "reihenhaus", "row house", "maison en rangée"]),
    (18, ["multi-family house", "mehrfamilienhaus", "apartment building", "mfh", "immeuble"]),
    (13, ["two-family house", "zweifamilienhaus", "zfh", "duplex house"]),
    (12, ["single-family house", "einfamilienhaus", "efh", "detached house", "maison individuelle", "single family"]),

    # ── Parking ──────────────────────────────────────────────
    (38, ["underground garage", "tiefgarage", "souterrain"]),
    (39, ["double garage"]),
    (35, ["carport"]),
    (36, ["duplex parking", "duplexgarage"]),
    (37, ["car park", "parkhaus"]),
    (33, ["garage"]),
    (34, ["parking", "parkplatz", "parking space", "outdoor parking"]),

    # ── Office / Commercial ───────────────────────────────────
    (40, ["office loft"]),
    (41, ["studio office", "studio space"]),
    (47, ["surgery", "praxis"]),
    (42, ["office", "büro", "bureau"]),

    # ── Industrial / Storage ──────────────────────────────────
    (75, ["workshop", "werkstatt", "atelier"]),
    (66, ["industrial hall", "industriehalle"]),
    (72, ["warehouse", "lagerhaus"]),
    (71, ["storage area", "lager"]),
    (64, ["hall"]),

    # ── Retail ───────────────────────────────────────────────
    (81, ["shop", "store", "boutique", "magasin"]),
    (77, ["shopping centre", "shopping center"]),

    # ── Hospitality ──────────────────────────────────────────
    (58, ["hotel"]),
    (62, ["restaurant"]),
    (56, ["guest house", "guesthouse"]),

    # ── Investment ───────────────────────────────────────────
    (97, ["invest", "investment property", "yield"]),

    # ── Generic apartment / flat (broad catch-all for residential) ──
    (7,  ["apartment", "wohnung", "appartement", "flat", "room", "studio", "zimmer wohnung",
          "room apartment", "1/2 room", "2/2 room", "3.5", "4.5", "5.5", "2.5", "1.5",
          "furnished apartment", "rental apartment", "garden apartment", "balcon"]),

    # ── Generic house (final house fallback) ─────────────────
    (12, ["house", "haus", "maison", "home", "property"]),
]

def normalize_phone(phone_text):
    if not phone_text:
        return ""
    phone_text = re.sub(r'\(0\)', '', str(phone_text).strip())
    cleaned = re.sub(r'[^\d\+]', '', phone_text)
    if not cleaned:
        return ""
    if cleaned.startswith('-'):
        cleaned = cleaned[1:]
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
    # Fix +410... → +41...
    if cleaned.startswith('+410') and len(cleaned) > 12:
        cleaned = '+41' + cleaned[4:]
    return cleaned

def classify(title: str, url: str, description: str = "") -> int:
    """Return the best matching rs_category_id."""
    text = f"{title} {url} {description[:500]}".lower()
    # Normalize separators
    text = re.sub(r'[-/]', ' ', text)

    for cat_id, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw.lower() in text:
                return cat_id

    # Absolute fallback: standard apartment
    return 7

# ============================================================
# MAIN
# ============================================================
def main():
    # ── Load and categorise Objekte ──────────────────────────
    with open(INPUT_OBJEKTE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows   = list(reader)

    counts = {}
    for row in rows:
        url = row.get("detail_url", "")

        # Category classification
        cat_id = classify(
            row.get("title", ""),
            url,
            row.get("description", "")
        )
        row["rs_category_id"] = str(cat_id)
        counts[cat_id] = counts.get(cat_id, 0) + 1

        # Price formatting (CHF 1'234'567.-)
        p_val = row.get("price_value", "").strip()
        if p_val:
            try:
                # Standardize to int
                val_int = int(float(p_val))
                # Swiss formatting: single quote as thousands separator
                formatted = f"{val_int:,}".replace(",", "'")
                row["price"] = f"CHF {formatted}.-"
            except (ValueError, TypeError):
                pass

        # Force correct IDs for the final product
        row["portal_id"] = "13"
        row["vendor_id"] = "7"

    with open(OUT_OBJEKTE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    # ── Copy and format Kontakte ──────────────────────────────
    with open(INPUT_KONTAKTE, "r", encoding="utf-8") as f:
        reader      = csv.DictReader(f)
        k_fields    = list(reader.fieldnames)
        k_rows      = list(reader)

    # Apply fixes: preserve raw phone and normalize for np
    for k_row in k_rows:
        p = k_row.get('phone', '')
        np = k_row.get('normalized_phone', '')
        
        # Unwrap if already wrapped by previous phase
        raw_p = p.replace('="', '').replace('"', '') if p.startswith('="') else p
        raw_np = np.replace('="', '').replace('"', '') if np.startswith('="') else np

        # Normalize only for np (use raw_p if np is empty)
        base_for_norm = raw_np if raw_np else raw_p
        norm_val = normalize_phone(base_for_norm)
        
        # Save back in plain CSV format without Excel formula wrapper
        k_row['phone'] = raw_p if raw_p else ""
        k_row['normalized_phone'] = norm_val if norm_val else ""
        
        # Force correct IDs for the final product
        k_row['portal_id'] = "13"
        k_row['vendor_id'] = "7"

    with open(OUT_KONTAKTE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=k_fields, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(k_rows)

    # ── Report ────────────────────────────────────────────────
    logging.info("=== PHASE 6: CATEGORY MAPPING COMPLETE ===")
    logging.info(f"Total Objekte processed : {len(rows)}")
    logging.info(f"Total Kontakte copied   : {len(k_rows)}")
    logging.info("Category distribution:")
    
    # Category label lookup
    labels = {
        1:"Top floor", 2:"Loft", 3:"Maisonette", 4:"Penthouse", 5:"Terraced flat",
        6:"Ground floor", 7:"Standard apartment", 8:"Raised ground floor", 9:"Basement",
        10:"Attic apartment", 11:"Other", 12:"Single-family house", 13:"Two-family house",
        14:"Terrace house", 15:"Mid-terrace house", 16:"End-terrace house",
        17:"Corner terraced house", 18:"Multi-family house", 19:"Townhouse", 20:"Finca",
        21:"Bungalow", 22:"Farmhouse", 23:"Semi-detached house", 24:"Villa",
        25:"Castle / Manor house", 26:"Special real estate", 27:"Twin single-family house",
        28:"Holiday house", 29:"Apartment (short-term)", 33:"Garage", 34:"Street parking",
        35:"Carport", 36:"Duplex", 37:"Car park", 38:"Underground garage", 39:"Double garage",
        40:"Office loft", 41:"Studio", 42:"Office", 47:"Surgery", 56:"Guest house",
        58:"Hotel", 62:"Restaurant", 64:"Hall", 66:"Industrial hall", 71:"Storage area",
        72:"Warehouse", 75:"Workshop", 77:"Shopping centre", 81:"Shop", 97:"Freehold flat (invest)"
    }
    for cat_id, count in sorted(counts.items(), key=lambda x: -x[1]):
        label = labels.get(cat_id, f"Category {cat_id}")
        logging.info(f"  [{cat_id:>3}] {label:<35} : {count}")

    logging.info("Output files written:")
    logging.info(f"  {OUT_OBJEKTE}")
    logging.info(f"  {OUT_KONTAKTE}")

if __name__ == "__main__":
    main()
