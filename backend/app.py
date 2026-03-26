import os
import json
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import redis
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///local.db')

# Fix for Windows local testing if .env has a PythonAnywhere path
if os.name == 'nt' and app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:////home/'):
    app.logger.warning("Detected PythonAnywhere path on Windows. Falling back to local.db.")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///local.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def migrate_db():
    with app.app_context():
        # 1. Ensure all tables exist
        db.create_all()
        
        # 2. Manual column additions for SQLite/existing DBs
        inspector = db.inspect(db.engine)
        
        # Withdrawals fix
        cols_w = [c['name'] for c in inspector.get_columns('withdrawals')]
        with db.engine.connect() as conn:
            if 'bank_name' not in cols_w:
                conn.execute(text("ALTER TABLE withdrawals ADD COLUMN bank_name TEXT"))
            if 'account_number' not in cols_w:
                conn.execute(text("ALTER TABLE withdrawals ADD COLUMN account_number TEXT"))
            if 'account_name' not in cols_w:
                conn.execute(text("ALTER TABLE withdrawals ADD COLUMN account_name TEXT"))
            
            # AccessKeys fix
            cols_ak = [c['name'] for c in inspector.get_columns('access_keys')]
            if 'bank_name' not in cols_ak:
                conn.execute(text("ALTER TABLE access_keys ADD COLUMN bank_name TEXT"))
            if 'account_number' not in cols_ak:
                conn.execute(text("ALTER TABLE access_keys ADD COLUMN account_number TEXT"))
            if 'account_name' not in cols_ak:
                conn.execute(text("ALTER TABLE access_keys ADD COLUMN account_name TEXT"))

            # Keywords fix
            cols_kw = [c['name'] for c in inspector.get_columns('keywords')]
            if 'config' not in cols_kw:
                # SQLite doesn't support JSON type natively in alter but TEXT works
                conn.execute(text("ALTER TABLE keywords ADD COLUMN config TEXT"))
            
            conn.commit()

# migrate_db() will be called after models are defined.# --- Redis Configuration ---
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
# Allow disabling Redis in strict dev environments if not available
USE_REDIS = os.environ.get('USE_REDIS', 'true').lower() == 'true'
if USE_REDIS:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
    except Exception as e:
        app.logger.error(f"Redis connection failed: {e}. Falling back to DB-only queueing.")
        USE_REDIS = False
        redis_client = None
else:
    redis_client = None

# --- Models ---
class AccessKey(db.Model):
    __tablename__ = 'access_keys'
    id = db.Column(db.Integer, primary_key=True)
    key_value = db.Column(db.Text, unique=True, nullable=False)
    owner_name = db.Column(db.Text, nullable=False)
    wallet_address = db.Column(db.Text)
    bank_name = db.Column(db.Text)
    account_number = db.Column(db.Text)
    account_name = db.Column(db.Text)
    total_leads_processed = db.Column(db.Integer, default=0)
    total_successes = db.Column(db.Integer, default=0)
    total_earnings_ngn = db.Column(db.Numeric, default=0)
    withdrawn_ngn = db.Column(db.Numeric, default=0)
    last_active = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, default=True)
    is_banned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Keyword(db.Model):
    __tablename__ = 'keywords'
    id = db.Column(db.Integer, primary_key=True)
    keyword_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.Text, default='pending')
    assigned_to = db.Column(db.Integer, db.ForeignKey('access_keys.id'))
    assigned_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    result_count = db.Column(db.Integer, default=0)
    config = db.Column(db.JSON, nullable=True) # Stores Campaign settings (Address, Email, etc)

