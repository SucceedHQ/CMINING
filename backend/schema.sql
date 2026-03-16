-- CMining Supabase Schema Definition

-- Enable missing extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. access_keys
CREATE TABLE public.access_keys (
    id SERIAL PRIMARY KEY,
    key_value TEXT UNIQUE NOT NULL,
    owner_name TEXT NOT NULL,
    wallet_address TEXT,
    bank_name TEXT,
    account_number TEXT,
    account_name TEXT,
    total_leads_processed INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    total_earnings_ngn NUMERIC DEFAULT 0,
    withdrawn_ngn NUMERIC DEFAULT 0,
    last_active TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,
    is_banned BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. keywords
CREATE TABLE public.keywords (
    id SERIAL PRIMARY KEY,
    keyword_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, assigned, done
    assigned_to INTEGER REFERENCES public.access_keys(id),
    assigned_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    result_count INTEGER DEFAULT 0
);

-- 3. leads
CREATE TABLE public.leads (
    id SERIAL PRIMARY KEY,
    name TEXT,
    phone TEXT,
    website TEXT,
    address TEXT,
    keyword_source TEXT,
    status TEXT DEFAULT 'new', -- new, assigned, contacted, success, failed
    assigned_to INTEGER REFERENCES public.access_keys(id),
    assigned_at TIMESTAMP WITH TIME ZONE,
    last_attempt_at TIMESTAMP WITH TIME ZONE,
    attempt_count INTEGER DEFAULT 0,
    sequence_step INTEGER DEFAULT 1,
    project_id INTEGER, -- FK to projects
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 4. projects (Outreach Campaigns)
CREATE TABLE public.projects (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    sequence_length INTEGER DEFAULT 1,
    messages JSONB NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_by_admin BOOLEAN DEFAULT true
);

-- Foreign Key for leads -> projects
ALTER TABLE public.leads ADD CONSTRAINT fk_leads_project FOREIGN KEY (project_id) REFERENCES public.projects(id);

-- 5. earnings_log
CREATE TABLE public.earnings_log (
    id SERIAL PRIMARY KEY,
    access_key_id INTEGER REFERENCES public.access_keys(id) NOT NULL,
    type TEXT NOT NULL, -- keyword_batch, lead_batch
    amount_ngn NUMERIC NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 6. withdrawals
CREATE TABLE public.withdrawals (
    id SERIAL PRIMARY KEY,
    access_key_id INTEGER REFERENCES public.access_keys(id) NOT NULL,
    amount_ngn NUMERIC NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, approved, rejected
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    admin_note TEXT
);

-- 7. notifications
CREATE TABLE public.notifications (
    id SERIAL PRIMARY KEY,
    target TEXT DEFAULT 'all', -- 'all' or specific key_value
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    is_read BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 8. bug_reports
CREATE TABLE public.bug_reports (
    id SERIAL PRIMARY KEY,
    access_key_id INTEGER REFERENCES public.access_keys(id) NOT NULL,
    category TEXT NOT NULL, -- bug, suggestion, other
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    screenshot_url TEXT,
    status TEXT DEFAULT 'open', -- open, in_review, resolved
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 9. app_versions
CREATE TABLE public.app_versions (
    id SERIAL PRIMARY KEY,
    version_string TEXT NOT NULL,
    min_required_version TEXT,
    download_url TEXT,
    changelog TEXT,
    is_obsolete BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 10. Global Settings (for signup_open, global earnings rates, etc.)
CREATE TABLE public.global_settings (
    id TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

-- RPC Function: claim_keyword_batch
CREATE OR REPLACE FUNCTION claim_keyword_batch(worker_id INTEGER, batch_size INTEGER)
RETURNS SETOF public.keywords
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.keywords
    SET status = 'assigned', assigned_to = worker_id, assigned_at = NOW()
    WHERE id IN (
        SELECT id FROM public.keywords
        WHERE status = 'pending'
        ORDER BY id ASC
        LIMIT batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$;


-- RPC Function: claim_lead_batch
CREATE OR REPLACE FUNCTION claim_lead_batch(worker_id INTEGER, batch_size INTEGER)
RETURNS SETOF public.leads
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.leads
    SET status = 'assigned', assigned_to = worker_id, assigned_at = NOW()
    WHERE id IN (
        SELECT id FROM public.leads
        WHERE status = 'new'
        ORDER BY id ASC
        LIMIT batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$;

-- RLS Policies (Workers only communicate via Flask, Admin dashboard might use Supabase direct or via Flask. 
-- For safety, since the thick Flask wrapper handles auth via X-Access-Key, we can leave RLS minimal or restrict to service role if admin UI uses service role)

-- By default, block all access from anonymous
ALTER TABLE public.access_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keywords ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.earnings_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.withdrawals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bug_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.global_settings ENABLE ROW LEVEL SECURITY;

-- If we connect from Flask using service_role key, it bypasses RLS.
-- Therefore, we don't strictly need complex policies here unless the web dashboard does direct anon/authenticated queries.
-- Assuming Admin Dashboard uses direct Supabase client with admin auth:
-- Setup would require a standard policy allowing authenticated users.
