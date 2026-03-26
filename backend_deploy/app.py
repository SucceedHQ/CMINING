import os
import json
import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import redis
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Redis Configuration ---
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
    bank_details = db.Column(db.Text)
    status = db.Column(db.Text, default='pending')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime(timezone=True))
    admin_note = db.Column(db.Text)

class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    sequence_json = db.Column(db.JSON, nullable=False, default=[]) 
    start_date = db.Column(db.Text, nullable=True)  # ISO date string e.g. '2026-04-01'
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    # Attempt to create tables on every home visit just in case of environment migration
    try:
        db.create_all()
    except Exception as e:
        app.logger.error(f"Table creation failed: {e}")

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
    data = request.json or {}
    key_val = data.get('access_key')
    if not key_val:
        return jsonify({"error": "Missing access key"}), 400
    
    ak = AccessKey.query.filter_by(key_value=key_val).first()
    if not ak or not ak.is_active or ak.is_banned:
        return jsonify({"error": "Invalid access key"}), 403
        
    ak.last_active = datetime.now(timezone.utc)
    db.session.commit()
    
    return jsonify({"status": "authorized", "owner": ak.owner_name, "worker_id": ak.id})

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

@app.route('/api/earnings/me', methods=['GET'])
@require_key
def get_earnings():
    ak = request.access_key
    available = float(ak.total_earnings_ngn or 0) - float(ak.withdrawn_ngn or 0)
    # also subtract pending withdrawals
    pending_w = Withdrawal.query.filter_by(access_key_id=ak.id, status='pending').all()
    pending_sum = sum(float(w.amount_ngn) for w in pending_w)
    return jsonify({"total_earned": float(ak.total_earnings_ngn or 0), "withdrawn": float(ak.withdrawn_ngn or 0), "available": available - pending_sum, "pending": pending_sum})

@app.route('/api/earnings/withdraw', methods=['POST'])
@require_key
def request_withdrawal():
    ak = request.access_key
    data = request.json or {}
    amount = float(data.get('amount', 50000))
    bank_details = data.get('bank_details', '')
    
    if amount < 50000:
        return jsonify({"error": "Minimum withdrawal is 50,000 NGN"}), 400
    if not bank_details:
        return jsonify({"error": "Bank details are required"}), 400
        
    available = float(ak.total_earnings_ngn or 0) - float(ak.withdrawn_ngn or 0)
    pending_w = Withdrawal.query.filter_by(access_key_id=ak.id, status='pending').all()
    pending_sum = sum(float(w.amount_ngn) for w in pending_w)
    
    if amount > (available - pending_sum):
        return jsonify({"error": "Insufficient available funds"}), 400
        
    w = Withdrawal(access_key_id=ak.id, amount_ngn=amount, bank_details=bank_details)
    db.session.add(w)
    db.session.commit()
    return jsonify({"status": "success", "message": "Withdrawal requested successfully"})