class KeyRequest(db.Model):
    __tablename__ = 'key_requests'
    id = db.Column(db.Integer, primary_key=True)
    worker_name = db.Column(db.Text, nullable=True)  # Optional display name
    contact_info = db.Column(db.Text, nullable=False)  # Email required
    status = db.Column(db.Text, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Lead(db.Model):
    __tablename__ = 'leads'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text)
    phone = db.Column(db.Text)
    website = db.Column(db.Text)
    address = db.Column(db.Text)
    keyword_source = db.Column(db.Text)
    status = db.Column(db.Text, default='new')
    assigned_to = db.Column(db.Integer, db.ForeignKey('access_keys.id'))
    assigned_at = db.Column(db.DateTime(timezone=True))
    last_attempt_at = db.Column(db.DateTime(timezone=True))
    attempt_count = db.Column(db.Integer, default=0)
    sequence_step = db.Column(db.Integer, default=1)
    project_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class EarningsLog(db.Model):
    __tablename__ = 'earnings_log'
    id = db.Column(db.Integer, primary_key=True)
    access_key_id = db.Column(db.Integer, db.ForeignKey('access_keys.id'), nullable=False)
    type = db.Column(db.Text, nullable=False)
    amount_ngn = db.Column(db.Numeric, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AppVersion(db.Model):
    __tablename__ = 'app_versions'
    id = db.Column(db.Integer, primary_key=True)
    version_string = db.Column(db.Text, nullable=False)
    min_required_version = db.Column(db.Text)
    download_url = db.Column(db.Text)
    changelog = db.Column(db.Text)
    is_obsolete = db.Column(db.Boolean, default=False)

class Withdrawal(db.Model):
    __tablename__ = 'withdrawals'
    id = db.Column(db.Integer, primary_key=True)
    access_key_id = db.Column(db.Integer, db.ForeignKey('access_keys.id'), nullable=False)
    amount_ngn = db.Column(db.Numeric, nullable=False)
    bank_name = db.Column(db.Text)
    account_number = db.Column(db.Text)
    account_name = db.Column(db.Text)
    status = db.Column(db.Text, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime(timezone=True))
    admin_note = db.Column(db.Text)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    target = db.Column(db.Text, default='all')
    title = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class BugReport(db.Model):
    __tablename__ = 'bug_reports'
    id = db.Column(db.Integer, primary_key=True)
    access_key_id = db.Column(db.Integer, db.ForeignKey('access_keys.id'), nullable=False)
    category = db.Column(db.Text, nullable=False)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    screenshot_url = db.Column(db.Text)
    status = db.Column(db.Text, default='open')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class GlobalSetting(db.Model):
    __tablename__ = 'global_settings'
    id = db.Column(db.Text, primary_key=True)
    value = db.Column(db.JSON, nullable=False)

# --- Middleware ---

def require_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        key_val = request.headers.get('X-Access-Key')
        if not key_val:
            return jsonify({"error": "Missing access key"}), 401
        
        # Cache check could be added here
        ak = AccessKey.query.filter_by(key_value=key_val).first()
        if not ak or not ak.is_active or ak.is_banned:
            return jsonify({"error": "Invalid or revoked access key"}), 403
            
        # Update last active (in a real high-throughput env, do this async or via Redis cache)
        # We'll batch this or let heartbeat handle it to reduce DB writes on every API call
        request.access_key = ak
        return f(*args, **kwargs)
    return decorated_function

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_key = os.environ.get('ADMIN_SECRET_KEY')
        if not admin_key or request.headers.get('Authorization') != f"Bearer {admin_key}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function



@app.route('/')
def home():
    # Performance check & Optional wipe trigger
    # Usage: visit /?wipe_keywords=token (token is a safety measure)
    if request.args.get('wipe_keywords') == 'confirm':
        try:
            Keyword.query.delete()
            db.session.commit()
            return "SUCCESS: All keywords wiped."
        except Exception as e:
            return f"ERROR: {e}"

    # Attempt to create tables on every home visit just in case of environment migration
    try:
        db.create_all()
    except Exception as e:
        app.logger.error(f"Table check failed: {e}")

    # Simple Stat Gathering for Dashboard
    try:
        worker_count = AccessKey.query.count()
        lead_count = Lead.query.count()
        kw_count = Keyword.query.count()
    except:
        worker_count = lead_count = kw_count = 0

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CMining Backend | Status</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; }}
            .glass {{ background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); }}
        </style>
    </head>
    <body class="bg-slate-950 text-slate-200 min-h-screen flex items-center justify-center p-6">
        <div class="max-w-4xl w-full">
            <div class="glass border border-slate-800 rounded-3xl p-8 md:p-12 shadow-2xl">
                <div class="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
                    <div>
                        <h1 class="text-4xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent mb-2">
                            CMining System Online
                        </h1>
                        <p class="text-slate-400">Server is running correctly on PythonAnywhere.</p>
                    </div>
                    <div class="flex items-center gap-2 bg-emerald-500/10 text-emerald-400 px-4 py-2 rounded-full border border-emerald-500/20">
                        <span class="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                        <span class="text-sm font-semibold uppercase tracking-wider">Active</span>
                    </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
                    <div class="bg-slate-900/50 border border-slate-800 p-6 rounded-2xl">
                        <p class="text-slate-500 text-sm font-medium mb-1">Total Workers</p>
                        <p class="text-3xl font-bold">{worker_count}</p>
                    </div>
                    <div class="bg-slate-900/50 border border-slate-800 p-6 rounded-2xl">
                        <p class="text-slate-500 text-sm font-medium mb-1">Leads Found</p>
                        <p class="text-3xl font-bold text-blue-400">{lead_count}</p>
                    </div>
                    <div class="bg-slate-900/50 border border-slate-800 p-6 rounded-2xl">
                        <p class="text-slate-500 text-sm font-medium mb-1">Keywords</p>
                        <p class="text-3xl font-bold text-emerald-400">{kw_count}</p>
                    </div>
                </div>

                <div class="space-y-4">
                    <div class="p-4 bg-slate-900/30 rounded-xl border border-slate-800 flex items-center justify-between">
                        <span class="text-slate-400">API Endpoint</span>
                        <code class="text-blue-400 text-sm">/api/version/check</code>
                    </div>
                    <div class="p-4 bg-slate-900/30 rounded-xl border border-slate-800 flex items-center justify-between">
                        <span class="text-slate-400">Server Time</span>
                        <span class="text-sm font-mono text-slate-500">{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</span>
                    </div>
                </div>

                <div class="mt-12 text-center">
                    <p class="text-xs text-slate-600 uppercase tracking-tighter">Powered by Antigravity AI Engine</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html

# --- Public / Worker Endpoints ---

@app.route('/api/validate', methods=['POST'])
def validate():
    try:
        data = request.json or {}
        key_val = data.get('access_key')
        if not key_val:
            return jsonify({"error": "Missing access key"}), 400
        
        ak = AccessKey.query.filter_by(key_value=key_val).first()
        if not ak:
            return jsonify({"error": "Invalid access key. Please check your Dashboard."}), 403
        if ak.is_banned:
            return jsonify({"error": "This access key has been banned. Contact administrator."}), 403
        if not ak.is_active:
            return jsonify({"error": "This access key is currently inactive."}), 403
            
        return jsonify({"status": "authorized", "owner": ak.owner_name, "worker_id": ak.id})
    except Exception as e:
        return jsonify({"error": f"Database error during validation: {str(e)}"}), 500

@app.route('/api/request_key', methods=['POST'])
@app.route('/api/keys/request', methods=['POST'])
def request_key():
    try:
        data = request.json or {}
        # Email is the only required field
        c_info = data.get('contact_info') or data.get('email') or data.get('worker_name')
        w_name = data.get('worker_name') or data.get('name') or c_info
        
        if not c_info:
            return jsonify({"error": "Email address is required to request an access key."}), 400
        
        # Prevent duplicate pending requests for same email
        existing = KeyRequest.query.filter_by(contact_info=c_info, status='pending').first()
        if existing:
            return jsonify({"status": "success", "message": "Request already submitted. Please wait for admin approval."})
        
        kr = KeyRequest(worker_name=w_name, contact_info=c_info)
        db.session.add(kr)
        db.session.commit()
        return jsonify({"status": "success", "message": "Access Key requested. You will be contacted at your email."})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"KeyRequest error: {e}")
        return jsonify({"error": "Failed to store request. Please try again."}), 500

