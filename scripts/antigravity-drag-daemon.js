// Antigravity Permanent Window Drag & Quota Guard Daemon
// Connects to Antigravity via DevToolsActivePort, ensuring both Draggable Titlebars
// and the Control Center Quota & Usage Top-Bar Indicator 24/7 across all chats/reloads.

const fs = require('fs');
const path = require('path');

const PORT_FILE = path.join(process.env.APPDATA, 'Antigravity', 'DevToolsActivePort');

const COMBINED_SCRIPT = `
(function installAntigravityDragStyles() {
  function applyStyles() {
    let style = document.getElementById('ag-window-drag-fix');
    if (!style) {
      style = document.createElement('style');
      style.id = 'ag-window-drag-fix';
      const root = document.head || document.documentElement;
      if (root) root.appendChild(style);
    }
    style.textContent = \`
      /* Draggable Titlebar & Top Bar */
      [class*="@container/titlebar"],
      .shrink-0:has(> [class*="@container/titlebar"]),
      .bg-sidebar > .shrink-0,
      #ag-quota-pill {
        -webkit-app-region: drag !important;
      }

      /* Interactive Controls Must Remain Clickable */
      [class*="@container/titlebar"] button,
      [class*="@container/titlebar"] input,
      [class*="@container/titlebar"] a,
      [class*="@container/titlebar"] [role="button"],
      [class*="@container/titlebar"] [class*="cursor-pointer"],
      .bg-sidebar > .shrink-0 button,
      .bg-sidebar > .shrink-0 [role="button"],
      #ag-btn-control-center,
      [style*="no-drag"] {
        -webkit-app-region: no-drag !important;
      }
    \`;
  }

  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', applyStyles);
  } else {
    applyStyles();
  }

  if (!window.__agDragObserver) {
    window.__agDragObserver = new MutationObserver(() => {
      if (!document.getElementById('ag-window-drag-fix')) {
        applyStyles();
      }
    });
    window.__agDragObserver.observe(document.documentElement, { childList: true, subtree: true });
  }

  if (!window.__agDragInterval) {
    window.__agDragInterval = setInterval(applyStyles, 2000);
  }
})();

// --- Antigravity Active Account Quota Top-Bar Indicator ---
(function initAntigravityQuotaIndicator() {
    const UI_VERSION = 'ag-swiss-ui-v2';
    const existingPill = document.getElementById('ag-quota-pill');
    if (existingPill && existingPill.dataset.uiVersion === UI_VERSION) return;
    window.__agQuotaIndicatorRunning = true;

    function quotaColor(val) {
        if (val === null || val === undefined || isNaN(val)) return '#f2f0ea';
        if (val >= 50) return '#52c47e';
        if (val >= 20) return '#d9a043';
        return '#e55333';
    }

    async function openControlCenter(e) {
        if (e) {
            e.stopPropagation();
            e.preventDefault();
        }
        if (window.__agOpeningCC && (Date.now() - window.__agOpeningCC < 600)) {
            return;
        }
        window.__agOpeningCC = Date.now();
        
        const btn = document.getElementById('ag-btn-control-center');
        if (btn) {
            btn.style.transform = 'scale(0.92)';
            setTimeout(() => { btn.style.transform = 'scale(1)'; }, 150);
        }

        // 1. Direct daemon API call to show/restore native GUI
        try {
            const resp = await fetch('http://127.0.0.1:28795/api/open-ui', { cache: 'no-store' });
            if (resp && resp.ok) return;
        } catch (_) {}

        // Retry briefly in case daemon is warming up
        try {
            await new Promise(r => setTimeout(r, 400));
            const resp2 = await fetch('http://127.0.0.1:28795/api/open-ui', { cache: 'no-store' });
            if (resp2 && resp2.ok) return;
        } catch (_) {}

        // 2. Main process IPC handler if registered
        try {
            if (typeof electron_1 !== 'undefined' && electron_1.ipcRenderer) {
                const opened = await electron_1.ipcRenderer.invoke('control-center:open');
                if (opened) return;
            }
        } catch (_) {}

        // 3. Fallback: launch native Control Center via registered Windows URL protocol (never opens a browser tab)
        try {
            if (typeof electron_1 !== 'undefined' && electron_1.ipcRenderer) {
                await electron_1.ipcRenderer.invoke('shell:open-external', 'antigravity-cc://open');
            }
        } catch (_) {}
    }

    function ensureStyles() {
        let style = document.getElementById('ag-quota-styles');
        if (style && style.dataset.uiVersion === UI_VERSION) return;
        if (!style) {
            style = document.createElement('style');
            style.id = 'ag-quota-styles';
            const target = document.head || document.documentElement;
            if (target) target.appendChild(style);
        }
        style.dataset.uiVersion = UI_VERSION;
        style.textContent = \`
            /* Window Draggable Titlebar & Topbar Areas */
            [class*="@container/titlebar"],
            .shrink-0:has(> [class*="@container/titlebar"]),
            .bg-sidebar > .shrink-0,
            #ag-quota-pill {
                -webkit-app-region: drag !important;
            }

            /* Interactive Elements inside Draggable Areas */
            [class*="@container/titlebar"] button,
            [class*="@container/titlebar"] input,
            [class*="@container/titlebar"] a,
            [class*="@container/titlebar"] [role="button"],
            [class*="@container/titlebar"] [class*="cursor-pointer"],
            .bg-sidebar > .shrink-0 button,
            .bg-sidebar > .shrink-0 [role="button"],
            #ag-btn-control-center,
            [style*="no-drag"] {
                -webkit-app-region: no-drag !important;
            }

            #ag-quota-pill {
                max-width: calc(100vw - 320px);
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            }
            .ag-badge-5h {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                background: transparent;
                border: none;
                padding: 0;
                font-family: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;
                font-variant-numeric: tabular-nums;
            }
            .ag-badge-wk {
                display: inline-flex;
                align-items: center;
                gap: 3px;
                background: transparent;
                border: none;
                padding: 0 0 0 4px;
                font-family: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;
                font-variant-numeric: tabular-nums;
                opacity: 0.78;
            }
            #ag-btn-control-center {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid transparent;
                border-radius: 4px;
                color: #a8a59c;
                font-family: inherit;
                font-size: 10.5px;
                font-weight: 500;
                letter-spacing: 0.01em;
                text-transform: none;
                height: 16px;
                padding: 0 6px;
                cursor: pointer;
                -webkit-app-region: no-drag;
                pointer-events: auto;
                outline: none;
                transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
            }
            #ag-btn-control-center:hover {
                background: rgba(255, 255, 255, 0.09) !important;
                border-color: rgba(229, 83, 51, 0.55) !important;
                color: #f2f0ea !important;
            }
            #ag-btn-control-center:hover svg {
                color: #e55333;
            }
            @media (max-width: 1020px) {
                #ag-quota-pill {
                    left: 260px !important;
                    right: 142px !important;
                    width: fit-content !important;
                    margin: 0 auto !important;
                    transform: none !important;
                    max-width: calc(100vw - 410px) !important;
                }
            }
            @media (max-width: 900px) {
                .ag-badge-wk { display: none !important; }
            }
            @media (max-width: 740px) {
                .ag-btn-text { display: none !important; }
                .ag-acct-text { max-width: 64px !important; }
            }
            @media (max-width: 600px) {
                .ag-acct-text { display: none !important; }
                #ag-quota-pill {
                    gap: 5px !important;
                }
            }
        \`;
    }

    function ensurePillElement() {
        ensureStyles();
        let el = document.getElementById('ag-quota-pill');
        if (!document.body) return null;
        if (el && document.body.contains(el) && el.dataset.uiVersion === UI_VERSION) {
            return el;
        }

        if (!el) {
            el = document.createElement('div');
            el.id = 'ag-quota-pill';
        }

        if (el.dataset.uiVersion !== UI_VERSION) {
            el.style.cssText = [
                'position: fixed',
                'top: 5px',
                'left: 50%',
                'transform: translateX(-50%)',
                'height: 22px',
                'z-index: 99999',
                'user-select: none',
                'display: inline-flex',
                'align-items: center',
                'gap: 8px',
                'padding: 0 4px 0 8px',
                'border-radius: 5px',
                'background: rgba(255, 255, 255, 0.03)',
                'border: 1px solid rgba(255, 255, 255, 0.07)',
                'color: #a8a59c',
                'font-family: "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif',
                'font-size: 11px',
                'line-height: 1',
                'cursor: pointer',
                'transition: transform 0.15s ease, background 0.15s ease, border-color 0.15s ease',
                'box-sizing: border-box',
                'pointer-events: auto'
            ].join(';') + ';';
            el.dataset.uiVersion = UI_VERSION;
        }

        if (!el.dataset.listenersBound) {
            el.dataset.listenersBound = 'true';
            el.addEventListener('mouseenter', () => {
                el.style.background = 'rgba(255, 255, 255, 0.06)';
                el.style.borderColor = 'rgba(255, 255, 255, 0.13)';
            });

            el.addEventListener('mouseleave', () => {
                el.style.background = 'rgba(255, 255, 255, 0.03)';
                el.style.borderColor = 'rgba(255, 255, 255, 0.07)';
            });

            el.addEventListener('click', (e) => {
                openControlCenter(e);
            });
        }

        if (!document.body.contains(el)) {
            document.body.appendChild(el);
        }
        return el;
    }

    let lastValidStatus = window.__agLastValidStatus || null;
    let isFetching = false;

    async function updateQuota() {
        if (isFetching) return;
        isFetching = true;
        try {
            let status = null;

            // 1. Live status from Control Center daemon
            try {
                const resp = await fetch('http://127.0.0.1:28795/api/status', { cache: 'no-store' });
                if (resp && resp.ok) {
                    const data = await resp.json();
                    if (data && data.active) {
                        status = data;
                        lastValidStatus = data;
                        window.__agLastValidStatus = data;
                    }
                }
            } catch (_) {}

            // 2. In-memory cache continuity
            if (!status && lastValidStatus) {
                status = lastValidStatus;
            }

            const pill = ensurePillElement();
            if (!pill) return;

            const controlBtnHtml = [
                '<button id="ag-btn-control-center" title="Click to open Antigravity Control Center">',
                '  <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" aria-hidden="true" style="flex-shrink:0;">',
                '    <line x1="2" y1="4" x2="14" y2="4"></line>',
                '    <circle cx="5.5" cy="4" r="1.5" fill="none"></circle>',
                '    <line x1="2" y1="8" x2="14" y2="8"></line>',
                '    <circle cx="10.5" cy="8" r="1.5" fill="none"></circle>',
                '    <line x1="2" y1="12" x2="14" y2="12"></line>',
                '    <circle cx="6.5" cy="12" r="1.5" fill="none"></circle>',
                '  </svg>',
                '  <span class="ag-btn-text">Control</span>',
                '</button>'
            ].join('');

            if (!status || !status.active) {
                if (pill.dataset.hasRendered === 'true' && pill.dataset.renderedUiVersion === UI_VERSION) {
                    return;
                }
                pill.dataset.renderedUiVersion = UI_VERSION;
                pill.innerHTML = [
                    '<span style="width:5px;height:5px;border-radius:50%;background:#d9a043;flex-shrink:0;display:inline-block;"></span>',
                    '<span style="color:#a8a59c;font-size:10.5px;font-weight:400;">Syncing</span>',
                    '<span style="width:1px;height:10px;background:rgba(255,255,255,0.10);"></span>',
                    controlBtnHtml
                ].join('');
                pill.title = 'Antigravity Quota: Waiting for switchboard status...\\nClick [Control] to open Control Center';
                attachButtonHandler();
                return;
            }

            const activeAccount = status.active;
            const shortName = activeAccount.includes('@') ? activeAccount.split('@')[0] : activeAccount;
            const quotaData = (status.quotas && status.quotas[activeAccount]) ? status.quotas[activeAccount] : null;

            let gemini5h = null;
            let gemini5hDelta = '';
            let geminiWeekly = null;
            let geminiWeeklyDelta = '';

            let claude5h = null;
            let claude5hDelta = '';
            let claudeWeekly = null;
            let claudeWeeklyDelta = '';

            if (quotaData) {
                if (quotaData.gemini) {
                    if (quotaData.gemini['5h']) {
                        gemini5h = quotaData.gemini['5h'].remaining;
                        gemini5hDelta = quotaData.gemini['5h'].resetDelta || '';
                    }
                    if (quotaData.gemini['weekly']) {
                        geminiWeekly = quotaData.gemini['weekly'].remaining;
                        geminiWeeklyDelta = quotaData.gemini['weekly'].resetDelta || '';
                    }
                }
                if (quotaData.claude) {
                    if (quotaData.claude['5h']) {
                        claude5h = quotaData.claude['5h'].remaining;
                        claude5hDelta = quotaData.claude['5h'].resetDelta || '';
                    }
                    if (quotaData.claude['weekly']) {
                        claudeWeekly = quotaData.claude['weekly'].remaining;
                        claudeWeeklyDelta = quotaData.claude['weekly'].resetDelta || '';
                    }
                }
            } else if (status.gemini !== undefined || status.claude !== undefined) {
                gemini5h = status.gemini;
                claude5h = status.claude;
                gemini5hDelta = status.geminiDelta || '';
                claude5hDelta = status.claudeDelta || '';
                geminiWeekly = status.geminiWeekly ?? null;
                claudeWeekly = status.claudeWeekly ?? null;
                geminiWeeklyDelta = status.geminiWeeklyDelta || '';
                claudeWeeklyDelta = status.claudeWeeklyDelta || '';
            }

            const gColor = quotaColor(gemini5h);
            const cColor = quotaColor(claude5h);

            const gVal = gemini5h !== null ? Math.round(gemini5h) + '%' : '--';
            const cVal = claude5h !== null ? Math.round(claude5h) + '%' : '--';

            const gWVal = geminiWeekly !== null ? Math.round(geminiWeekly) + '%' : '--';
            const cWVal = claudeWeekly !== null ? Math.round(claudeWeekly) + '%' : '--';

            pill.dataset.hasRendered = 'true';
            pill.dataset.renderedUiVersion = UI_VERSION;
            pill.innerHTML = [
                // Account Badge
                '<span style="display:inline-flex;align-items:center;gap:5px;">',
                '  <span style="width:5px;height:5px;border-radius:50%;background:#52c47e;flex-shrink:0;display:inline-block;"></span>',
                '  <span class="ag-acct-text" style="max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle;color:#d6d3cb;font-weight:400;">' + shortName + '</span>',
                '</span>',
                '<span style="width:1px;height:10px;background:rgba(255,255,255,0.10);"></span>',

                // Gemini Segment
                '<div style="display:inline-flex;align-items:center;gap:5px;">',
                '  <span style="font-family:&quot;IBM Plex Mono&quot;,&quot;Cascadia Mono&quot;,Consolas,monospace;font-size:10px;font-weight:600;color:#76736b;">G</span>',
                '  <span class="ag-badge-5h" title="Gemini 5h cycle remaining">',
                '    <span style="font-weight:500;color:' + gColor + ';font-size:10.5px;">' + gVal + '</span>',
                '    <span style="color:#76736b;font-size:9.5px;">' + (gemini5hDelta || '--') + '</span>',
                '  </span>',
                '  <span class="ag-badge-wk" title="Gemini Weekly quota remaining">',
                '    <span style="color:#6b6860;font-size:9px;">W</span>',
                '    <span style="font-weight:500;color:#a8a59c;font-size:10px;">' + gWVal + '</span>',
                '    <span style="color:#6b6860;font-size:9px;">' + (geminiWeeklyDelta || '--') + '</span>',
                '  </span>',
                '</div>',
                '<span style="width:1px;height:10px;background:rgba(255,255,255,0.10);"></span>',

                // Claude Segment
                '<div style="display:inline-flex;align-items:center;gap:5px;">',
                '  <span style="font-family:&quot;IBM Plex Mono&quot;,&quot;Cascadia Mono&quot;,Consolas,monospace;font-size:10px;font-weight:600;color:#76736b;">C</span>',
                '  <span class="ag-badge-5h" title="Claude 5h cycle remaining">',
                '    <span style="font-weight:500;color:' + cColor + ';font-size:10.5px;">' + cVal + '</span>',
                '    <span style="color:#76736b;font-size:9.5px;">' + (claude5hDelta || '--') + '</span>',
                '  </span>',
                '  <span class="ag-badge-wk" title="Claude Weekly quota remaining">',
                '    <span style="color:#6b6860;font-size:9px;">W</span>',
                '    <span style="font-weight:500;color:#a8a59c;font-size:10px;">' + cWVal + '</span>',
                '    <span style="color:#6b6860;font-size:9px;">' + (claudeWeeklyDelta || '--') + '</span>',
                '  </span>',
                '</div>',
                '<span style="width:1px;height:10px;background:rgba(255,255,255,0.10);"></span>',

                // Control Center Button
                controlBtnHtml
            ].join('');

            let tip = 'Active Account: ' + activeAccount + '\\n';
            if (gemini5h !== null) tip += '• Gemini (5h cycle): ' + gemini5h.toFixed(1) + '% (Resets in ' + (gemini5hDelta || 'N/A') + ')\\n';
            if (geminiWeekly !== null) tip += '• Gemini (Weekly): ' + geminiWeekly.toFixed(1) + '% (Resets in ' + (geminiWeeklyDelta || 'N/A') + ')\\n';
            if (claude5h !== null) tip += '• Claude (5h cycle): ' + claude5h.toFixed(1) + '% (Resets in ' + (claude5hDelta || 'N/A') + ')\\n';
            if (claudeWeekly !== null) tip += '• Claude (Weekly): ' + claudeWeekly.toFixed(1) + '% (Resets in ' + (claudeWeeklyDelta || 'N/A') + ')\\n';
            tip += '\\nClick [Control] to open Control Center';

            pill.title = tip;
            attachButtonHandler();
        } catch (_) {}
        finally {
            isFetching = false;
        }
    }

    window.__agUpdateQuota = updateQuota;

    function attachButtonHandler() {
        const btn = document.getElementById('ag-btn-control-center');
        if (btn && !btn.dataset.bound) {
            btn.dataset.bound = 'true';
            btn.addEventListener('click', (e) => {
                openControlCenter(e);
            });
        }
    }

    function startMonitor() {
        ensurePillElement();
        updateQuota();
        if (window.__agQuotaInterval) clearInterval(window.__agQuotaInterval);
        if (window.__agPillInterval) clearInterval(window.__agPillInterval);
        window.__agQuotaInterval = setInterval(updateQuota, 4000);
        window.__agPillInterval = setInterval(ensurePillElement, 2000);
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', startMonitor);
    } else {
        startMonitor();
    }
})();
`;

