'use strict';

const { chromium } = require('playwright');

// ── CONFIG ────────────────────────────────────────────────────
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';
const ACCESS_KEY = process.env.ACCESS_KEY || 'DEV_TEST_KEY';

const HEADLESS = true;
const WORKERS = 5;      // ← safe sweet spot for Google Maps
const SCROLL_ROUNDS = 25;
const SCROLL_PAUSE = 1500;   // ms between scrolls
const DETAIL_TIMEOUT = 20000; // max ms to load a single place page
const NAV_TIMEOUT = 40000;  // collector nav timeout
const STAGGER_MS = 800;    // delay between spawning each worker
const MIN_DELAY = 600;    // min random delay between requests per worker
const MAX_DELAY = 1400;   // max random delay between requests per worker
// ─────────────────────────────────────────────────────────────

if (!process.env.ACCESS_KEY) {
    console.warn("WARNING: ACCESS_KEY not set in env. Defaulting to DEV_TEST_KEY");
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const randDelay = () => sleep(MIN_DELAY + Math.random() * (MAX_DELAY - MIN_DELAY));

function cleanText(t) {
    if (!t) return '';
    return t.replace(/[\uE000-\uF8FF]/g, '').replace(/\n\s*\n/g, '\n').trim();
}

async function dismissPopups(page) {
    for (const sel of [
        'button[aria-label="Accept all"]',
        'form:nth-child(2) button',
        'button:has-text("No thanks")',
        'button[aria-label="No thanks"]',
    ]) {
        try {
            const btn = page.locator(sel).first();
            if (await btn.isVisible({ timeout: 1500 })) { await btn.click(); await sleep(600); }
        } catch { /* no popup */ }
    }
}

// ── COLLECTOR: scroll a keyword and return all place URLs ─────
async function collectCardUrls(page, keyword) {
    const url = `https://www.google.com/maps/search/${encodeURIComponent(keyword)}`;
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
    await dismissPopups(page);

    try {
        await page.waitForSelector('div[role="feed"]', { timeout: 12000 });
    } catch { return []; }

    for (let s = 0; s < SCROLL_ROUNDS; s++) {
        await page.evaluate(() => {
            const f = document.querySelector('div[role="feed"]');
            if (f) f.scrollTop = f.scrollHeight;
        });
        await sleep(SCROLL_PAUSE);
        const ended = await page.locator('text="You\'ve reached the end of the list."')
            .isVisible().catch(() => false);
        if (ended) break;
    }

    return page.$$eval('a[href*="/maps/place/"]', els =>
        [...new Set(els.map(el => {
            const m = (el.href || '').match(/https:\/\/www\.google\.com\/maps\/place\/[^?]+/);
            return m ? m[0] : null;
        }).filter(Boolean))]
    );
}

// ── WORKER: visit one place URL and return extracted details ──
async function scrapeCard(page, cardUrl, keyword) {
    await page.goto(cardUrl, { waitUntil: 'domcontentloaded', timeout: DETAIL_TIMEOUT });
    await sleep(1000); // short settle

    return page.evaluate(kw => {
        const nameEl =
            document.querySelector('h1.DUwDvf') ||
            document.querySelector('h1[class*="fontHeadlineLarge"]') ||
            document.querySelector('h1');
        const name = nameEl?.innerText?.trim() || '';

        const phoneEl = document.querySelector('[data-item-id^="phone:tel:"]');
        let phone = '';
        if (phoneEl) {
            const al = phoneEl.getAttribute('aria-label') || '';
            phone = al.replace(/^Phone:\s*/i, '').trim()
                || (phoneEl.getAttribute('data-item-id') || '').replace('phone:tel:', '');
        }

        const website = document.querySelector('[data-item-id="authority"]')?.innerText?.trim() || '';
        const address = document.querySelector('[data-item-id="address"]')?.innerText?.trim() || '';

        return { name, phone, website, address, keyword: kw };
    }, keyword);
}

// ── Worker runner: pulls from shared queue until empty ────────
async function runWorker(id, ctx, queue, resultsArray, seen) {
    const page = await ctx.newPage();
    // Block images/fonts for speed in headless (less bandwidth)
    await page.route('**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,otf}', r => r.abort());

    // Stagger: worker N waits N * STAGGER_MS before starting
    await sleep(id * STAGGER_MS);

    try {
        while (true) {
            const item = queue.shift();
            if (!item) break;

            try {
                const d = await scrapeCard(page, item.url, item.keyword);
                if (!d.name) continue;
                
                const key = `${d.name}|${d.phone}`;
                if (!seen.has(key)) {
                    seen.add(key);
                    resultsArray.push({
                        name: cleanText(d.name),
                        phone: cleanText(d.phone),
                        website: cleanText(d.website),
                        address: cleanText(d.address).replace(/\n/g, ', '),
                        keyword_source: d.keyword,
                    });
                }
            } catch {}

            await randDelay(); // polite pause between requests
        }
    } finally {
        await page.close();
    }
}

// ── API Communicators ─────────────────────────────────────────

async function getKeywordBatch() {
    try {
        const res = await fetch(`${BACKEND_URL}/api/batch/keywords`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Access-Key': ACCESS_KEY },
            body: JSON.stringify({ batch_size: 1 }) // 1 keyword is usually plenty of cards
        });
        if (res.ok) {
            const data = await res.json();
            return data.keywords || [];
        } else {
            console.error(`Backend error fetching keywords: ${res.status}`);
            return [];
        }
    } catch (e) {
        console.error("Connection to backend failed", e.message);
        return [];
    }
}