@app.route('/api/bugs', methods=['POST'])
@require_key
def submit_bug():
    ak = request.access_key
    data = request.json or {}
    b = BugReport(
        access_key_id=ak.id,
        category='node_issue',
        title=data.get('title', 'Untitled'),
        description=data.get('desc', '')
    )
    db.session.add(b)
    db.session.commit()
    return jsonify({"status": "success"})

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
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            kws = Keyword.query.filter_by(status='pending').limit(batch_size).all()
            for k in kws:
                k.status = 'assigned'
                k.assigned_to = ak.id
                k.assigned_at = datetime.now(timezone.utc)
                assigned_keywords.append(k)
            db.session.commit()
        else:
            # Fallback to Supabase RPC
            result = db.session.execute(text("SELECT * FROM claim_keyword_batch(:wid, :bsize)"), 
                                        {"wid": ak.id, "bsize": batch_size})
            assigned_keywords = result.fetchall()
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
        
    project = Project.query.order_by(Project.id.desc()).first()
    sequence = project.sequence_json if project and getattr(project, 'sequence_json', None) else [{"delay_days": 0, "platform": "Email", "message": "Hi {name},\n\nWe are reaching out to discuss potential partnerships. Please get back to us.\n\nThanks"}]
        
    assigned_leads = []
    
    # Check for follow-ups in Python to avoid complex cross-dialect date-math
    existing_all = Lead.query.filter(Lead.assigned_to == ak.id, Lead.status.like('SUCCESS_%')).all()
    for l in existing_all:
        step_idx = l.sequence_step - 1
        if step_idx < len(sequence):
            delay_needed = sequence[step_idx].get('delay_days', 0)
            if l.last_attempt_at and datetime.now(timezone.utc) >= l.last_attempt_at + timedelta(days=int(delay_needed)):
                assigned_leads.append(l)
        else:
            if l.status != 'completed':
                l.status = 'completed'
                db.session.commit()
        if len(assigned_leads) >= batch_size:
            break
            
    rem = batch_size - len(assigned_leads)
    if rem > 0:
        if USE_REDIS:
            for _ in range(rem):
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
        
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            lds = Lead.query.filter_by(status='new').limit(rem).all()
            for l in lds:
                l.status = 'assigned'
                l.assigned_to = ak.id
                l.assigned_at = datetime.now(timezone.utc)
                assigned_leads.append(l)
            db.session.commit()
        else:
            # Fallback to Supabase RPC
            result = db.session.execute(text("SELECT * FROM claim_lead_batch(:wid, :bsize)"), 
                                        {"wid": ak.id, "bsize": rem})
            fetched_leads = result.fetchall()
            assigned_leads.extend(fetched_leads)
            db.session.commit()


    # Format output handling mapping whether it's an object or tuple from raw SQL
    res = []
    for l in assigned_leads:
        step_idx = (getattr(l, 'sequence_step', 1) or 1) - 1
        if step_idx >= len(sequence): step_idx = len(sequence) - 1
        if step_idx < 0: step_idx = 0
        
        step_cfg = sequence[step_idx]
        msg_template = step_cfg.get('message', 'Hi {name}, following up.')
        
        l_name = getattr(l, 'name', l[1] if isinstance(l, tuple) else '') or 'Business'
        msg_text = msg_template.replace('{name}', str(l_name))
        
        res.append({
            "id": getattr(l, 'id', l[0] if isinstance(l, tuple) else None),
            "name": l_name,
            "website": getattr(l, 'website', l[3] if isinstance(l, tuple) else None),
            "phone": getattr(l, 'phone', l[2] if isinstance(l, tuple) else None),
            "address": getattr(l, 'address', l[4] if isinstance(l, tuple) else None),
            "custom_message": msg_text
        })
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
                lead.sequence_step += 1
                
    # Update worker stats & earnings
    ak.total_leads_processed += len(results)
    ak.total_successes += successes
    
    # Base rate logic checking Global Settings can be added later, for now flat 250 NGN if successes > 0
    if len(results) > 0:
        credit_amount = 250
        ak.total_earnings_ngn = float(ak.total_earnings_ngn or 0) + float(credit_amount)
        elog = EarningsLog(access_key_id=ak.id, type='lead_batch', amount_ngn=credit_amount)
        db.session.add(elog)
        
    db.session.commit()
    return jsonify({"status": "success"})


# --- Admin Endpoints ---

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

@app.route('/api/admin/notify', methods=['POST'])
@require_admin
def admin_notify():
    # In a real environment, this inserts into the DB and the Realtime DB feature handles delivery
    # Using Supabase Realtime means we just insert into `notifications` and clients listening via Postgres channel get it.
    # So we just insert:
    data = request.json or {}
    new_notif = Notification(title=data.get('title', 'System Update'), body=data.get('body', ''), target=data.get('target', 'all'))
    db.session.add(new_notif)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/admin/withdrawals', methods=['GET'])
@require_admin
def admin_withdrawals():
    pending = Withdrawal.query.filter_by(status='pending').all()
    return jsonify({"withdrawals": [{"id": w.id, "amount_ngn": float(w.amount_ngn), "access_key_id": w.access_key_id, "bank_details": w.bank_details} for w in pending]})

