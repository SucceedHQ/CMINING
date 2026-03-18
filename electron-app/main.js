const { app, BrowserWindow, ipcMain, Notification, net } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const https = require('https'); // Added for cloud server support

let mainWindow;
let activeProcess = null;
let currentMode = null; // 'scraper' or 'outreach'
let heartbeatInterval = null;
let engineInterval = null;

const CONFIG_PATH = path.join(app.getPath('userData'), 'cmining_config.json');
const SETTINGS_PATH = path.join(app.getPath('userData'), 'cmining_settings.json');
const ENGINE_PATH = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.join(__dirname, '..', 'engine');

// Load backend URL from editable settings file (so workers can point to any server)
function getBackendUrl() {
    if (fs.existsSync(SETTINGS_PATH)) {
        try {
            const s = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf-8'));
            if (s.backend_url) return s.backend_url.replace(/\/$/, '');
        } catch(e) {}
    }
    return process.env.BACKEND_URL || 'https://succeedhq.pythonanywhere.com';
}

const BACKEND_URL = getBackendUrl();

function loadConfig() {
    if (fs.existsSync(CONFIG_PATH)) {
        return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
    }
    return {};
}

function saveConfig(config) {
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config));
}

function getWATTime() {
    // WAT is UTC+1
    const nowUtc = new Date();
    const watTime = new Date(nowUtc.getTime() + (3600000)); 
    return watTime;
}

function determineMode() {
    const wat = getWATTime();
    const hour = wat.getUTCHours();
    
    // 01:00 to 14:00 WAT -> Scraper
    // 14:00 to 01:00 WAT -> Outreach
    if (hour >= 1 && hour < 14) {
        return 'scraper';
    } else {
        return 'outreach';
    }
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
        if (accessKey) {
            request.setHeader('X-Access-Key', accessKey);
        }

        request.on('response', (response) => {
            let body = '';
            response.on('data', (chunk) => {
                body += chunk.toString();
            });
            response.on('end', () => {
                if (response.statusCode >= 200 && response.statusCode < 300) {
                    try { resolve(body ? JSON.parse(body) : {}); }
                    catch(e) { resolve(body); }
                } else {
                    reject(`SERVER_ERROR: HTTP ${response.statusCode}`);
                }
            });
        });

        request.on('error', (error) => {
            console.error("Net Request Error:", error);
            reject(`CONNECTION_FAILED: Native networking blocked or DNS invalid (${error.message})`);
        });

        if (data) request.write(JSON.stringify(data));
        request.end();
    });
}

async function startEngine(mode, accessKey) {
    if (activeProcess) {
        if (currentMode === mode) return; // Already running correct mode
        console.log(`Switching mode from ${currentMode} to ${mode}...`);
        activeProcess.kill();
        activeProcess = null;
    }

    currentMode = mode;
    const scriptName = mode === 'scraper' ? 'scraper.js' : 'outreach.js';
    const scriptPath = path.join(ENGINE_PATH, scriptName);
    
    console.log(`Starting ${scriptName}...`);
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
        sendToRenderer('engine-log', `Process exited with code ${code}`);
        sendToRenderer('engine-status', { mode: null, status: 'stopped' });
        activeProcess = null;
        currentMode = null;
    });
}

function sendToRenderer(channel, payload) {
    if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(channel, payload);
    }
}

async function runHeartbeat(accessKey) {
    try {
        await requestBackend('/api/heartbeat', 'POST', {}, accessKey);
        // We could also poll notifications here if Supabase Realtime isn't configured
    } catch (e) {
        console.error("Heartbeat failed", e);
    }
}

function startOrchestrator(accessKey) {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    if (engineInterval) clearInterval(engineInterval);

    // Initial checks
    runHeartbeat(accessKey);
    const mode = determineMode();
    startEngine(mode, accessKey);

    heartbeatInterval = setInterval(() => runHeartbeat(accessKey), 60000);
    
    engineInterval = setInterval(() => {
        const newMode = determineMode();
        startEngine(newMode, accessKey);
    }, 60000);
}

function stopOrchestrator() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    if (engineInterval) clearInterval(engineInterval);
    if (activeProcess) activeProcess.kill();
    activeProcess = null;
    currentMode = null;
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1000,
        height: 700,
        backgroundColor: '#111827',
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        }
    });

    mainWindow.loadFile('index.html');
}

app.whenReady().then(() => {
    createWindow();

    app.on('activate', function () {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', function () {
    stopOrchestrator();
    if (process.platform !== 'darwin') app.quit();
});

// --- IPC Listeners ---

ipcMain.handle('validate-key', async (event, key) => {
    // First check backend is reachable
    try {
        await requestBackend('/api/version/check', 'GET', null, null);
    } catch(e) {
        return { success: false, error: `CONNECTION ERROR: ${e}. (URL: ${BACKEND_URL})` };
    }

    try {
        const res = await requestBackend('/api/validate', 'POST', { access_key: key });
        
        const config = loadConfig();
        config.accessKey = key;
        saveConfig(config);
        
        startOrchestrator(key);
        
        return { success: true, owner: res.owner };
    } catch (error) {
        const msg = typeof error === 'string' ? error : error.message || 'Invalid access key or server error.';
        return { success: false, error: `AUTH ERROR (${BACKEND_URL}): ${msg}` };
    }
});

ipcMain.handle('get-config', () => {
    return loadConfig();
});

ipcMain.handle('get-backend-url', () => {
    return BACKEND_URL;
});

ipcMain.handle('logout', () => {
    stopOrchestrator();
    saveConfig({});
    return true;
});

// Notifications
ipcMain.on('show-notification', (event, { title, body }) => {
    new Notification({ title, body }).show();
});
