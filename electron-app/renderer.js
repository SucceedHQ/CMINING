const { ipcRenderer } = require('electron');

const loginScreen = document.getElementById('login-screen');
const dashboardScreen = document.getElementById('dashboard-screen');
const loginBtn = document.getElementById('login-btn');
const keyInput = document.getElementById('access-key-input');
const loginError = document.getElementById('login-error');
const serverUrlEl = document.getElementById('server-url');
const workerNameEl = document.getElementById('worker-name');
const terminal = document.getElementById('terminal-output');
const activeEngineTag = document.getElementById('active-engine');
const logoutBtn = document.getElementById('logout-btn');

// Show which server the app is pointed at
ipcRenderer.invoke('get-backend-url').then(url => {
    if (serverUrlEl) serverUrlEl.innerText = `🔗 Server: ${url}`;
});

function showDashboard(owner) {
    loginScreen.classList.add('hidden');
    dashboardScreen.classList.remove('hidden');
    workerNameEl.innerText = owner;
    logToTerminal('Connected to pool. Waiting for orchestrator instructions...', '#10b981');
}

function showLogin() {
    loginScreen.classList.remove('hidden');
    dashboardScreen.classList.add('hidden');
    keyInput.value = '';
}

function logToTerminal(msg, color = '#10b981') {
    const p = document.createElement('p');
    const time = new Date().toLocaleTimeString();
    p.innerHTML = `<span style="color: #64748b;">[${time}]</span> <span style="color: ${color}">${msg}</span>`;
    terminal.appendChild(p);
    
    // Auto scroll to bottom
    if (terminal.childElementCount > 200) terminal.removeChild(terminal.firstChild);
    terminal.scrollTop = terminal.scrollHeight;
}

loginBtn.addEventListener('click', async () => {
    const key = keyInput.value.trim();
    if (!key) return;
    
    loginBtn.disabled = true;
    loginBtn.innerText = 'Connecting...';
    loginError.innerText = '';
    
    const res = await ipcRenderer.invoke('validate-key', key);
    
    loginBtn.disabled = false;
    loginBtn.innerText = 'Connect Wallet';
    
    if (res.success) {
        showDashboard(res.owner);
    } else {
        loginError.innerText = res.error || "Connection failed";
    }
});

logoutBtn.addEventListener('click', async () => {
    await ipcRenderer.invoke('logout');
    showLogin();
    terminal.innerHTML = '<p>Initializing connection to mining pool...</p>';
});

// Auto-login if key exists in config
ipcRenderer.invoke('get-config').then(async (config) => {
    if (config && config.accessKey) {
        keyInput.value = config.accessKey;
        loginBtn.click();
    }
});

// IPC Listeners from main.js orchestrator
ipcRenderer.on('engine-log', (event, msg) => {
    let color = '#f8fafc'; // default text
    if (msg.includes('ERROR') || msg.includes('Fatal') || msg.includes('failed')) color = '#ef4444';
    else if (msg.includes('✔') || msg.includes('Success')) color = '#10b981';
    else if (msg.includes('Switching') || msg.includes('Starting')) color = '#3b82f6';
    
    // Ignore boring log dumps
    if(msg.length > 200) msg = msg.substring(0, 200) + '...';
    
    logToTerminal(msg, color);
});

ipcRenderer.on('engine-status', (event, data) => {
    if (data.status === 'starting' || data.status === 'running') {
        const title = data.mode === 'scraper' ? 'Scraping Data...' : 'Processing Outreach...';
        activeEngineTag.innerText = title;
    } else {
        activeEngineTag.innerText = 'Idle / Waiting';
    }
});