@app.route('/api/worker/version', methods=['GET'])
def get_latest_version():
    latest = AppVersion.query.order_by(AppVersion.id.desc()).first()
    if not latest:
        return jsonify({"version_string": "1.0.0", "is_force_update": False})
    return jsonify({
        "version_string": latest.version_string,
        "download_url": latest.download_url,
        "changelog": latest.changelog,
        "is_force_update": latest.is_obsolete
    })

@app.route('/api/worker/pricing', methods=['GET'])
@require_key
def get_pricing_for_worker():
    rate_setting = GlobalSetting.query.get('earnings_rates')
    rates = rate_setting.value if rate_setting else {"scraper_rate": 25, "outreach_rate": 250, "withdrawal_limit": 50000}
    return jsonify(rates)

@app.route('/api/worker/bug', methods=['POST'])
@app.route('/api/bugs/report', methods=['POST'])
@require_key
def worker_bug():
    data = request.json or {}
    ak = request.access_key
    bug = BugReport(access_key_id=ak.id, category=data.get('category', 'General'), 
                    title=data.get('title', 'Bug Report'), description=data.get('description', ''))
    db.session.add(bug)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/withdrawals/request', methods=['POST'])
@require_key
def worker_withdraw():
    try:
        data = request.json or {}
        ak = request.access_key
        amount = float(data.get('amount', 0))
        
        if amount <= 0:
            return jsonify({"error": "Please enter a valid withdrawal amount."}), 400

        if amount < 100000:
            return jsonify({"error": "Minimum withdrawal amount is ₦100,000"}), 400

        # Check available balance (earnings minus already withdrawn/pending amounts)
        total_earned = float(ak.total_earnings_ngn or 0)
        total_withdrawn = float(ak.withdrawn_ngn or 0)
        # Also account for any currently PENDING withdrawal requests
        pending_sum = db.session.query(db.func.sum(Withdrawal.amount_ngn)).filter_by(
            access_key_id=ak.id, status='pending'
        ).scalar() or 0
        available_balance = total_earned - total_withdrawn - float(pending_sum)

        if amount > available_balance:
            return jsonify({"error": f"Insufficient balance. Available: ₦{available_balance:,.0f}"}), 400
            
        bank = data.get('bank', 'Unknown')
        account = data.get('account', 'Unknown')
        name = data.get('name', 'Unknown')

        # Deduct from balance immediately when request is submitted
        ak.withdrawn_ngn = (ak.withdrawn_ngn or 0) + amount
        
        w = Withdrawal(
            access_key_id=ak.id, 
            amount_ngn=amount,
            bank_name=bank,
            account_number=account,
            account_name=name
        )
        db.session.add(w)
        db.session.commit()
        return jsonify({"status": "success", "message": f"Withdrawal request of ₦{amount:,.0f} submitted."})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Withdrawal Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/version/check', methods=['GET'])
def check_version():
    try:
        client_version = request.args.get('version', '0.0.0')
        latest = AppVersion.query.order_by(AppVersion.id.desc()).first()
        if latest:
            return jsonify({
                "latest_version": latest.version_string,
                "min_required_version": latest.min_required_version,
                "is_obsolete": latest.is_obsolete,
                "download_url": latest.download_url,
                "changelog": latest.changelog
            })
    except Exception as e:
        app.logger.error(f"Version check DB error: {e}")
    
    return jsonify({"is_obsolete": False, "latest_version": "1.0.0"})

@app.route('/api/heartbeat', methods=['POST'])
@require_key
def heartbeat():
    ak = request.access_key
    ak.last_active = datetime.now(timezone.utc)
    db.session.commit()
    if USE_REDIS:
        redis_client.setex(f"worker_heartbeat:{ak.id}", 120, "alive")
    return jsonify({"status": "ok"})

