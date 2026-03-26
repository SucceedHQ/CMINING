const { app, BrowserWindow, ipcMain, Notification, net } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

let mainWindow;
let activeProcess = null;
let currentMode = null; 
let heartbeatInterval = null;
let engineInterval = null;
let statsInterval = null;
let currentKey = null;

const CONFIG_PATH = path.join(app.getPath('userData'), 'cmining_config.json');
const SETTINGS_PATH = path.join(app.getPath('userData'), 'cmining_settings.json');
const ENGINE_PATH = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.join(__dirname, '..', 'engine');
const APP_VERSION = "1.4.0";

// Load backend URL from editable settings file
function getBackendUrl() {
    if (fs.existsSync(SETTINGS_PATH)) {
        try {
            const s = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf-8'));
            if (s.backend_url) return s.backend_url.replace(/\/$/, '');
        } catch(e) {}
    }
    return process.env.BACKEND_URL || (app.isPackaged ? 'https://succeedhq.pythonanywhere.com' : 'http://localhost:5000');
}

const BACKEND_URL = getBackendUrl();

function loadConfig() {
    if (fs.existsSync(CONFIG_PATH)) {
        try { return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8')); } catch(e) { return {}; }
    }
    return {};
}

function saveConfig(config) {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config));
}

function getWATTime() {
    const nowUtc = new Date();
    const watTime = new Date(nowUtc.getTime() + (3600000)); 
    return watTime;
}

function determineMode() {
    const wat = getWATTime();
    const hour = wat.getUTCHours();
    // Scraper: 01:00-14:00 | Outreach: 14:00-01:00
    return (hour >= 1 && hour < 14) ? 'scraper' : 'outreach';
}

function requestBackend(endpoint, method = 'POST', data = null, accessKey = null) {
    return new Promise((resolve, reject) => {
        const url = new URL(endpoint, BACKEND_URL);
        const request = net.request({
            method: method,
            url: url.toString(),
            useSessionCookies: false
        });

        request.setHeader('Content-Type', 'application/json');
        if (accessKey) request.setHeader('X-Access-Key', accessKey);

        request.on('response', (response) => {
            let body = '';
            response.on('data', (chunk) => body += chunk.toString());
            response.on('end', () => {
                let parsedBody = {};
                try { parsedBody = body ? JSON.parse(body) : {}; } catch(e) {}
                
                if (response.statusCode >= 200 && response.statusCode < 300) {
                    resolve(parsedBody);
                } else {
                    const errMsg = parsedBody.error || parsedBody.message || `HTTP ${response.statusCode}`;
                    reject(errMsg);
                }
            });
        });

        request.on('error', (error) => reject(error.message));
        if (data) request.write(JSON.stringify(data));
        request.end();
    });
}

function sendToRenderer(channel, payload) {
    if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(channel, payload);
    }
}

async function updateStats(accessKey) {
    try {
        const stats = await requestBackend('/api/worker/stats', 'GET', null, accessKey);
        sendToRenderer('stats-update', stats);
    } catch(e) { console.error("Stats update failed", e); }
}

async function checkNotifications(accessKey) {
    try {
        config.seenNotifIds = seenIds;
        saveConfig(config);
    } catch(e) { console.error("Notif check failed", e); }
}

async function startEngine(mode, accessKey) {
    if (activeProcess) {
        if (currentMode === mode) return;
        activeProcess.kill();
        activeProcess = null;
    }

    currentMode = mode;
    const scriptName = mode === 'scraper' ? 'scraper.js' : 'outreach.js';
    const scriptPath = path.join(ENGINE_PATH, scriptName);
    
    sendToRenderer('engine-status', { mode, status: 'starting' });

    activeProcess = spawn('node', [scriptPath], {
        cwd: ENGINE_PATH,
        env: { ...process.env, BACKEND_URL, ACCESS_KEY: accessKey }
    });

    activeProcess.stdout.on('data', (data) => {
        const msg = data.toString().trim();
        if(msg) sendToRenderer('engine-log', msg);
    });

    activeProcess.stderr.on('data', (data) => {
        const msg = data.toString().trim();
        if(msg) sendToRenderer('engine-log', `ERROR: ${msg}`);
    });

    activeProcess.on('close', (code) => {
        sendToRenderer('engine-status', { mode: null, status: 'stopped' });
        activeProcess = null;
        currentMode = null;
    });
}

