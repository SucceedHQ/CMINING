import os
from app import app, db, AccessKey
from datetime import datetime, timezone

with app.app_context():
    # Revoke old key
    old_ak = AccessKey.query.filter_by(key_value="JUDD-81EA6F6DB443").first()
    if old_ak:
        old_ak.is_banned = True
        old_ak.is_active = False

    ak = AccessKey.query.filter_by(key_value="JUDD-81EA6F6D9010").first()
    if not ak:
        ak = AccessKey(
            key_value="JUDD-81EA6F6D9010", 
            owner_name="Judd", 
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(ak)
        db.session.commit()
        print("Successfully revoked old key and added new Access Key: JUDD-81EA6F6D9010")
    else:
        print("Key JUDD-81EA6F6D9010 already exists!")
