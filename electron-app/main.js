const { app, BrowserWindow, ipcMain, Notification } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http'); // For making api requests

let mainWindow;
let activeProcess = null;
let currentMode = null; // 'scraper' or 'outreach'
let heartbeatInterval = null;
let engineInterval = null;

const CONFIG_PATH = path.join(app.getPath('userData'), 'cmining_config.json');
const ENGINE_PATH = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.join(__dirname, '..', 'engine');
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';

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
        const req = http.request(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-Access-Key': accessKey || ''
            }
        }, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                if(res.statusCode >= 200 && res.statusCode < 300) {
                    try { resolve(JSON.parse(body)); } catch(e) { resolve(body); }
                } else {
                    reject(`HTTP ${res.statusCode}: ${body}`);
                }
            });
        });
        req.on('error', reject);
        if (data) {
            req.write(JSON.stringify(data));
        }
        req.end();
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
    try {
        const res = await requestBackend('/api/validate', 'POST', { access_key: key });
        
        // Check version
        try {
           const vres = await requestBackend('/api/version/check', 'GET');
           if (vres.is_obsolete) {
               return { success: false, error: `App is obsolete. Please download new version: ${vres.download_url}` };
           }
        } catch(e) {}
        
        const config = loadConfig();
        config.accessKey = key;
        saveConfig(config);
        
        startOrchestrator(key);
        
        return { success: true, owner: res.owner };
    } catch (error) {
        return { success: false, error: error.toString() };
    }
});

ipcMain.handle('get-config', () => {
    return loadConfig();
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