function startOrchestrator(accessKey) {
    currentKey = accessKey;
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    if (engineInterval) clearInterval(engineInterval);
    if (statsInterval) clearInterval(statsInterval);

    const tick = () => {
        requestBackend('/api/heartbeat', 'POST', {}, accessKey).catch(e => {});
        checkNotifications(accessKey);
        const newMode = determineMode();
        startEngine(newMode, accessKey);
    };

    tick();
    updateStats(accessKey);
    checkForUpdates(); // Function now defined below

    heartbeatInterval = setInterval(tick, 60000);
    statsInterval = setInterval(() => updateStats(accessKey), 300000); 
    setInterval(checkForUpdates, 3600000); 
}

async function checkForUpdates() {
    try {
        const data = await requestBackend('/api/worker/version', 'GET');
        if (data && data.version_string !== APP_VERSION) {
            sendToRenderer('update-available', {
                version: data.version_string,
                url: data.download_url,
                changelog: data.changelog,
                force: data.is_force_update
            });
        }
    } catch(e) { console.error("Update check failed", e); }
}

function stopOrchestrator() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    if (engineInterval) clearInterval(engineInterval);
    if (statsInterval) clearInterval(statsInterval);
    if (activeProcess) activeProcess.kill();
    activeProcess = null;
    currentMode = null;
    currentKey = null;
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1100,
        height: 800,
        backgroundColor: '#030712',
        title: "CMining Worker Node",
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        }
    });

    mainWindow.loadFile('index.html');
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
    stopOrchestrator();
    if (process.platform !== 'darwin') app.quit();
});

// --- IPC Handlers ---

ipcMain.handle('validate-key', async (event, key) => {
    try {
        const res = await requestBackend('/api/validate', 'POST', { access_key: key });
        const config = loadConfig();
        config.accessKey = key;
        saveConfig(config);
        startOrchestrator(key);
        return { success: true, owner: res.owner };
    } catch (error) {
        return { success: false, error: "Validation failed: " + error };
    }
});

ipcMain.handle('request-key', async (event, data) => {
    try {
        await requestBackend('/api/keys/request', 'POST', { email: data.email });
        return { success: true };
    } catch (e) { return { success: false, error: e }; }
});

ipcMain.handle('submit-bug', async (event, data) => {
    if (!currentKey) return { success: false, error: "Not logged in" };
    try {
        await requestBackend('/api/bugs/report', 'POST', { category: 'Technical', title: data.title, description: data.desc }, currentKey);
        return { success: true };
    } catch (e) { return { success: false, error: e }; }
});

ipcMain.handle('request-withdrawal', async (event, data) => {
    if (!currentKey) return { success: false, error: "Not logged in" };
    try {
        await requestBackend('/api/withdrawals/request', 'POST', { 
            bank: data.bank, 
            account: data.account, 
            name: data.name, 
            amount: data.amount 
        }, currentKey);
        return { success: true };
    } catch (e) { return { success: false, error: e }; }
});

ipcMain.handle('get-notifications', async () => {
    if (!currentKey) return { success: false, error: "Not logged in" };
    try {
        const notifs = await requestBackend('/api/notifications/active', 'GET', {}, currentKey);
        return { success: true, notifications: notifs };
    } catch (e) { return { success: false, error: e }; }
});

ipcMain.handle('stop-engine', () => {
    if (activeProcess) activeProcess.kill();
    return true;
});

ipcMain.handle('get-config', loadConfig);
ipcMain.handle('logout', () => {
    stopOrchestrator();
    const config = loadConfig();
    delete config.accessKey;
    saveConfig(config);
    return true;
});
