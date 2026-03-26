const { chromium } = require('playwright');
const { parse } = require('node-html-parser');

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';
const ACCESS_KEY = process.env.ACCESS_KEY || 'DEV_TEST_KEY';

const SENDER_NAME = "Sophia Biden";
const SENDER_EMAIL = "sophia.biden@hexagon-construction.com";
const SENDER_PHONE = "+19016973940";
const SENDER_COMPANY = "Hexagon Construction";
const SENDER_SUBJECT = "Follow up message";
const SENDER_MESSAGE = "Hi [BUSINESS_NAME], we are trying to get in touch regarding a recent inquiry, please email us back. Thanks.";

let isShuttingDown = false;
process.on('SIGINT', () => {
    console.log('\n[~] Received SIGINT. Wait for current lead batch to finish before exiting...');
    isShuttingDown = true;
});
process.on('SIGTERM', () => {
    console.log('\n[~] Received SIGTERM. Wait for current lead batch to finish before exiting...');
    isShuttingDown = true;
});

const FIELD_MAPPINGS = {
    'fname': ['first-name', 'firstname', 'first_name', 'given-name', 'givenname', 'f_name'],
    'lname': ['last-name', 'lastname', 'last_name', 'surname', 'family-name', 'familyname', 'l_name'],
    'name': ['name', 'fullname', 'full-name', 'full_name', 'your-name', 'yourname', 'contact_person', 'your_name', 'author', 'sender', 'sender-name', 'contactname', 'contact-name', 'username', 'clientname', 'client-name', 'customer-name', 'field-name', 'input-name'],
    'email': ['email', 'mail', 'e-mail', 'your-email', 'youremail', 'email_address', 'email-address', 'emailaddress', 'your_email', 'e_mail', 'from', 'reply-to', 'replyto', 'reply_to', 'sender-email', 'contact-email', 'field-email', 'input-email', 'useremail', 'user-email'],
    'phone': ['phone', 'tel', 'mobile', 'cell', 'number', 'phone_number', 'phone-number', 'contact_number', 'contact-number', 'whatsapp', 'telephone', 'phonenumber', 'phone-no', 'mob', 'cellphone', 'field-phone', 'input-phone'],
    'company': ['company', 'business', 'organization', 'organisation', 'firm', 'corp', 'office', 'workplace', 'field-company', 'input-company'],
    'message': ['message', 'comment', 'comments', 'enquiry', 'inquiry', 'body', 'details', 'note', 'notes', 'description', 'content', 'text', 'msg', 'more-info', 'more_info', 'project-details', 'your-message', 'yourmessage', 'field-message', 'input-message', 'textarea', 'question', 'feedback', 'howcanwehelp', 'how-can-we-help'],
    'subject': ['subject', 'topic', 'regarding', 're', 'title', 'subject-line', 'reason', 'purpose', 'field-subject', 'input-subject', 'inquiry_type', 'interest', 'nature-of-enquiry'],
    'address': ['address', 'location', 'mailing', 'addr'],
    'consent': ['consent', 'agree', 'privacy', 'terms', 'conditions', 'accept', 'gdpr', 'policy', 'acknowledge']
};

const STATUS_SUCCESS_VERIFIED = "SUCCESS_VERIFIED";
const STATUS_SUCCESS_UNCERTAIN = "SUCCESS_UNCERTAIN";
const STATUS_FLAGGED_AS_SPAM = "FLAGGED_AS_SPAM";
const STATUS_BLOCKED_CLOUDFLARE = "BLOCKED_BY_CLOUDFLARE";
const STATUS_NO_FORM = "NOT_FOUND";
const STATUS_JS_FORM = "SKIPPED_JS_FORM";
const STATUS_FAILED = "FAILED_HTTP";
const STATUS_ERROR = "ERROR_SUBMITTING";
const STATUS_BROWSER_SUCCESS = "SUCCESS_BROWSER";
const STATUS_BROWSER_FAILED = "FAILED_BROWSER";

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function fetchWithTimeout(resource, options = {}) {
    // Basic fetch with hard AbortController timeout
    const { timeout = 8000 } = options;
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    const response = await fetch(resource, {
        ...options,
        signal: controller.signal,
        headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            ...options.headers
        }
    });
    clearTimeout(id);
    return response;
}

