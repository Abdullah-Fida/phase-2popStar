import csv
import os

# --- CONFIGURATION ---
INPUT_FILE = r"output\Kontakte.csv"
OUTPUT_FILTERED = r"output\Kontakte_filtered.csv"
OUTPUT_REJECTED = r"output\Kontakte_rejected_agencies.csv"

# Keywords that indicate a contact is an agency or company rather than a person
AGENCY_KEYWORDS = [
    "GMBH", "SA", "SARL", "AG", "LLC", "CORP", "INC",
    "IMMOBILIEN", "IMMO", "IMMOBILIER", "IMMOBILIARE",
    "AGENCY", "AGENCE", "AGENZIA", "GROUP", "GROUPE", "GRUPPO",
    "ESTATE", "REALTY", "PROPERTIES", "PROPRIÉTÉS", "PROPRIETÀ",
    "INVEST", "INVESTMENT", "MANAGEMENT", "CONSULTING", "ADVISORY",
    "SOLUTIONS", "SERVICES", "PARTENAIRE", "PARTNERS",
    "ESTATES", "HOMES", "LIVING", "L'AGENCE",
    "DEVELOPMENT", "PROMOTION", "REGIE", "RÉGIE",
    "CONSEIL", "PROMOTIONS", "TEAM", "DEPARTMENT", "DÉPARTEMENT",
    "SERVICE", "STATION", "HOYOU", "NEHO", "VIMOVA", "PROPERTI"
]

def is_agency(first_name, last_name):
    full_name = f"{first_name} {last_name}".upper()
    for kw in AGENCY_KEYWORDS:
        # Check if keyword is in the name as a whole word or significant part
        if kw in full_name:
            return True, kw
    return False, None

def run_phase_3_5():
    print("--- PHASE 3.5: AGENCY/COMPANY FILTERING ---")
    
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        return

    filtered_count = 0
    rejected_count = 0

    with open(INPUT_FILE, mode='r', encoding='utf-8-sig', newline='') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        
        filtered_rows = []
        rejected_rows = []
        
        for row in reader:
            first = row.get('first_name', '')
            last = row.get('last_name', '')
            
            is_comm, matched_kw = is_agency(first, last)
            
            if is_comm:
                # Add matched keyword to row for debugging/review
                row['rejection_reason'] = f"Agency Keyword: {matched_kw}"
                rejected_rows.append(row)
                rejected_count += 1
            else:
                filtered_rows.append(row)
                filtered_count += 1

    # Write Filtered (Keep)
    with open(OUTPUT_FILTERED, mode='w', encoding='utf-8-sig', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)

    # Write Rejected
    if rejected_rows:
        # Add rejection_reason to header for the rejected file
        rejected_fieldnames = fieldnames + ['rejection_reason']
        with open(OUTPUT_REJECTED, mode='w', encoding='utf-8-sig', newline='') as rejfile:
            writer = csv.DictWriter(rejfile, fieldnames=rejected_fieldnames)
            writer.writeheader()
            writer.writerows(rejected_rows)

    print(f"Filtering Results:")
    print(f"  - Kept Individuals: {filtered_count}")
    print(f"  - Rejected Agencies: {rejected_count}")
    print(f"Accepted file: {OUTPUT_FILTERED}")
    print(f"Rejected file: {OUTPUT_REJECTED}")
    print("DONE!")

if __name__ == "__main__":
    run_phase_3_5()
