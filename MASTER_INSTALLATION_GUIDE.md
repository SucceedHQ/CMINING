# CMining Monorepo: Master Setup & Requirements

After 12 hours of development, the system is fully production-ready. This guide ensures anyone can set up the **Owner/Admin** or **Distributed Worker** environments on any new laptop.

---

## 💻 1. Minimum System Requirements

### For Owners (Backend + Admin Dashboard)
- **OS**: Windows 10/11, macOS, or Linux.
- **Node.js**: v18.0.0 or higher.
- **Python**: v3.9 or higher (with `venv`).
- **RAM**: 4GB Minimum.
- **Storage**: 500MB (excluding project records).
- **Network**: Stable internet for Supabase/Redis sync.

### For Workers (Desktop Miner App)
- **OS**: Windows 10/11 (Portable `.exe` included).
- **RAM**: 4GB Minimum (8GB recommended for multiple browser threads).
- **Browser**: Playwright will install its own Chromium instance.
- **Network**: Must be able to reach your Flask URL (locally or cloud).

---

## 🛠️ 2. Owner Setup (New Laptop)

If you are moving the "Brain" of the operation to a new computer:

1. **Install Dependencies**:
   - Install [Node.js](https://nodejs.org/)
   - Install [Python](https://www.python.org/downloads/)
2. **Download Repository**: Clone or unzip the `CMining-Monorepo` folder.
3. **Setup Backend**:
   - Open terminal in `backend/`
   - Run: `python -m venv venv`
   - Run: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (Mac)
   - Run: `pip install -r requirements.txt`
4. **Setup Admin UI**:
   - Open terminal in `admin-dashboard/`
   - Run: `npm install`
5. **Launch Everything**:
   - Use the `CONTROL_CENTER.bat` file in the root folder.
   - Select **[1] START BACKEND** and **[2] START ADMIN**.

---

## ⛏️ 3. Worker Setup (New Laptop)

For the people helping you mine leads:

1. **Send the Files**: 
   - Zip the `electron-app/dist/cmining-worker 1.0.0.exe` and send it to them.
   - **OR** send them the `electron-app` folder if they want to run from source.
2. **If running from Source**:
   - Install [Node.js](https://nodejs.org/)
   - Open terminal in `electron-app/`
   - Run: `npm install`
   - Use `START_WORKER_APP.bat` to launch.
3. **If running the .EXE**:
   - Simply double-click it. 
   - Enter your Access Key (e.g., `JUDD-81EA6F6D9010`).
   - Click **Connect Wallet**.

---

## 🆘 4. Troubleshooting common errors

### "Connection Error: Cannot reach server"
- **Cause**: The app is trying to reach a URL that isn't running.
- **Fix**: Open `START_BACKEND.bat` first. Ensure `https://succeedhq.pythonanywhere.com/api/version/check` works in a browser.

### "AggregateError"
- **Cause**: (FIXED) The app was using the wrong network protocol (HTTP instead of HTTPS).
- **Fix**: I have updated the code to automatically switch between HTTP and HTTPS.

### "AUTH ERROR"
- **Cause**: The Access Key you typed is either wrong, revoked, or not in the database.
- **Fix**: Check your **Admin Dashboard** stats to see if the key is listed as active.

---

## 🛡️ 5. FAQ
**Q: Is the Flask variable named app?**  
**A:** Yes. Inside `app.py`, the variable is `app = Flask(__name__)`. For PythonAnywhere's `wsgi.py`, it is imported as `application` (Standard requirement).

**Q: Can I run this without the internet?**  
**A:** No. The system heartbeat requires a connection to the central database to log worker progress and verify keys.