function normalizeUrl(url) {
    if(!url) return null;
    let u = url.trim();
    if (!u.startsWith('http')) u = 'https://' + u;
    return u.replace(/\/$/, "");
}

async function findContactPage(targetDomain) {
    const base = normalizeUrl(targetDomain);
    if (!base) return null;
    
    const paths = ["/contact", "/contact-us", "/contact/"];
    for (const p of paths) {
        try {
            const t = base + p;
            const res = await fetchWithTimeout(t, { timeout: 5000 });
            if (res.ok) {
                const text = await res.text();
                if (text.toLowerCase().includes('<form') && (text.toLowerCase().includes('email') || text.toLowerCase().includes('message'))) {
                    return { url: t, html: text };
                }
            }
        } catch(e) {}
    }
    
    // Fallback to homepage
    try {
        const res = await fetchWithTimeout(base, { timeout: 8000 });
        if (res.ok) {
            const text = await res.text();
            if (text.toLowerCase().includes('<form')) return { url: base, html: text };
        }
    } catch(e) {}
    return null;
}

function analyzeForm(formHtml, pageUrl, config = {}) {
    const root = parse(formHtml);
    // Find inputs
    const inputs = root.querySelectorAll('input, textarea, select');
    const payload = {};
    const method = (root.getAttribute('method') || 'post').toLowerCase();
    const action = root.getAttribute('action') || '';
    
    let isJsOnly = !action || action === '#' || action.startsWith('javascript:');
    
    let actionUrl = pageUrl;
    if (action && action !== '#' && !action.startsWith('javascript:')) {
        try {
            actionUrl = new URL(action, pageUrl).href;
        } catch(e) {}
    }

    // Map Advanced config variables or fallback to defaults
    const fName = config.firstName || SENDER_NAME.split(' ')[0] || 'Sophia';
    const lName = config.lastName || SENDER_NAME.split(' ').slice(1).join(' ') || 'Biden';
    const fullName = `${fName} ${lName}`.trim();
    const address = config.address || '123 Main St';
    const city = config.city || 'Anytown';
    const state = config.state || 'NY';
    const zip = config.zip || '10001';
    const email = config.email || SENDER_EMAIL;
    const phone = config.phone || SENDER_PHONE;
    const subject = config.subject || SENDER_SUBJECT;
    const message = config.message || SENDER_MESSAGE;

    for (const field of inputs) {
        const type = (field.getAttribute('type') || 'text').toLowerCase();
        const name = field.getAttribute('name');
        if (!name) continue;
        if (['submit', 'button', 'image', 'reset'].includes(type)) continue;
        
        if (type === 'hidden') {
            payload[name] = field.getAttribute('value') || '';
            continue;
        }
        
        const id = field.getAttribute('id') || '';
        const placeholder = field.getAttribute('placeholder') || '';
        const cls = field.getAttribute('class') || '';
        const identifier = `${name} ${id} ${placeholder} ${cls}`.toLowerCase();
        
        let mapped = false;
        for (const [key, keywords] of Object.entries(FIELD_MAPPINGS)) {
            if (keywords.some(kw => identifier.includes(kw))) {
                if(key === 'fname') payload[name] = fName;
                else if(key === 'lname') payload[name] = lName;
                else if(key === 'name') payload[name] = fullName;
                else if(key === 'email') payload[name] = email;
                else if(key === 'phone') payload[name] = phone;
                else if(key === 'company') payload[name] = SENDER_COMPANY;
                else if(key === 'subject') payload[name] = subject;
                else if(key === 'message') payload[name] = message;
                else if(key === 'address') payload[name] = address;
                else if(key === 'consent') payload[name] = "yes";
                mapped = true; break;
            }
        }
        
        // Fallback for unidentified textareas
        if(!mapped && field.tagName.toLowerCase() === 'textarea') {
            payload[name] = message;
            mapped = true;
        }
        
        if(!mapped && field.hasAttribute('required')) {
            payload[name] = "N/A";
        }
    }
    
    let hasData = Object.keys(payload).length > 0;
    if(!hasData) isJsOnly = true;

    return { payload, actionUrl, method, isJsOnly };
}