@app.route('/api/admin/withdrawals/<int:w_id>/approve', methods=['POST'])
@require_admin
def approve_withdrawal(w_id):
    w = Withdrawal.query.get(w_id)
    if w and w.status == 'pending':
        w.status = 'approved'
        w.processed_at = datetime.now(timezone.utc)
        ak = AccessKey.query.get(w.access_key_id)
        if ak:
            ak.withdrawn_ngn = float(ak.withdrawn_ngn or 0) + float(w.amount_ngn)
        db.session.commit()
        return jsonify({"status": "approved"})
    return jsonify({"error": "Invalid withdrawal"}), 400

@app.route('/api/admin/earnings_rates', methods=['POST'])
@require_admin
def update_rates():
    data = request.json or {}
    rate_setting = GlobalSetting.query.get('earnings_rates')
    if not rate_setting:
        rate_setting = GlobalSetting(id='earnings_rates', value=data)
        db.session.add(rate_setting)
    else:
        rate_setting.value = data
    db.session.commit()
    return jsonify({"status": "success", "rates": data})

@app.route('/api/admin/change_password', methods=['POST'])
@require_admin
def change_password():
    data = request.json or {}
    new_pass = data.get('new_password')
    if new_pass:
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        try:
            with open(env_path, 'r') as f:
                lines = f.readlines()
            with open(env_path, 'w') as f:
                found = False
                for line in lines:
                    if line.startswith('ADMIN_SECRET_KEY='):
                        f.write(f"ADMIN_SECRET_KEY={new_pass}\n")
                        found = True
                    else:
                        f.write(line)
                if not found:
                    f.write(f"\nADMIN_SECRET_KEY={new_pass}\n")
            return jsonify({"status": "success", "message": "Password changed. Requires server reload."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Missing password"}), 400

@app.route('/api/admin/bugs', methods=['GET'])
@require_admin
def admin_bugs():
    bugs = BugReport.query.filter_by(status='open').all()
    return jsonify({"bugs": [{"id": b.id, "title": b.title, "description": b.description} for b in bugs]})

@app.route('/api/admin/versions', methods=['POST'])
@require_admin
def publish_version():
    data = request.json or {}
    ver = AppVersion(version_string=data['version_string'], min_required_version=data.get('min_required_version'), download_url=data.get('download_url'), changelog=data.get('changelog'))
    db.session.add(ver)
    db.session.commit()
    return jsonify({"status": "published"})

@app.route('/api/admin/keys', methods=['GET', 'POST'])
@require_admin
def admin_keys():
    if request.method == 'POST':
        data = request.json or {}
        ak = AccessKey(key_value=data.get('key_value'), owner_name=data.get('owner_name', 'Unknown'))
        db.session.add(ak)
        db.session.commit()
        return jsonify({"status": "success"})
    keys = AccessKey.query.all()
    return jsonify({"keys": [{"id": k.id, "key_value": k.key_value, "owner_name": k.owner_name, "is_active": k.is_active, "total_leads": k.total_leads_processed, "total_earnings": float(k.total_earnings_ngn or 0)} for k in keys]})

@app.route('/api/admin/keys/<int:key_id>', methods=['DELETE'])
@require_admin
def delete_key(key_id):
    ak = AccessKey.query.get_or_404(key_id)
    db.session.delete(ak)
    db.session.commit()
    return jsonify({"status": "deleted"})

@app.route('/api/admin/workers', methods=['GET'])
@require_admin
def admin_workers():
    workers = AccessKey.query.all()
    return jsonify({"workers": [{"id": w.id, "owner": w.owner_name, "last_active": w.last_active.isoformat() if w.last_active else None, "is_active": w.is_active, "is_banned": w.is_banned} for w in workers]})

@app.route('/api/admin/workers/<int:worker_id>/ban', methods=['POST'])
@require_admin
def ban_worker(worker_id):
    ak = AccessKey.query.get_or_404(worker_id)
    ak.is_banned = not ak.is_banned
    db.session.commit()
    return jsonify({"status": "success", "is_banned": ak.is_banned})

@app.route('/api/admin/leads_upload', methods=['POST'])
@require_admin
def admin_leads_upload():
    data = request.json or {}
    text_lines = data.get('leads_text', '').split('\n')
    for line in text_lines:
        cleaned = line.strip()
        if cleaned:
            # simple assumed format or just dump to website/name
            parts = cleaned.split(',')
            if len(parts) >= 2:
                l = Lead(name=parts[0].strip(), website=parts[1].strip(), status='new')
            else:
                l = Lead(website=cleaned, status='new', name='Unknown')
            db.session.add(l)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/admin/leads', methods=['GET'])
@require_admin
def admin_leads():
    leads = Lead.query.order_by(Lead.id.desc()).limit(200).all()
    return jsonify({"leads": [{"id": l.id, "name": l.name or 'N/A', "website": l.website or 'N/A', "status": l.status, "worker": l.assigned_to or '-'} for l in leads]})

@app.route('/api/admin/leads/export.csv', methods=['GET'])
@require_admin
def export_leads_csv():
    """Export all scraped leads as a downloadable CSV for admin review."""
    leads = Lead.query.order_by(Lead.id.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'name', 'phone', 'website', 'address', 'keyword_source', 'status'])
    for l in leads:
        writer.writerow([l.id, l.name or '', l.phone or '', l.website or '', l.address or '', l.keyword_source or '', l.status])
    csv_content = output.getvalue()
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=cmining_leads.csv'}
    )

