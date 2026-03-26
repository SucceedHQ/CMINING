import sys

with open('c:\\Users\\USER\\Documents\\TOOLS\\CMINING TOOL\\CMining-Monorepo\\electron-app\\index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

replacement = """        <!-- Logs Section -->
        <div class="logs-wrapper">
            <div class="logs-header">
                <button class="toggle-logs" id="toggle-logs">Hide Logs</button>
            </div>
            <div class="terminal" id="terminal-output">
                <p><span class="log-time">></span> <span class="log-msg">Initializing secure connection to mining pool...</span></p>
            </div>
        </div>
    </div>
</div>

<!-- Request Key Modal -->
<div id="request-key-modal" class="modal-overlay hidden">
    <div class="modal">
        <h2>Request Access Key</h2>
        <p class="modal-info">Enter your email address to request a new worker access key. We will contact you.</p>
        <input type="email" id="req-email" placeholder="Contact Email *" title="Contact Email" style="width: 100%; padding: 10px; font-size: 14px; margin-bottom: 15px; background: var(--panel-bg); border: 1px solid var(--border); color: white; border-radius: 6px;">
        <div class="modal-footer">
            <button id="cancel-req-btn" class="btn-outline flex-1">Cancel</button>
            <button id="submit-req-btn" class="btn-primary flex-1">Send Request</button>
        </div>
    </div>
</div>

<!-- Report Bug Modal -->
<div id="bug-modal" class="modal-overlay hidden">
    <div class="modal">
        <h2>Report Technical Issue</h2>
        <p class="modal-info">Please describe the problem you encountered in detail.</p>
        <textarea id="bug-desc" placeholder="Enter your report here..." title="Report Description" style="width: 100%; padding: 12px; height: 150px; background: #030712; border: 1px solid #374151; border-radius: 6px; color: white; margin-bottom: 15px; font-family: inherit; font-size: 15px;"></textarea>
        <div class="modal-footer">
            <button id="cancel-bug-btn" class="btn-outline flex-1">Cancel</button>
            <button id="submit-bug-btn" class="btn-primary flex-1">Submit Report</button>
        </div>
    </div>
</div>

<!-- Notifications Modal -->
<div id="notif-modal" class="modal-overlay hidden">
    <div class="modal" style="max-width: 500px;">
        <h2>Notifications</h2>
        <div id="notif-list" style="max-height: 400px; overflow-y: auto; margin-bottom: 20px;">
            <p style="color: var(--text-muted); text-align: center; padding: 10px 0;">No active notifications.</p>
        </div>
        <button id="close-notif-btn" class="btn-outline" style="width: 100%; justify-content: center;">Close</button>
    </div>
</div>
"""

new_lines = lines[:301] + [replacement] + lines[308:]
with open('c:\\Users\\USER\\Documents\\TOOLS\\CMINING TOOL\\CMining-Monorepo\\electron-app\\index.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