async function submitHttpForm(contactPage, businessName, config = {}) {
    const root = parse(contactPage.html);
    const forms = root.querySelectorAll('form');
    let bestForm = forms[0]; // simplistic selection logic for direct port limit
    if (!bestForm) return STATUS_NO_FORM;
    
    const { payload, actionUrl, method, isJsOnly } = analyzeForm(bestForm.outerHTML, contactPage.url, config);
    if(isJsOnly) return STATUS_JS_FORM;
    
    // Replace placeholders in mapped payload
    for (let key in payload) {
        if (typeof payload[key] === 'string') {
            payload[key] = payload[key].replace(/\[BUSINESS_NAME\]/g, businessName);
        }
    }
    
    const params = new URLSearchParams();
    for(const [k, v] of Object.entries(payload)) {
        params.append(k, v);
    }
    
    try {
        let res;
        if (method === 'post') {
            res = await fetchWithTimeout(actionUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: params.toString()
            });
        } else {
            res = await fetchWithTimeout(`${actionUrl}?${params.toString()}`);
        }
        
        const textLower = (await res.text()).toLowerCase();
        
        if (textLower.includes('cdn-cgi/challenge-platform') || textLower.includes('turnstile')) {
            return STATUS_BLOCKED_CLOUDFLARE;
        }
        if (textLower.includes('bot detected') || textLower.includes('forbidden') || textLower.includes('access denied')) {
            return STATUS_FLAGGED_AS_SPAM;
        }
        
        const successPhrases = ["thank you", "thanks", "success", "received", "sent", "submitted", "we'll be in touch"];
        if (successPhrases.some(p => textLower.includes(p))) {
            return STATUS_SUCCESS_VERIFIED;
        }
        
        if (res.ok) return STATUS_SUCCESS_UNCERTAIN;
        return `${STATUS_FAILED}_${res.status}`;
        
    } catch(e) {
        return `${STATUS_ERROR}: ${e.message}`;
    }
}

async function submitPlaywrightForm(url, businessName, config = {}) {
    console.log(`[+] Launching Playwright fallback for ${businessName}...`);
    const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
    const context = await browser.newContext();
    const page = await context.newPage();
    
    try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
        await page.waitForTimeout(2000); // let forms load
        
        // Find forms
        const formLocator = page.locator('form').first();
        if(await formLocator.count() === 0) {
            return STATUS_BROWSER_FAILED + ": No Form";
        }
        
        // Fill basic mapped fields sequentially
        const inputs = await page.locator('input, textarea').all();
        let filledAny = false;
        
        const fName = config.firstName || SENDER_NAME.split(' ')[0] || 'Alexander';
        const lName = config.lastName || SENDER_NAME.split(' ').slice(1).join(' ') || 'Webb';
        const fullName = `${fName} ${lName}`.trim();
        const address = config.address || '123 Main St';
        const city = config.city || 'Anytown';
        const state = config.state || 'NY';
        const zip = config.zip || '10001';
        const email = config.email || SENDER_EMAIL;
        const phone = config.phone || SENDER_PHONE;
        const subject = config.subject || SENDER_SUBJECT;
        const message = config.message || SENDER_MESSAGE;
        
        for (const input of inputs) {
            if (!(await input.isVisible())) continue;
            
            const name = (await input.getAttribute('name') || '').toLowerCase();
            const id = (await input.getAttribute('id') || '').toLowerCase();
            const type = (await input.getAttribute('type') || '').toLowerCase();
            const ph = (await input.getAttribute('placeholder') || '').toLowerCase();
            const identifier = `${name} ${id} ${ph} ${type}`;
            
            if (['hidden','submit','button','checkbox','radio'].includes(type)) continue;
            
            let val = "";
            if (identifier.includes('first') && identifier.includes('name')) val = fName;
            else if (identifier.includes('last') && identifier.includes('name')) val = lName;
            else if (identifier.includes('name') || identifier.includes('contact')) val = fullName;
            else if (identifier.includes('email') || identifier.includes('mail')) val = email;
            else if (identifier.includes('phone') || identifier.includes('tel')) val = phone;
            else if (identifier.includes('address') || identifier.includes('street')) val = address;
            else if (identifier.includes('city') || identifier.includes('town')) val = city;
            else if (identifier.includes('state') || identifier.includes('region')) val = state;
            else if (identifier.includes('zip') || identifier.includes('postal')) val = zip;
            else if (identifier.includes('subject') || identifier.includes('topic')) val = subject;
            else if (identifier.includes('message') || identifier.includes('comment') || await input.evaluate(el => el.tagName.toLowerCase() === 'textarea')) val = message;
            else if (await input.getAttribute('required')) val = "N/A";
            
            if (val !== "") {
                val = val.replace(/\[BUSINESS_NAME\]/g, businessName);
                await input.fill(val);
                filledAny = true;
                await page.waitForTimeout(100);
            }
        }
        
        if(!filledAny) return STATUS_BROWSER_FAILED + ": No recognizable fields";
        
        // Click submit
        const submitBtn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Send"), button:has-text("Submit")').first();
        if (await submitBtn.count() > 0) {
            await submitBtn.click({ timeout: 5000 });
        } else {
            // Hitting enter on last input
            await inputs[inputs.length-1].press('Enter');
        }
        
        // Wait for response/navigation
        await page.waitForTimeout(5000);
        const html = await page.content();
        const htmlLower = html.toLowerCase();
        
        const successPhrases = ["thank you", "thanks", "success", "received", "sent", "submitted", "we'll be in touch"];
        if (successPhrases.some(p => htmlLower.includes(p))) {
            return STATUS_BROWSER_SUCCESS;
        }
        
        return STATUS_BROWSER_FAILED + ": No success confirmation detected in fallback";
    } catch(e) {
         return `${STATUS_BROWSER_FAILED}: ${e.message}`;
    } finally {
        await browser.close();
    }
}