@app.route('/api/admin/campaigns/<int:project_id>/upload_leads', methods=['POST'])
@require_admin
def upload_campaign_leads(project_id):
    """Upload reviewed leads (CSV text) directly into a specific campaign."""
    project = Project.query.get_or_404(project_id)
    data = request.json or {}
    text_lines = data.get('leads_text', '').split('\n')
    count = 0
    for line in text_lines:
        cleaned = line.strip()
        if not cleaned or cleaned.startswith('#'):
            continue
        parts = [p.strip() for p in cleaned.split(',')]
        lead_name = parts[0] if len(parts) > 0 else 'Unknown'
        lead_site = parts[1] if len(parts) > 1 else ''
        lead_phone = parts[2] if len(parts) > 2 else ''
        l = Lead(
            name=lead_name,
            website=lead_site,
            phone=lead_phone,
            project_id=project.id,
            status='new',
            keyword_source='admin_upload'
        )
        db.session.add(l)
        count += 1
    db.session.commit()
    return jsonify({"status": "success", "leads_imported": count})

@app.route('/api/admin/campaigns', methods=['GET'])
@require_admin
def admin_campaigns():
    projects = Project.query.order_by(Project.id.desc()).all()
    return jsonify({"projects": [{"id": p.id, "name": p.name, "start_date": p.start_date, "sequence": p.sequence_json} for p in projects]})

@app.route('/api/admin/campaigns', methods=['POST'])
@require_admin
def admin_campaigns_create():
    data = request.json or {}
    action = data.get('action')
    
    if action == 'new_keyword':
        # Handles bulk keywords via array
        kw_list = data.get('keywords', [])
        for txt in kw_list:
            if txt.strip():
                k = Keyword(keyword_text=txt.strip(), status='pending')
                db.session.add(k)
        db.session.commit()
        return jsonify({"status": "success"})
        
    if action == 'save_project':
        pid = data.get('project_id')
        seq = data.get('sequence', [])
        name = data.get('name', 'New Campaign')
        start_date = data.get('start_date', None)
        if pid:
            p = Project.query.get(pid)
            if p:
                p.name = name
                p.sequence_json = seq
                p.start_date = start_date
        else:
            p = Project(name=name, sequence_json=seq, start_date=start_date)
            db.session.add(p)
        db.session.commit()
        return jsonify({"status": "success", "project_id": p.id})

    return jsonify({"error": "Invalid action"}), 400

@app.route('/api/admin/keywords', methods=['GET'])
@require_admin
def admin_keywords():
    kws = Keyword.query.order_by(Keyword.id.desc()).limit(100).all()
    return jsonify({"keywords": [{"id": k.id, "keyword_text": k.keyword_text, "status": k.status, "result_count": k.result_count} for k in kws]})

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