@app.route('/api/worker/stats', methods=['GET'])
@require_key
def worker_stats():
    ak = request.access_key
    pending_withdrawals = Withdrawal.query.filter_by(access_key_id=ak.id, status='pending').count()
    return jsonify({
        "balance": float(ak.total_earnings_ngn - (ak.withdrawn_ngn or 0)),
        "pending": pending_withdrawals,
        "successes": ak.total_successes
    })


# --- Batches ---

@app.route('/api/batch/keywords', methods=['POST'])
@require_key
def batch_keywords():
    ak = request.access_key
    data = request.json or {}
    batch_size = min(int(data.get('batch_size', 1)), 10)
    
    # CRITICAL: Startup Batch Recovery
    # Check if the worker already has assigned keywords that aren't completed
    existing = Keyword.query.filter_by(assigned_to=ak.id, status='assigned').all()
    if existing:
        return jsonify({"keywords": [{"id": k.id, "keyword_text": k.keyword_text} for k in existing]})
    
    # Get new batch via Redis if available, fallback to DB RPC
    assigned_keywords = []
    
    if USE_REDIS:
        # LPOP from Redis queue
        for _ in range(batch_size):
            kw_id = redis_client.lpop("queue:keywords")
            if not kw_id: break
            
            k = Keyword.query.get(int(kw_id))
            if k and k.status == 'pending':
                k.status = 'assigned'
                k.assigned_to = ak.id
                k.assigned_at = datetime.now(timezone.utc)
                assigned_keywords.append(k)
        
        if assigned_keywords:
            db.session.commit()
    else:
        # Fallback to Supabase RPC
        result = db.session.execute(text("SELECT * FROM claim_keyword_batch(:wid, :bsize)"), 
                                    {"wid": ak.id, "bsize": batch_size})
        assigned_keywords = result.fetchall()
        db.session.commit()
        
        # Note: If sqlite locally, claim_keyword_batch doesn't exist, we must use a programmatic lock
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI'] and not assigned_keywords:
            kws = Keyword.query.filter_by(status='pending').limit(batch_size).all()
            for k in kws:
                k.status = 'assigned'
                k.assigned_to = ak.id
                k.assigned_at = datetime.now(timezone.utc)
                assigned_keywords.append(k)
            db.session.commit()

    return jsonify({"keywords": [{"id": k.id if hasattr(k, 'id') else k[0], "keyword_text": k.keyword_text if hasattr(k, 'keyword_text') else k[1]} for k in assigned_keywords]})

@app.route('/api/batch/leads', methods=['POST'])
@require_key
def batch_leads():
    ak = request.access_key
    data = request.json or {}
    batch_size = min(int(data.get('batch_size', 5)), 20)
    
    existing = Lead.query.filter_by(assigned_to=ak.id, status='assigned').all()
    if existing:
        return jsonify({"leads": [{"id": l.id, "name": l.name, "website": l.website, "phone": l.phone, "address": l.address} for l in existing]})
        
    assigned_leads = []
    
    if USE_REDIS:
        for _ in range(batch_size):
            l_id = redis_client.lpop("queue:leads")
            if not l_id: break
            
            l = Lead.query.get(int(l_id))
            if l and l.status == 'new':
                l.status = 'assigned'
                l.assigned_to = ak.id
                l.assigned_at = datetime.now(timezone.utc)
                assigned_leads.append(l)
        if assigned_leads:
            db.session.commit()
    else:
        # Fallback to Supabase RPC
        result = db.session.execute(text("SELECT * FROM claim_lead_batch(:wid, :bsize)"), 
                                    {"wid": ak.id, "bsize": batch_size})
        assigned_leads = result.fetchall()
        db.session.commit()
        
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI'] and not assigned_leads:
            lds = Lead.query.filter_by(status='new').limit(batch_size).all()
            for l in lds:
                l.status = 'assigned'
                l.assigned_to = ak.id
                l.assigned_at = datetime.now(timezone.utc)
                assigned_leads.append(l)
            db.session.commit()

    # Format output handling mapping whether it's an object or tuple from raw SQL
    res = []
    for l in assigned_leads:
        kw_src = l.keyword_source if hasattr(l, 'keyword_source') else l[5]
        config = {}
        if kw_src:
            k = Keyword.query.filter_by(keyword_text=kw_src).first()
            if k and k.config:
                config = k.config
                
                # LEAD EXCLUSION LOGIC
                exclusions = config.get('exclusions', [])
                if any(excl.lower() in (l.name or "").lower() or excl.lower() in (l.website or "").lower() for excl in exclusions):
                    l.status = 'excluded'
                    continue

        res.append({
            "id": l.id if hasattr(l, 'id') else l[0],
            "name": l.name if hasattr(l, 'name') else l[1],
            "website": l.website if hasattr(l, 'website') else l[3],
            "phone": l.phone if hasattr(l, 'phone') else l[2],
            "address": l.address if hasattr(l, 'address') else l[4],
            "config": config,
            "step": l.sequence_step if hasattr(l, 'sequence_step') else l[9] # Index 9 is sequence_step
        })
    
    if len(res) < len(assigned_leads):
        db.session.commit() # save exclusions

    return jsonify({"leads": res})

