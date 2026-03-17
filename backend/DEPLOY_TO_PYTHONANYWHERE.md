# CMining Backend — PythonAnywhere Deployment Guide

## STEP 1: Upload files to PythonAnywhere

In PythonAnywhere, open a **Bash console** and run:
```bash
mkdir -p ~/CMining-Monorepo/backend
cd ~/CMining-Monorepo/backend
```

Then upload these files from your local `backend/` folder using the **Files** tab:
- `app.py`
- `requirements.txt`
- `wsgi.py`
- `.env`  ← your Upstash Redis URL + ADMIN_SECRET_KEY

## STEP 2: Install dependencies

In the Bash console:
```bash
cd ~/CMining-Monorepo/backend
pip3 install --user -r requirements.txt
```

## STEP 3: Configure the Web App

1. Go to **Web** tab → click **Add a new web app**
2. Choose **Manual configuration** → Python 3.10
3. Set **Source code**: `/home/SucceedHQ/CMining-Monorepo/backend`
4. Set **WSGI configuration file** → click the link → **replace all content** with:

```python
import sys, os
project_home = '/home/SucceedHQ/CMining-Monorepo/backend'
if project_home not in sys.path:
    sys.path.insert(0, project_home)
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))
from app import app as application
```

5. Click **Save** and then **Reload** the web app

## STEP 4: Verify it works

Open in your browser:
```
https://succeedhq.pythonanywhere.com/api/version/check
```

You should see:
```json
{"is_obsolete": false, "latest_version": "1.0.0"}
```

## STEP 5: Your .env file (minimum required)

Create `/home/SucceedHQ/CMining-Monorepo/backend/.env` with:
```
REDIS_URL=rediss://:yourpassword@liberal-cheetah-71....upstash.io:6379
ADMIN_SECRET_KEY=your_admin_password_here
DATABASE_URL=sqlite:////home/SucceedHQ/CMining-Monorepo/backend/local.db
```

> NOTE: PythonAnywhere free tier doesn't allow outbound Redis connections.
> Use `USE_REDIS=false` in your .env to fall back to SQLite only.

## STEP 6: Initialize the database

In PythonAnywhere Bash console:
```bash
cd ~/CMining-Monorepo/backend
python3 -c "from app import app, db; app.app_context().push(); db.create_all(); print('DB ready')"
python3 fix_keys.py
```

---

Once done, the Electron app will connect automatically to:
`https://succeedhq.pythonanywhere.com`