async function reportResults(results, keywordIds) {
    try {
        await fetch(`${BACKEND_URL}/api/batch/results`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Access-Key': ACCESS_KEY },
            body: JSON.stringify({ results, completed_keyword_ids: keywordIds })
        });
        console.log(`[✓] Reported ${results.length} scraped leads to backend.`);
    } catch (e) {
        console.error("Failed to report results", e.message);
    }
}

// ── MAIN ENGINE ───────────────────────────────────────────────
async function startScraperEngine() {
    console.log('\n🚀 Starting CMining Node.js Scraper Engine...');
    console.log(`🔗 Connected to: ${BACKEND_URL}`);
    
    // Launch browser once for the session
    const browser = await chromium.launch({
        headless: HEADLESS,
        args: [
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--disable-setuid-sandbox',
        ]
    });

    const ctxOpts = {
        viewport: { width: 1280, height: 900 },
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        locale: 'en-US',
    };

    const collectorCtx = await browser.newContext(ctxOpts);
    await collectorCtx.addInitScript(() => Object.defineProperty(navigator, 'webdriver', { get: () => false }));
    const collectorPage = await collectorCtx.newPage();

    const workerCtx = await browser.newContext(ctxOpts);
    await workerCtx.addInitScript(() => Object.defineProperty(navigator, 'webdriver', { get: () => false }));

    while (true) {
        const keywords = await getKeywordBatch();
        if (!keywords || keywords.length === 0) {
            console.log("No pending keywords available. Sleeping for 30s...");
            await sleep(30000);
            continue;
        }

        const keywordTask = keywords[0]; // Process one at a time from batch
        console.log(`\n[⬇] Claimed keyword: "${keywordTask.keyword_text}"`);

        let cardUrls = [];
        try {
            cardUrls = await collectCardUrls(collectorPage, keywordTask.keyword_text);
        } catch (e) {
            console.error(`\n⚠️ [${keywordTask.keyword_text}] collect failed: ${e.message}`);
            // Return failure to backend? Wait, just mark it as done with 0 results
        }

        if (!cardUrls.length) {
            console.log(`⚠️ No results found for: "${keywordTask.keyword_text}"`);
            await reportResults([], [keywordTask.id]);
            continue;
        }

        console.log(`[▶] Found ${cardUrls.length} cards. Extracting details with ${WORKERS} workers...`);

        const queue = cardUrls.map(url => ({ url, keyword: keywordTask.keyword_text }));
        const workerCount = Math.min(WORKERS, cardUrls.length);
        const resultsArray = [];
        const seenLeads = new Set(); // ensure purity inside the batch

        await Promise.all(
            Array.from({ length: workerCount }, (_, id) =>
                runWorker(id, workerCtx, queue, resultsArray, seenLeads)
            )
        );

        console.log(`[✔] Scraped ${resultsArray.length} valid profiles for "${keywordTask.keyword_text}".`);
        await reportResults(resultsArray, [keywordTask.id]);
    }

    // Unreachable in infinite loop, but good practice
    await browser.close();
}

startScraperEngine().catch(e => {
    console.error('\n❌ Fatal:', e.message);
    process.exit(1);
});