async function processLead(lead) {
    const bizName = lead.name || 'Business';
    const domain = lead.website;
    
    if(!domain) return { lead_id: lead.id, status: STATUS_NO_FORM, log: "No website" };
    
    // Check JUNK
    for (const pattern of JUNK_DOMAINS) {
        if(domain.toLowerCase().includes(pattern)) return { lead_id: lead.id, status: "SKIPPED_JUNK", log: `Matches junk domain ${pattern}` };
    }
    
    console.log(`[~] Processing Lead: ${bizName} - ${domain}`);
    
    const contactPage = await findContactPage(domain);
    if (!contactPage) {
        return { lead_id: lead.id, status: STATUS_NO_FORM, log: "Contact page not found" };
    }
    
    let status = await submitHttpForm(contactPage, bizName, lead.config || {});
    
    if (status === STATUS_JS_FORM || status.startsWith(STATUS_FAILED) || status.startsWith(STATUS_ERROR) || status.startsWith(STATUS_BLOCKED_CLOUDFLARE)) {
        status = await submitPlaywrightForm(contactPage.url, bizName, lead.config || {});
    }
    
    return { lead_id: lead.id, status: status, log: "Processed completely." };
}

async function getBatch() {
    try {
        const res = await fetch(`${BACKEND_URL}/api/batch/leads`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Access-Key': ACCESS_KEY },
            body: JSON.stringify({ batch_size: 5 }) // 5 leads per worker
        });
        if (res.ok) {
            const data = await res.json();
            return data.leads || [];
        } else {
            console.error(`Backend error: ${res.status}`);
            return [];
        }
    } catch (e) {
        console.error("Connection to backend failed", e.message);
        return [];
    }
}

async function reportBatch(results) {
    try {
        await fetch(`${BACKEND_URL}/api/batch/report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Access-Key': ACCESS_KEY },
            body: JSON.stringify({ results })
        });
        console.log(`[✓] Reported batch of ${results.length} leads to backend.`);
    } catch (e) {
        console.error("Failed to report results", e.message);
    }
}

async function startEngine() {
    console.log(`🚀 Initializing CMining GPU Compute Engine... connected to ${BACKEND_URL}`);
    
    while (!isShuttingDown) {
        const leads = await getBatch();
        
        if (!leads || leads.length === 0) {
            console.log("Waiting for block assignment. Hash rate stable...");
            await sleep(30000);
            continue;
        }
        
        console.log(`[⬇] Fetched batch of ${leads.length} leads.`);
        const results = [];
        for (const idx in leads) {
             const resultPayload = await processLead(leads[idx]);
             results.push(resultPayload);
        }
        
        await reportBatch(results);
    }
    console.log('[~] CMining Engine shutdown complete.');
    process.exit(0);
}

// Start sequence
startEngine().catch(e => console.error(e));