@app.route('/api/batch/results', methods=['POST'])
@require_key
def batch_results():
    ak = request.access_key
    data = request.json or {}
    results = data.get('results', [])
    completed_ids = data.get('completed_keyword_ids', [])
    
    # Process the scraped leads and insert them into the Leads table queue
    inserted_leads = []
    for r in results:
        # Deduplication could be done here (check domain/phone)
        domain = r.get('website', '').replace('https://','').replace('http://','').strip('/')
        if not domain: continue
        
        # Avoid duplicate domain insertion (Basic check)
        exists = Lead.query.filter(Lead.website.ilike(f'%{domain}%')).first()
        if not exists:
            new_lead = Lead(name=r.get('name'), phone=r.get('phone'), website=r.get('website'), address=r.get('address'), keyword_source=r.get('keyword_source'), status='new')
            db.session.add(new_lead)
            inserted_leads.append(new_lead)
    
    db.session.commit() # commit so they get IDs
    
    # Push to Redis queue for outreach
    if USE_REDIS and inserted_leads:
        for l in inserted_leads:
            redis_client.rpush("queue:leads", l.id)
            
    # Mark keywords as completed & Credit worker
    for kid in completed_ids:
        kw = Keyword.query.filter_by(id=kid, assigned_to=ak.id).first()
        if kw:
            kw.status = 'done'
            kw.completed_at = datetime.now(timezone.utc)
            kw.result_count = len([x for x in results if x.get('keyword_source') == kw.keyword_text])
            
            # Credit Earnings: 50 NGN per batch
            credit_amount = 50
            ak.total_earnings_ngn = float(ak.total_earnings_ngn or 0) + float(credit_amount)
            elog = EarningsLog(access_key_id=ak.id, type='keyword_batch', amount_ngn=credit_amount)
            db.session.add(elog)
            
    db.session.commit()
    return jsonify({"status": "success", "inserted": len(inserted_leads)})

@app.route('/api/batch/report', methods=['POST'])
@require_key
def batch_report():
    ak = request.access_key
    data = request.json or {}
    results = data.get('results', [])
    
    successes = 0
    for r in results:
        lead_id = r.get('lead_id')
        status = r.get('status')
        lead = Lead.query.filter_by(id=lead_id, assigned_to=ak.id).first()
        if lead:
            lead.status = status
            lead.attempt_count += 1
            lead.last_attempt_at = datetime.now(timezone.utc)
            if 'SUCCESS' in status:
                successes += 1
                
    # Update worker stats & earnings
    ak.total_leads_processed = (ak.total_leads_processed or 0) + len(results)
    ak.total_successes = (ak.total_successes or 0) + successes
    
    # Base rate logic checking Global Settings can be added later, for now flat 250 NGN if successes > 0
    if len(results) > 0:
        credit_amount = 250
        ak.total_earnings_ngn = float(ak.total_earnings_ngn or 0) + float(credit_amount)
        elog = EarningsLog(access_key_id=ak.id, type='lead_batch', amount_ngn=credit_amount)
        db.session.add(elog)
        
    db.session.commit()
    return jsonify({"status": "success"})


# --- Admin Endpoints ---

@app.route('/api/notifications/active', methods=['GET'])
@app.route('/api/worker/notifications', methods=['GET'])
@require_key
def worker_notifications():
    noti = Notification.query.order_by(Notification.id.desc()).limit(10).all()
    return jsonify([{"id": n.id, "title": n.title, "body": n.body, "created_at": n.created_at} for n in noti])

@app.route('/api/admin/notifications/<int:n_id>', methods=['DELETE'])
@require_admin
def delete_notification(n_id):
    n = Notification.query.get(n_id)
    if not n: return jsonify({"error": "Not found"}), 404
    db.session.delete(n)
    db.session.commit()
    return jsonify({"status": "deleted"})

@app.route('/api/admin/stats', methods=['GET'])
@require_admin
def admin_stats():
    # Summarized stats
    total_workers = AccessKey.query.count()
    active_workers = AccessKey.query.filter_by(is_active=True).count()
    total_kws = Keyword.query.count()
    pending_kws = Keyword.query.filter_by(status='pending').count()
    total_lds = Lead.query.count()
    success_lds = Lead.query.filter(Lead.status.ilike('%SUCCESS%')).count()
    
    return jsonify({
        "workers": {"total": total_workers, "active": active_workers},
        "keywords": {"total": total_kws, "pending": pending_kws},
        "leads": {"total": total_lds, "successes": success_lds}
    })

def auto_reclaim_stale_assignments():
    try:
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        stale_kws = Keyword.query.filter(Keyword.status == 'assigned', Keyword.assigned_at < one_hour_ago).all()
        for kw in stale_kws:
            kw.status = 'pending'
        stale_leads = Lead.query.filter(Lead.status == 'assigned', Lead.assigned_at < one_hour_ago).all()
        for l in stale_leads:
            l.status = 'new'
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Auto-reclaim error: {e}")

