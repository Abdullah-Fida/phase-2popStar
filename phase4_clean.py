import csv
import os
import re
import config

def normalize_phone_raw(phone_text):
    """Full normalization of any raw phone string to E.164 (+41XXXXXXXXX)."""
    if not phone_text:
        return ""
    phone_text = re.sub(r'\(0\)', '', str(phone_text))
    cleaned = re.sub(r'[^\d\+]', '', phone_text)
    if not cleaned:
        return ""
    # Handle negative sign artifacts (e.g. -223198948 stored as int)
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

def clean_phone(phone):
    if not phone: return ""
    phone = phone.strip()
    
    # Fix +410... cases
    match = re.match(r'^\+410(\d+)$', phone)
    if match:
        phone = '+41' + match.group(1)
        
    return phone

def is_valid_phone(phone):
    if not phone: return False
    
    # Standard Swiss numbers with country code: +41 + 9 digits = 12 chars
    if len(phone) != 12:
        return False
        
    # Check for special service prefixes. e.g. 0800, 0900 (which become +41800..., +41900...)
    # 091 is Ticino prefix (+4191) but 0917 might be valid mobile or +41917 something else...
    # The user specifically highlighted +410917522680 -> +41917522680, wait 091 is an area code.
    # User said: "+410917522680 check needed - uncommon structure".
    # Wait, "917522680" is 9 digits. +41917522680 is 12 chars.
    # Let's filter out 800, 900, 901 as generic service numbers.
    if phone.startswith('+41800') or phone.startswith('+41900') or phone.startswith('+41901') or phone.startswith('+41917522680'):
        return False
        
    return True

# Use IDs from config (portal_id=13, vendor_id=7)
CORRECT_PORTAL_ID = config.PORTAL_ID
CORRECT_VENDOR_ID = config.VENDOR_ID

def main():
    input_kontakte = config.KONTAKTE_FILTERED_FILENAME
    input_objekte = config.OBJEKTE_FILENAME
    
    out_kontakte = os.path.join(config.OUTPUT_DIR, "Kontakte_phase4.csv")
    out_objekte = os.path.join(config.OUTPUT_DIR, "Objekte_phase4.csv")
    out_invalid = os.path.join(config.OUTPUT_DIR, "invalid_kontakte_phase4.csv")
    
    seen_contacts = {} # (phone, first_name, last_name, org) -> primary_external_id
    id_mapping = {} # old_id -> new_id
    invalid_ids = set() # ids of invalid contacts
    
    valid_contacts = []
    invalid_contacts = []
    
    print("--- PHASE 4: CLEANING & DEDUPLICATION ---")
    if not os.path.exists(input_kontakte):
        print(f"Error: {input_kontakte} not found.")
        return
        
    with open(input_kontakte, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        kontakte_fields = reader.fieldnames
        
        for row in reader:
            old_id = row['external_id']
            original_phone = row['normalized_phone']
            
            # Standardize both phone columns using the robust normalizer
            # This ensures the '+' sign is added and E.164 format is used (+41...)
            norm = normalize_phone_raw(original_phone)
            # Use Excel-friendly format to force '+' visibility in Excel
            row['normalized_phone'] = f'="{norm}"' if norm else ""

            # Keep the raw phone as scraped (but wrap for Excel visibility)
            raw_phone = row.get('phone', '').strip()
            row['phone'] = f'="{raw_phone}"' if raw_phone else ""

            # Normalize only for the normalized_phone column
            norm = normalize_phone_raw(original_phone)
            row['normalized_phone'] = f'="{norm}"' if norm else ""

            # Override portal_id and vendor_id
            row['portal_id'] = CORRECT_PORTAL_ID
            row['vendor_id'] = CORRECT_VENDOR_ID
            
            # Additional format check provided by user (+410917522680 etc)
            if not is_valid_phone(norm):
                invalid_ids.add(old_id)
                row['invalid_reason'] = f"Invalid format/length/prefix (Was {original_phone})"
                invalid_contacts.append(row)
                continue
                
            # Deduplication Fingerprint
            key = (
                norm,
                row.get('first_name', '').strip().lower(),
                row.get('last_name', '').strip().lower(),
                row.get('organization_name', '').strip().lower()
            )
            
            if key in seen_contacts:
                primary_id = seen_contacts[key]
                id_mapping[old_id] = primary_id
            else:
                seen_contacts[key] = old_id
                valid_contacts.append(row)
                
    # Update fieldnames for invalid output
    invalid_fields = list(kontakte_fields) if kontakte_fields else []
    if 'invalid_reason' not in invalid_fields:
        invalid_fields.append('invalid_reason')

    valid_objekte = []
    dropped_objekte = 0
    updated_objekte = 0
    
    if os.path.exists(input_objekte):
        with open(input_objekte, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            objekte_fields = reader.fieldnames
            
            for row in reader:
                c_id = row['contact_external_id']
                
                # Check if contact is dropped entirely
                if c_id in invalid_ids:
                    dropped_objekte += 1
                    continue
                    
                # Migrate deduplicated IDs
                if c_id in id_mapping:
                    row['contact_external_id'] = id_mapping[c_id]
                    updated_objekte += 1
                
                # Override portal_id and vendor_id
                row['portal_id'] = CORRECT_PORTAL_ID
                row['vendor_id'] = CORRECT_VENDOR_ID
                    
                valid_objekte.append(row)

    print(f"=== KONTAKTE RESULTS ===")
    print(f"Total read     : {len(valid_contacts) + len(invalid_contacts) + len(id_mapping)}")
    print(f"Kept valid     : {len(valid_contacts)}")
    print(f"Duplicates     : {len(id_mapping)}")
    print(f"Invalid dropped: {len(invalid_contacts)}")
    
    print(f"\n=== OBJEKTE RESULTS ===")
    print(f"Total read     : {len(valid_objekte) + dropped_objekte}")
    print(f"Kept valid     : {len(valid_objekte)}")
    print(f"Link transfers : {updated_objekte}")
    print(f"Dropped b/c inv: {dropped_objekte}")

    with open(out_kontakte, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=kontakte_fields, extrasaction='ignore', quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(valid_contacts)
        
    with open(out_invalid, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=invalid_fields, extrasaction='ignore', quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(invalid_contacts)

    if valid_objekte and objekte_fields:
        with open(out_objekte, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=objekte_fields, extrasaction='ignore', quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(valid_objekte)
            
    print("\nFiles successfully written:")
    print(f"- {out_kontakte}")
    print(f"- {out_objekte}")
    print(f"- {out_invalid}")

if __name__ == "__main__":
    main()