const connectedTargets = new Set();

async function getDevToolsPort() {
  if (!fs.existsSync(PORT_FILE)) return null;
  try {
    const content = fs.readFileSync(PORT_FILE, 'utf8').trim().split('\n')[0].trim();
    const port = parseInt(content, 10);
    return isNaN(port) ? null : port;
  } catch (_) {
    return null;
  }
}

async function attachToPage(target) {
  if (connectedTargets.has(target.id)) return;
  connectedTargets.add(target.id);

  let ws;
  try {
    ws = new WebSocket(target.webSocketDebuggerUrl);
  } catch (err) {
    connectedTargets.delete(target.id);
    return;
  }

  ws.onopen = () => {
    // 1. Enable Page domain
    ws.send(JSON.stringify({ id: 1, method: 'Page.enable' }));
    // 2. Add script for all future navigations / document loads
    ws.send(JSON.stringify({
      id: 2,
      method: 'Page.addScriptToEvaluateOnNewDocument',
      params: { source: COMBINED_SCRIPT }
    }));
    // 3. Evaluate immediately in the current document
    ws.send(JSON.stringify({
      id: 3,
      method: 'Runtime.evaluate',
      params: { expression: COMBINED_SCRIPT }
    }));
  };

  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      // On any frame navigation or load event, re-apply immediately
      if (data.method === 'Page.frameNavigated' || data.method === 'Page.loadEventFired' || data.method === 'Page.domContentEventFired') {
        ws.send(JSON.stringify({
          id: 10,
          method: 'Runtime.evaluate',
          params: { expression: COMBINED_SCRIPT }
        }));
      }
    } catch (_) {}
  };

  ws.onclose = () => {
    connectedTargets.delete(target.id);
  };

  ws.onerror = () => {
    connectedTargets.delete(target.id);
  };
}

