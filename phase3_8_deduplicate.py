import csv
import os
import logging
from collections import defaultdict

# ============================================================
# CONFIGURATION
# ============================================================
OUTPUT_DIR = "output"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_DIR, "phase3_8_dedup.log"), mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

INPUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase3_7.csv")
INPUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase3_7.csv")

OUT_OBJEKTE  = os.path.join(OUTPUT_DIR, "Objekte_phase3_8.csv")
OUT_KONTAKTE = os.path.join(OUTPUT_DIR, "Kontakte_phase3_8.csv")

def main():
    logging.info("--- PHASE 3.8: CONTACT DEDUPLICATION ---")

    if not os.path.exists(INPUT_KONTAKTE):
        logging.error(f"Input file not found: {INPUT_KONTAKTE}")
        return

    # ── Identify Duplicates ──────────────────────────────────
    logging.info(f"Reading Kontakte from: {INPUT_KONTAKTE}")
    contacts_by_key = defaultdict(list)
    original_contacts = []
    
    with open(INPUT_KONTAKTE, "r", encoding="utf-8", newline='') as f:
        reader = csv.DictReader(f)
        fieldnames_k = list(reader.fieldnames)
        for row in reader:
            original_contacts.append(row)
            # Deduplication key: Name + Normalized Phone
            key = (
                row.get('first_name', '').strip().lower(),
                row.get('last_name', '').strip().lower(),
                row.get('normalized_phone', '').strip()
            )
            contacts_by_key[key].append(row)

    unique_contacts = []
    # Mapping: redundant_id -> master_id
    id_map = {}

    for key, group in contacts_by_key.items():
        # Keep the first one as master
        master = group[0]
        unique_contacts.append(master)
        
        master_id = master.get('external_id')
        for contact in group[1:]:
            red_id = contact.get('external_id')
            if red_id and master_id:
                id_map[red_id] = master_id

    logging.info(f"Analyzed {len(original_contacts)} contacts.")
    logging.info(f"  - Unique contacts: {len(unique_contacts)}")
    logging.info(f"  - Redundant IDs found: {len(id_map)}")

    # ── Update Objekte ───────────────────────────────────────
    logging.info(f"Reading Objekte from: {INPUT_OBJEKTE}")
    if not os.path.exists(INPUT_OBJEKTE):
        logging.warning(f"{INPUT_OBJEKTE} not found. Skipping object update.")
        final_objects = []
    else:
        final_objects = []
        updated_count = 0

        with open(INPUT_OBJEKTE, "r", encoding="utf-8", newline='') as f:
            reader = csv.DictReader(f)
            fieldnames_o = list(reader.fieldnames)
            for row in reader:
                contact_id = row.get('contact_external_id')
                if contact_id in id_map:
                    row['contact_external_id'] = id_map[contact_id]
                    updated_count += 1
                final_objects.append(row)

        logging.info(f"Analyzed {len(final_objects)} objects.")
        logging.info(f"  - Re-mapped to master contacts: {updated_count}")

    # ── Save Results ──────────────────────────────────────────
    with open(OUT_KONTAKTE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_k, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(unique_contacts)

    if final_objects:
        with open(OUT_OBJEKTE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames_o, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(final_objects)

    logging.info(f"=== DEDUPLICATION COMPLETE ===")
    logging.info(f"Final files written:")
    logging.info(f"  {OUT_KONTAKTE}")
    logging.info(f"  {OUT_OBJEKTE}")

if __name__ == "__main__":
    main()