@app.route('/api/admin/overview', methods=['GET'])
@require_admin
def admin_overview():
    auto_reclaim_stale_assignments()
    now = datetime.now(timezone.utc)
    one_day_ago = now - timedelta(days=1)
    
    active_workers = AccessKey.query.filter(AccessKey.last_active > one_day_ago).count()
    scraped_today = Lead.query.filter(Lead.created_at > one_day_ago).count()
    successes_today = Lead.query.filter(Lead.status.ilike('%SUCCESS%'), Lead.last_attempt_at > one_day_ago).count()
    total_earnings = db.session.query(db.func.sum(AccessKey.total_earnings_ngn)).scalar() or 0
    pending_withdrawals = Withdrawal.query.filter_by(status='pending').count()
    pending_keywords = Keyword.query.filter_by(status='pending').count()
    
    return jsonify({
        "workers": {"active": active_workers},
        "leads": {"total": scraped_today, "successes": successes_today},
        "earnings": float(total_earnings),
        "pending_withdrawals": pending_withdrawals,
        "keywords": {"pending": pending_keywords}
    })

@app.route('/api/admin/notify', methods=['GET', 'POST'])
@require_admin
def admin_notify():
    if request.method == 'GET':
        notifs = Notification.query.order_by(Notification.id.desc()).limit(50).all()
        return jsonify({"notifications": [{"id": n.id, "title": n.title, "body": n.body, "created_at": n.created_at.isoformat() if n.created_at else None} for n in notifs]})
    # POST - Send new notification
    data = request.json or {}
    new_notif = Notification(title=data.get('title', 'System Update'), body=data.get('body', ''), target=data.get('target', 'all'))
    db.session.add(new_notif)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/admin/withdrawals', methods=['GET'])
@require_admin
def admin_withdrawals():
    # Show all pending withdrawals with full worker details
    pending = Withdrawal.query.filter_by(status='pending').order_by(Withdrawal.created_at.desc()).all()
    result = []
    for w in pending:
        ak = AccessKey.query.get(w.access_key_id)
        avail = float(ak.total_earnings_ngn or 0) - float(ak.withdrawn_ngn or 0) if ak else 0
        result.append({
            "id": w.id,
            "amount_ngn": float(w.amount_ngn),
            "access_key_id": w.access_key_id,
            "owner_name": ak.owner_name if ak else 'Unknown Worker',
            "bank_name": w.bank_name,
            "account_number": w.account_number,
            "account_name": w.account_name,
            "worker_balance": avail,
            "created_at": w.created_at.isoformat() if w.created_at else None
        })
    return jsonify({"withdrawals": result})

@app.route('/api/admin/withdrawals/<int:w_id>/approve', methods=['POST'])
@require_admin
def approve_withdrawal(w_id):
    """Approve withdrawal. Balance was already deducted at request time — nothing more to deduct."""
    w = Withdrawal.query.get(w_id)
    if w and w.status == 'pending':
        w.status = 'approved'
        w.processed_at = datetime.now(timezone.utc)
        # Balance was pre-deducted at request time, so no further deduction needed
        db.session.commit()
        return jsonify({"status": "approved"})
    return jsonify({"error": "Invalid or already processed withdrawal"}), 400

@app.route('/api/admin/withdrawals/<int:w_id>/reject', methods=['POST'])
@require_admin
def reject_withdrawal(w_id):
    """Reject withdrawal and REFUND the balance back to the worker."""
    w = Withdrawal.query.get(w_id)
    if w and w.status == 'pending':
        w.status = 'rejected'
        w.processed_at = datetime.now(timezone.utc)
        # REFUND: add the amount back to the worker's withdrawn_ngn (reversing the deduction)
        ak = AccessKey.query.get(w.access_key_id)
        if ak:
            ak.withdrawn_ngn = max(0, float(ak.withdrawn_ngn or 0) - float(w.amount_ngn))
        db.session.commit()
        return jsonify({"status": "rejected"})
    return jsonify({"error": "Invalid or already processed withdrawal"}), 400

@app.route('/api/admin/earnings_rates', methods=['GET', 'POST'])
@require_admin
def update_rates():
    if request.method == 'GET':
        rate_setting = GlobalSetting.query.get('earnings_rates')
        rates = rate_setting.value if rate_setting else {"scraper_rate": 25, "outreach_rate": 250, "withdrawal_limit": 50000}
        return jsonify({"rates": rates})
    data = request.json or {}
    rate_setting = GlobalSetting.query.get('earnings_rates')
    if not rate_setting:
        rate_setting = GlobalSetting(id='earnings_rates', value=data)
        db.session.add(rate_setting)
    else:
        rate_setting.value = data
    db.session.commit()
    return jsonify({"status": "success", "rates": data})

@app.route('/api/admin/bugs', methods=['GET', 'DELETE'])
@require_admin
def admin_bugs():
    if request.method == 'DELETE':
        b_id = request.args.get('id')
        if b_id:
            BugReport.query.filter_by(id=b_id).delete()
            db.session.commit()
        return jsonify({"status": "deleted"})
        
    bugs = BugReport.query.filter_by(status='open').all()
    return jsonify({"bugs": [{"id": b.id, "title": b.title, "description": b.description, "worker_id": b.access_key_id} for b in bugs]})

@app.route('/api/admin/key_requests', methods=['GET'])
@require_admin
def admin_key_requests():
    reqs = KeyRequest.query.filter_by(status='pending').all()
    return jsonify({"requests": [{"id": r.id, "worker_name": r.worker_name, "contact_info": r.contact_info} for r in reqs]})