const DAEMON_BOOT_TS = Date.now();
let lastDaemonSpawnAttempt = 0;
async function ensureControlCenterDaemon() {
  const now = Date.now();
  // Give Windows Startup time to launch AntigravityControlCenter.exe --daemon before spawning another
  if (now - DAEMON_BOOT_TS < 4000) return;
  if (now - lastDaemonSpawnAttempt < 15000) return;
  lastDaemonSpawnAttempt = now;

  try {
    const res = await fetch('http://127.0.0.1:28795/api/ping', { signal: AbortSignal.timeout(2000) });
    if (res && res.ok) return;
  } catch (_) {}

  // Control Center daemon is not running: spawn AntigravityControlCenter.exe --daemon detached
  try {
    const { spawn } = require('child_process');
    const exeCandidates = [
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'AntigravityControlCenter', 'AntigravityControlCenter.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'AntigravityControlCenter', 'v1.3.0', 'AntigravityControlCenter', 'AntigravityControlCenter.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'AntigravityControlCenter', 'v1.2.2', 'AntigravityControlCenter', 'AntigravityControlCenter.exe')
    ];
    for (const exe of exeCandidates) {
      if (fs.existsSync(exe)) {
        const child = spawn(exe, ['--daemon'], {
          cwd: path.dirname(exe),
          detached: true,
          stdio: 'ignore',
          windowsHide: true
        });
        child.unref();
        break;
      }
    }
  } catch (_) {}
}

