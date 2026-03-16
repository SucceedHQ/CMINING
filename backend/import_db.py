import json
import os
import sys
from datetime import datetime, timezone
from app import app, db, AccessKey

# Ensure tables exist
with app.app_context():
    db.create_all()

backup_file = r"c:\Users\USER\Documents\TOOLS\CMINING TOOL\access_keys_backup.json"

if not os.path.exists(backup_file):
    print(f"Error: {backup_file} not found!")
    sys.exit(1)

with open(backup_file, 'r') as f:
    try:
        data = json.load(f)
    except json.JSONDecodeError:
        print("Failed to decode JSON backup.")
        sys.exit(1)

with app.app_context():
    inserted = 0
    for key_data in data:
        # Check if already exists
        exists = AccessKey.query.filter_by(key_value=key_data.get('key_value')).first()
        if exists:
            print(f"Key {key_data.get('key_value')} already exists, skipping...")
            continue
            
        new_key = AccessKey(
            key_value=key_data.get('key_value'),
            owner_name=key_data.get('owner_name', 'Unknown User'),
            total_leads_processed=key_data.get('total_leads_processed', 0),
            total_successes=key_data.get('total_successes', 0),
            created_at=datetime.utcnow() # Note: use naive UTC for sqlite compatibility inside sqlalchemy
        )
        db.session.add(new_key)
        inserted += 1
        
    db.session.commit()
    print(f"Successfully imported {inserted} access keys to the new database.")
