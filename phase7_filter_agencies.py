import csv
import os
import re

# ============================================================
# SETTINGS
# ============================================================
OUTPUT_DIR = "output"
INPUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase6.csv")
INPUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase6.csv")

OUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase7.csv")
OUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase7.csv")

# ============================================================
# AGENCY FILTER SETTINGS
# ============================================================

# Keywords that indicate a company name if found in first_name or last_name
AGENCY_KEYWORDS = [
    r"\bAG\b", r"\bGmbH\b", r"\bSA\b", r"\bS\.A\.?\b", r"\bSàrl\b", r"\bSarl\b", 
    r"\bSagl\b", r"\bGba\b", r"\bLtd\b", r"\bInc\b", r"\bS\.à\.r\.l\.?\b",
    r"Immobilien", r"Immobilier", r"Immobilière", r"Immobiliere", r"Immobiliare",
    r"Agency", r"Agence", r"Real Estate", r"Promotions", r"Promotion", r"Courtage", 
    r"Fiduciaire", r"Fiduciaria", r"Regie", r"Gestion", r"Solutions", r"Services", 
    r"Management", r"Consulting", r"Partner", r"Partners", r"Residence", r"Residences",
    r"Conseils", r"Immobiliario", r"Immobiliaria", r"Associates", r"Properties",
    r"Investissement", r"Investments", r"Development", r"Developments",
    r"Team", r"Staff", r"Service", r"Department", r"Département", r"Secrétariat",
    r"Administration", r"Vente", r"Location", r"Home", r"Homes", r"House", r"Houses",
    r"Immo", r"Immob", r"ImmoGérance", r"Build", r"Building", r"Estate",
]

# Patterns for URLs or other non-human names
NAME_BLOCK_PATTERNS = [
    r"\.ch\b", r"\.com\b", r"\.net\b", r"\.fr\b", r"\.it\b", r"\.li\b", # Domains
    r"^[\*\s\-]+$", # Pure symbols
    r"\d{3,}", # Long numbers in name
]

def is_agency(first_name, last_name):
    # Normalize
    name_text = f"{first_name} {last_name}".strip()
    if not name_text:
        return True # Remove empty names
        
    full_name_lower = name_text.lower()
    
    # Check against agency keywords
    for kw in AGENCY_KEYWORDS:
        # If it looks like a regex pattern (has \b or start/end anchors)
        if "\\" in kw or "^" in kw or "$" in kw:
            if re.search(kw, name_text, re.IGNORECASE):
                return True
        else:
            # Literal substring check for longer keywords
            if kw.lower() in full_name_lower:
                return True
            
    # Check against block patterns
    for pattern in NAME_BLOCK_PATTERNS:
        if re.search(pattern, full_name_lower, re.IGNORECASE):
            return True
            
    # Heuristic: If one field contains "de vente" or "service" or "secrétariat"
    if any(term in full_name_lower for term in ["de vente", "de location", "service des", "service de"]):
        return True

    return False

# ============================================================
# MAIN
# ============================================================
def main():
    print(f"Reading Kontakte from: {INPUT_KONTAKTE}")
    
    if not os.path.exists(INPUT_KONTAKTE):
        print(f"Error: {INPUT_KONTAKTE} not found.")
        return

    # ── Process Kontakte ─────────────────────────────────────
    valid_contacts = []
    removed_contacts_count = 0
    # IDs of contacts explicitly identified as AGENCIES
    agency_external_ids = set()

    with open(INPUT_KONTAKTE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        k_fields = list(reader.fieldnames)
        for row in reader:
            fn = row.get("first_name", "")
            ln = row.get("last_name", "")
            ext_id = row.get("external_id")
            
            if is_agency(fn, ln):
                removed_contacts_count += 1
                if ext_id:
                    agency_external_ids.add(ext_id)
            else:
                valid_contacts.append(row)

    print(f"Removed {removed_contacts_count} agency contacts.")
    print(f"Kept {len(valid_contacts)} person contacts.")

    # ── Process Objekte ──────────────────────────────────────
    print(f"\nReading Objekte from : {INPUT_OBJEKTE}")
    if not os.path.exists(INPUT_OBJEKTE):
        print(f"Error: {INPUT_OBJEKTE} not found.")
        return

    kept_objects = []
    removed_objects_count = 0

    with open(INPUT_OBJEKTE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Use the EXACT same fields as Phase 6 — no extra columns added
        o_fields = list(reader.fieldnames)

        for row in reader:
            contact_id = row.get("contact_external_id", "")

            # FILTER: Drop rows whose contact is a known agency
            if contact_id and contact_id in agency_external_ids:
                removed_objects_count += 1
            else:
                # Keep orphans (empty contact_id) and individual-linked rows
                kept_objects.append(row)

    print(f"Removed {removed_objects_count} objects linked to agencies.")
    print(f"Kept {len(kept_objects)} objects (individuals + orphans).")

    # ── Save Results ─────────────────────────────────────────
    with open(OUT_KONTAKTE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=k_fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(valid_contacts)

    with open(OUT_OBJEKTE, "w", newline="", encoding="utf-8-sig") as f:
        # Write using the exact same fieldnames as Phase 6 — no schema changes
        writer = csv.DictWriter(f, fieldnames=o_fields, quoting=csv.QUOTE_ALL, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept_objects)

    print(f"\n=== PHASE 7: AGENCY FILTERING COMPLETE ===")
    print(f"Output files written:")
    print(f"  {OUT_KONTAKTE}")
    print(f"  {OUT_OBJEKTE}")

if __name__ == "__main__":
    main()