let lastAsarMtime = 0;
let isPatchingAsar = false;

function ensureAsarPatched() {
  if (isPatchingAsar) return;
  try {
    const asarPath = path.join(process.env.LOCALAPPDATA, 'Programs', 'antigravity', 'resources', 'app.asar');
    if (!fs.existsSync(asarPath)) return;

    const mtime = fs.statSync(asarPath).mtimeMs;
    if (mtime === lastAsarMtime) return;
    lastAsarMtime = mtime;

    const patcherScript = path.join(__dirname, 'auto_patch_antigravity.js');
    if (!fs.existsSync(patcherScript)) return;

    const buf = fs.readFileSync(asarPath);
    const hasMarker = buf.includes(Buffer.from('initAntigravityQuotaIndicator')) &&
                      buf.includes(Buffer.from('lastValidStatus')) &&
                      buf.includes(Buffer.from('control-center:ensure-daemon')) &&
                      !buf.includes(Buffer.from("'http://127.0.0.1:28795/'"));
    if (!hasMarker) {
      isPatchingAsar = true;
      console.log('[DragDaemon] Stock app.asar detected after update. Auto-restoring top-bar quota extension...');
      const { exec } = require('child_process');
      exec(`node "${patcherScript}"`, { cwd: __dirname }, (err, stdout, stderr) => {
        isPatchingAsar = false;
        if (!err) {
          try {
            lastAsarMtime = fs.statSync(asarPath).mtimeMs;
          } catch (_) {}
          console.log('[DragDaemon] Top-bar indicator auto-restored successfully.');
        } else {
          console.error('[DragDaemon] Auto-restore error:', stderr || err.message);
        }
      });
    }
  } catch (_) {
    isPatchingAsar = false;
  }
}

async function poll() {
  ensureAsarPatched();
  ensureControlCenterDaemon();
  const port = await getDevToolsPort();
  if (port) {
    try {
      const resp = await fetch('http://127.0.0.1:' + port + '/json', { signal: AbortSignal.timeout(1500) });
      if (resp.ok) {
        const targets = await resp.json();
        const pages = targets.filter(t => {
          if (t.type !== 'page' || !t.webSocketDebuggerUrl) return false;
          const u = t.url || '';
          if (u.startsWith('data:') || u.startsWith('about:')) return false;
          if (/^https?:\/\/(?!127\.0\.0\.1|localhost)/i.test(u)) return false;
          return true;
        });
        for (const page of pages) {
          if (!connectedTargets.has(page.id)) {
            attachToPage(page);
          }
        }
      }
    } catch (_) {}
  }
}

// Initial attach and continuous guard loop
poll();
setInterval(poll, 1500);