@app.route('/api/admin/versions', methods=['POST'])
@require_admin
def publish_version():
    data = request.json or {}
    ver = AppVersion(
        version_string=data['version_string'], 
        min_required_version=data.get('min_required_version'), 
        download_url=data.get('download_url'), 
        changelog=data.get('changelog'),
        is_obsolete=data.get('is_obsolete', False)
    )
    db.session.add(ver)
    db.session.commit()
    return jsonify({"status": "published"})

@app.route('/api/admin/keywords', methods=['GET', 'POST', 'DELETE'])
@require_admin
def admin_keywords():
    if request.method == 'POST':
        data = request.json or {}
        raw_text = data.get('keyword_text', '').strip()
        if not raw_text:
            return jsonify({"error": "Search terms are required."}), 400
            
        # Handle bulk (split by newline only)
        kws = [k.strip() for k in raw_text.split('\n') if k.strip()]
        added = 0
        for k_text in kws:
            # Avoid direct duplicates in same batch
            k = Keyword(keyword_text=k_text, status='pending', config=data.get('config', {}))
            db.session.add(k)
            added += 1
        db.session.commit()
        return jsonify({"status": "success", "added_count": added})

    if request.method == 'DELETE':
        # Wipe all keywords if purge flag is set
        if request.args.get('purge') == 'true':
            Keyword.query.delete()
            db.session.commit()
            return jsonify({"status": "success", "message": "All keywords wiped."})
        
        # Delete specific
        k_id = request.args.get('id')
        if k_id:
            Keyword.query.filter_by(id=k_id).delete()
            db.session.commit()
            return jsonify({"status": "deleted"})
            
    # Return keywords that are NOT done (to avoid clutter)
    keywords = Keyword.query.order_by(Keyword.id.desc()).limit(500).all()
    pending = Keyword.query.filter_by(status='pending').count()
    assigned = Keyword.query.filter_by(status='assigned').count()
    done = Keyword.query.filter_by(status='done').count()
    return jsonify({
        "keywords": [{"id": k.id, "keyword_text": k.keyword_text, "status": k.status, "result_count": k.result_count} for k in keywords],
        "counts": {"pending": pending, "assigned": assigned, "done": done}
    })

@app.route('/api/admin/keys', methods=['GET', 'POST', 'PUT', 'DELETE'])
@require_admin
def admin_keys():
    if request.method == 'POST':
        data = request.json or {}
        ak = AccessKey(key_value=data.get('key_value'), owner_name=data.get('owner_name', 'Unknown'))
        db.session.add(ak)
        db.session.commit()
        return jsonify({"status": "success"})
    
    if request.method == 'PUT':
        data = request.json or {}
        k_id = data.get('id')
        ak = AccessKey.query.get(k_id)
        if not ak: return jsonify({"error": "Not found"}), 404
        if 'is_banned' in data:
            ak.is_banned = data['is_banned']
        if 'is_active' in data:
            ak.is_active = data['is_active']
        db.session.commit()
        return jsonify({"status": "updated"})

    if request.method == 'DELETE':
        k_id = request.args.get('id')
        ak = AccessKey.query.get(k_id)
        if ak:
            db.session.delete(ak)
            db.session.commit()
        return jsonify({"status": "deleted"})

    keys = AccessKey.query.all()
    requests_pending = KeyRequest.query.filter_by(status='pending').all()
    return jsonify({
        "keys": [{"id": k.id, "key_value": k.key_value, "owner_name": k.owner_name, "is_active": k.is_active, "is_banned": k.is_banned, "total_leads": k.total_successes, "total_earnings": float(k.total_earnings_ngn or 0)} for k in keys],
        "requests": [{"id": r.id, "worker_name": r.worker_name, "contact_info": r.contact_info, "status": r.status} for r in requests_pending]
    })

@app.route('/api/admin/keys/requests/<int:r_id>/approve', methods=['POST'])
@require_admin
def approve_key_request(r_id):
    kr = KeyRequest.query.get(r_id)
    if not kr or kr.status != 'pending':
        return jsonify({"error": "Invalid request"}), 400
    
    # Generate a random key
    import random, string
    new_val = "CM-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    ak = AccessKey(key_value=new_val, owner_name=kr.worker_name)
    kr.status = 'approved'
    db.session.add(ak)
    db.session.commit()
    return jsonify({"status": "approved", "key": new_val})

@app.route('/api/admin/leads', methods=['GET', 'DELETE'])
@require_admin
def admin_leads():
    if request.method == 'DELETE':
        src = request.args.get('source')
        if src:
            Lead.query.filter_by(keyword_source=src).delete()
        else:
            Lead.query.filter(Lead.project_id.is_(None)).delete()
        db.session.commit()
        return jsonify({"status": "cleared"})
    
    # Return grouped queries for Map Scraper outputs (where project_id is None)
    summary = db.session.query(
        db.func.date(Lead.created_at).label('date'),
        Lead.keyword_source,
        db.func.count(Lead.id).label('total')
    ).filter(Lead.project_id.is_(None)).group_by(db.func.date(Lead.created_at), Lead.keyword_source).order_by(db.desc('date')).all()
    
    return jsonify({"grouped_leads": [{
        "date": str(s[0]),
        "source": s[1] or 'Unknown',
        "count": s[2]
    } for s in summary]})

@app.route('/api/admin/leads/download', methods=['GET'])
@require_admin
def download_leads():
    import csv, io
    from flask import make_response
    src = request.args.get('source')
    dt = request.args.get('date')
    
    q = Lead.query.filter(Lead.project_id.is_(None))
    if src: q = q.filter(Lead.keyword_source == src)
    if dt: q = q.filter(db.func.date(Lead.created_at) == dt)
    
    leads = q.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Phone', 'Website', 'Address', 'Keyword Source', 'Status'])
    for l in leads:
        writer.writerow([l.id, l.name, l.phone, l.website, l.address, l.keyword_source, l.status])
    
    r = make_response(output.getvalue())
    filename = f"leads_{dt or 'all'}_{src or 'all'}.csv".replace(' ', '_')
    r.headers["Content-Disposition"] = f"attachment; filename={filename}"
    r.headers["Content-type"] = "text/csv"
    return r

@app.route('/api/admin/reclaim', methods=['POST'])
@require_admin
def reclaim_stale():
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    
    stale_kws = Keyword.query.filter(Keyword.status == 'assigned', Keyword.assigned_at < one_hour_ago).all()
    for kw in stale_kws:
        kw.status = 'pending'
    
    stale_leads = Lead.query.filter(Lead.status == 'assigned', Lead.assigned_at < one_hour_ago).all()
    for l in stale_leads:
        l.status = 'new'
        
    db.session.commit()
    return jsonify({"status": "success", "reclaimed_keywords": len(stale_kws), "reclaimed_leads": len(stale_leads)})

@app.route('/api/admin/campaigns', methods=['GET', 'POST', 'PUT', 'DELETE'])
@require_admin
def admin_campaigns():
    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name', f"Campaign {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        leads = data.get('leads', [])
        # Config stores sub-fields: firstName, lastName, email, phone, address, city, state, zip, subject, message, sequenceSteps
        config = data.get('config', {})

        if not leads:
            return jsonify({"error": "No leads provided. Please upload a CSV/XLSX lead file."}), 400
            
        added = 0
        for r in leads:
            # Avoid duplicates by website
            website = r.get('website') or r.get('Website') or r.get('WEBSITE')
            if website:
                exists = Lead.query.filter_by(website=website).first()
                if exists:
                    continue
            nl = Lead(
                name=r.get('name') or r.get('Name') or r.get('NAME'),
                phone=r.get('phone') or r.get('Phone') or r.get('PHONE'),
                website=website,
                address=r.get('address') or r.get('Address') or r.get('ADDRESS'),
                keyword_source=name,
                status='new'
            )
            # Attach campaign config to each lead
            if config:
                nl.project_id = hash(name) % 999999
            db.session.add(nl)
            added += 1

        # Store config in a GlobalSetting by campaign name so outreach.js can use it
        if config:
            cfg_key = f"campaign_config_{name.replace(' ', '_')}"
            existing_cfg = GlobalSetting.query.get(cfg_key)
            if not existing_cfg:
                existing_cfg = GlobalSetting(id=cfg_key, value=config)
                db.session.add(existing_cfg)
            else:
                existing_cfg.value = config

        db.session.commit()
        return jsonify({"status": "success", "added_count": added})
    
    if request.method == 'PUT':
        # Append leads to an existing campaign
        data = request.json or {}
        new_leads = data.get('append_leads', [])
        added = 0
        for r in new_leads:
            website = r.get('website') or r.get('Website')
            exists = Lead.query.filter_by(website=website).first() if website else None
            if not exists:
                nl = Lead(
                    name=r.get('name') or r.get('Name'),
                    phone=r.get('phone') or r.get('Phone'),
                    website=website,
                    address=r.get('address') or r.get('Address'),
                    keyword_source=data.get('campaign_name', 'Topup'),
                    status='new'
                )
                db.session.add(nl)
                added += 1
        db.session.commit()
        return jsonify({"status": "success", "added_count": added})

    if request.method == 'DELETE':
        # Wipe all campaign leads
        Lead.query.delete()
        db.session.commit()
        return jsonify({"status": "success", "message": "All campaign leads wiped."})

    # GET: Group leads by keyword_source/campaign_name where project_id IS NOT NULL
    summary = db.session.query(
        Lead.keyword_source,
        db.func.count(Lead.id).label('total'),
        db.func.sum(db.cast(Lead.status.ilike('%SUCCESS%'), db.Integer)).label('successes')
    ).filter(Lead.project_id.is_not(None)).group_by(Lead.keyword_source).all()
    
    campaigns_data = []
    for s in summary:
        c_name = s[0] or 'Unnamed'
        cfg_key = f"campaign_config_{c_name.replace(' ', '_')}"
        gs = GlobalSetting.query.get(cfg_key)
        
        campaigns_data.append({
            "name": c_name,
            "count": s[1],
            "successes": s[2] or 0,
            "config": gs.value if gs else None
        })
        
    return jsonify({"campaigns": campaigns_data})

@app.route('/api/admin/settings', methods=['GET', 'POST'])
@require_admin
def admin_settings():
    if request.method == 'POST':
        data = request.json or {}
        for key, val in data.items():
            s = GlobalSetting.query.get(key)
            if not s:
                s = GlobalSetting(id=key, value=val)
                db.session.add(s)
            else:
                s.value = val
        db.session.commit()
        return jsonify({"status": "success"})
    
    settings = GlobalSetting.query.all()
    return jsonify({"settings": {s.id: s.value for s in settings}})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
