const fs = require('fs');

const path = require('path');

const os = require('os');

const { execSync } = require('child_process');



const ASAR_PATH = path.join(process.env.LOCALAPPDATA, 'Programs', 'antigravity', 'resources', 'app.asar');

const UNPACKED_PATH = path.join(process.env.LOCALAPPDATA, 'Programs', 'antigravity', 'resources', 'app.asar.unpacked');

const UPDATER_DIR = path.join(process.env.LOCALAPPDATA, 'antigravity-updater');

const MARKER = 'initAntigravityQuotaIndicator';



function isAlreadyPatched() {

    if (!fs.existsSync(ASAR_PATH)) return false;

    try {

        const buf = fs.readFileSync(ASAR_PATH);

        return buf.includes(Buffer.from(MARKER)) &&
               buf.includes(Buffer.from('lastValidStatus')) &&
               buf.includes(Buffer.from('control-center:ensure-daemon')) &&
               buf.includes(Buffer.from('ag-swiss-ui-v1')) &&
               !buf.includes(Buffer.from("'http://127.0.0.1:28795/'"));

    } catch (e) {

        return false;

    }

}



function cleanUpdaterCache() {
    // Preserved for official Google Antigravity auto-updates. Never delete updater files.
    return;
}



const PRELOAD_INJECTION = `

// --- Antigravity Active Account Quota Top-Bar Indicator ---

(function initAntigravityQuotaIndicator() {
    const UI_VERSION = 'ag-swiss-ui-v1';
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

        // 2. Main process IPC handler (spawns native exe directly, never opens a browser tab)
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

                background: #131311;

                padding: 1px 5px;

                border-radius: 2px;

                border: 1px solid #2b2a27;

                font-family: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;

                font-variant-numeric: tabular-nums;

            }

            .ag-badge-wk {

                display: inline-flex;

                align-items: center;

                gap: 3px;

                background: transparent;

                padding: 1px 4px;

                border-radius: 2px;

                border: 1px solid #2b2a27;

                font-family: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;

                font-variant-numeric: tabular-nums;

            }

            #ag-btn-control-center {

                display: inline-flex;

                align-items: center;

                gap: 4px;

                background: #22221f;

                border: 1px solid #403e39;

                border-radius: 2px;

                color: #f2f0ea;

                font-family: "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;

                font-size: 9.5px;

                font-weight: 600;

                letter-spacing: 0.05em;

                text-transform: uppercase;

                height: 18px;

                padding: 0 6px;

                cursor: pointer;

                -webkit-app-region: no-drag;

                pointer-events: auto;

                outline: none;

                transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;

            }

            #ag-btn-control-center:hover {

                background: #2c2b27 !important;

                border-color: #e55333 !important;

                color: #ffffff !important;

            }

            @media (max-width: 1200px) {

                #ag-quota-pill {

                    left: auto !important;

                    right: 140px !important;

                    transform: none !important;

                }

            }

            @media (max-width: 950px) {

                .ag-btn-text { display: none !important; }

                .ag-acct-text { max-width: 70px !important; }

                #ag-quota-pill {

                    left: auto !important;

                    right: 140px !important;

                    transform: none !important;

                    gap: 5px !important;

                    padding: 0 6px 0 8px !important;

                }

            }

            @media (max-width: 820px) {

                #ag-quota-pill {

                    left: auto !important;

                    right: 140px !important;

                    transform: none !important;

                    gap: 4px !important;

                    padding: 0 5px 0 6px !important;

                }

                .ag-badge-wk { display: none !important; }

            }

            @media (max-width: 600px) {

                #ag-quota-pill {

                    right: 135px !important;

                    gap: 3px !important;

                }

                .ag-acct-text { max-width: 50px !important; }

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

                'top: 4px',

                'left: 50%',

                'transform: translateX(-50%)',

                'height: 24px',

                'z-index: 99999',

                'user-select: none',

                'display: inline-flex',

                'align-items: center',

                'gap: 7px',

                'padding: 0 4px 0 8px',

                'border-radius: 3px',

                'background: #191917',

                'border: 1px solid #2b2a27',

                'color: #f2f0ea',

                'font-family: "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif',

                'font-size: 11px',

                'line-height: 1',

                'box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45)',

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

                el.style.background = '#22221f';

                el.style.borderColor = '#403e39';

            });

            el.addEventListener('mouseleave', () => {

                el.style.background = '#191917';

                el.style.borderColor = '#2b2a27';

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
    let lastEnsureDaemonCall = 0;

    function triggerEnsureDaemon() {
        const now = Date.now();
        if (now - lastEnsureDaemonCall < 10000) return;
        lastEnsureDaemonCall = now;
        try {
            if (typeof electron_1 !== 'undefined' && electron_1.ipcRenderer) {
                electron_1.ipcRenderer.invoke('control-center:ensure-daemon').catch(() => {});
            }
        } catch (_) {}
    }

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
            } catch (_) {
                triggerEnsureDaemon();
            }

            // 2. In-memory cache continuity: if daemon is busy/refreshing, never flip to old stale accounts
            if (!status && lastValidStatus) {
                status = lastValidStatus;
            }

            const pill = ensurePillElement();
            if (!pill) return;

            const controlBtnHtml = [
                '<button id="ag-btn-control-center" title="Click to open Antigravity Control Center">',
                '  <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" aria-hidden="true" style="flex-shrink:0;">',
                '    <line x1="2" y1="4" x2="14" y2="4"></line>',
                '    <circle cx="5.5" cy="4" r="1.5" fill="#e55333" stroke="#e55333"></circle>',
                '    <line x1="2" y1="8" x2="14" y2="8"></line>',
                '    <circle cx="10.5" cy="8" r="1.5" fill="#191917"></circle>',
                '    <line x1="2" y1="12" x2="14" y2="12"></line>',
                '    <circle cx="6.5" cy="12" r="1.5" fill="#191917"></circle>',
                '  </svg>',
                '  <span class="ag-btn-text">CONTROL</span>',
                '</button>'
            ].join('');

            if (!status || !status.active) {
                if (pill.dataset.hasRendered === 'true' && pill.dataset.renderedUiVersion === UI_VERSION) {
                    return;
                }
                pill.dataset.renderedUiVersion = UI_VERSION;
                pill.innerHTML = [
                    '<span style="width:5px;height:5px;border-radius:50%;background:#d9a043;flex-shrink:0;display:inline-block;"></span>',
                    '<span style="color:#a8a59c;font-family:&quot;IBM Plex Mono&quot;,&quot;Cascadia Mono&quot;,Consolas,monospace;font-size:10px;letter-spacing:0.04em;text-transform:uppercase;">Syncing</span>',
                    '<span style="width:1px;height:12px;background:#2b2a27;"></span>',
                    controlBtnHtml
                ].join('');
                pill.title = 'Antigravity Quota: Waiting for switchboard status...\\nClick [Control] to open Control Center';
                attachButtonHandler();
                return;
            }

            pill.dataset.hasRendered = 'true';
            pill.dataset.renderedUiVersion = UI_VERSION;



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



            pill.innerHTML = [

                // Account Badge

                '<span style="display:inline-flex;align-items:center;gap:5px;">',

                '  <span style="width:5px;height:5px;border-radius:50%;background:#52c47e;flex-shrink:0;display:inline-block;"></span>',

                '  <span class="ag-acct-text" style="max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle;color:#f2f0ea;font-weight:500;">' + shortName + '</span>',

                '</span>',

                '<span style="width:1px;height:12px;background:#2b2a27;"></span>',



                // Gemini Segment

                '<div style="display:inline-flex;align-items:center;gap:5px;">',

                '  <span style="font-family:&quot;IBM Plex Mono&quot;,&quot;Cascadia Mono&quot;,Consolas,monospace;font-size:10px;font-weight:700;color:#a8a59c;">G</span>',

                '  <span class="ag-badge-5h" title="Gemini 5h cycle remaining">',

                '    <span style="font-weight:600;color:' + gColor + ';font-size:10.5px;">' + gVal + '</span>',

                '    <span style="color:#76736b;font-size:9.5px;">' + (gemini5hDelta || '--') + '</span>',

                '  </span>',

                '  <span class="ag-badge-wk" title="Gemini Weekly quota remaining">',

                '    <span style="color:#76736b;font-size:9px;font-weight:600;">W</span>',

                '    <span style="font-weight:500;color:#a8a59c;font-size:10px;">' + gWVal + '</span>',

                '    <span style="color:#76736b;font-size:9px;">' + (geminiWeeklyDelta || '--') + '</span>',

                '  </span>',

                '</div>',

                '<span style="width:1px;height:12px;background:#2b2a27;"></span>',



                // Claude Segment

                '<div style="display:inline-flex;align-items:center;gap:5px;">',

                '  <span style="font-family:&quot;IBM Plex Mono&quot;,&quot;Cascadia Mono&quot;,Consolas,monospace;font-size:10px;font-weight:700;color:#a8a59c;">C</span>',

                '  <span class="ag-badge-5h" title="Claude 5h cycle remaining">',

                '    <span style="font-weight:600;color:' + cColor + ';font-size:10.5px;">' + cVal + '</span>',

                '    <span style="color:#76736b;font-size:9.5px;">' + (claude5hDelta || '--') + '</span>',

                '  </span>',

                '  <span class="ag-badge-wk" title="Claude Weekly quota remaining">',

                '    <span style="color:#76736b;font-size:9px;font-weight:600;">W</span>',

                '    <span style="font-weight:500;color:#a8a59c;font-size:10px;">' + cWVal + '</span>',

                '    <span style="color:#76736b;font-size:9px;">' + (claudeWeeklyDelta || '--') + '</span>',

                '  </span>',

                '</div>',

                '<span style="width:1px;height:12px;background:#2b2a27;"></span>',



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
        triggerEnsureDaemon();
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



function applyDiskPatch(force = false) {

    if (!fs.existsSync(ASAR_PATH)) {

        console.error('Antigravity app.asar not found at: ' + ASAR_PATH);

        return false;

    }



    if (!force && isAlreadyPatched()) {

        console.log('[AutoPatcher] Already patched. Nothing to do.');

        return true;

    }



    console.log('[AutoPatcher] Applying beautiful micro-badge top-bar patch...');



    const tempDir = path.join(os.tmpdir(), 'ag_asar_patch_' + Date.now());

    const patchedAsar = path.join(os.tmpdir(), 'patched_app_' + Date.now() + '.asar');



    try {

        // 1. Extract

        execSync(`npx --yes asar extract "${ASAR_PATH}" "${tempDir}"`, { stdio: 'ignore' });



        // 2. Patch preload.js

        const preloadPath = path.join(tempDir, 'dist', 'preload.js');

        if (!fs.existsSync(preloadPath)) {
            throw new Error('dist/preload.js not found inside app.asar');
        }

        let preloadContent = fs.readFileSync(preloadPath, 'utf8');

        const markerIdx = preloadContent.indexOf('// --- Antigravity Active Account Quota Top-Bar Indicator ---');

        if (markerIdx !== -1) {

            preloadContent = preloadContent.substring(0, markerIdx).trim();

        }

        preloadContent = preloadContent.trim() + '\n\n' + PRELOAD_INJECTION;

        fs.writeFileSync(preloadPath, preloadContent, 'utf8');



        // 3. Patch ipcHandlers.js (auto-launch daemon on Antigravity startup + control-center:open & ensure-daemon handlers)

        const ipcPath = path.join(tempDir, 'dist', 'ipcHandlers.js');

        if (fs.existsSync(ipcPath)) {

            let ipcContent = fs.readFileSync(ipcPath, 'utf8');

            // Remove any older control-center:open snippet if present
            ipcContent = ipcContent.replace(/\/\/ --- Antigravity Control Center Auto-Launch & IPC ---[\s\S]*?\/\/ --- End Antigravity Control Center IPC ---\s*/g, '');

            if (!ipcContent.includes('control-center:ensure-daemon')) {

                const primaryTarget = "electron_1.ipcMain.handle('storage:get-items',";
                const fallbackTarget = "electron_1.ipcMain.handle(";
                const target = ipcContent.includes(primaryTarget)
                    ? primaryTarget
                    : (ipcContent.includes(fallbackTarget) ? fallbackTarget : null);

                if (target) {
                    const injection = [
                        "// --- Antigravity Control Center Auto-Launch & IPC ---",
                        "    const spawnControlCenter = (args = []) => {",
                        "        try {",
                        "            const { spawn } = require('child_process');",
                        "            const exePath = require('path').join(process.env.LOCALAPPDATA || '', 'Programs', 'AntigravityControlCenter', 'AntigravityControlCenter.exe');",
                        "            if (require('fs').existsSync(exePath)) {",
                        "                spawn(exePath, args, {",
                        "                    cwd: require('path').dirname(exePath),",
                        "                    detached: true,",
                        "                    stdio: 'ignore',",
                        "                    windowsHide: true",
                        "                }).unref();",
                        "                return true;",
                        "            }",
                        "        } catch (_) {}",
                        "        return false;",
                        "    };",
                        "    const ensureControlCenterDaemon = async () => {",
                        "        try {",
                        "            const r = await fetch('http://127.0.0.1:28795/api/ping', { signal: AbortSignal.timeout(800) });",
                        "            if (r && r.ok) return true;",
                        "        } catch (_) {}",
                        "        return spawnControlCenter(['--daemon']);",
                        "    };",
                        "    ensureControlCenterDaemon();",
                        "    electron_1.ipcMain.removeHandler?.('control-center:ensure-daemon');",
                        "    electron_1.ipcMain.handle('control-center:ensure-daemon', async () => {",
                        "        return await ensureControlCenterDaemon();",
                        "    });",
                        "    electron_1.ipcMain.removeHandler?.('control-center:open');",
                        "    electron_1.ipcMain.handle('control-center:open', async () => {",
                        "        try {",
                        "            const r = await fetch('http://127.0.0.1:28795/api/open-ui', { signal: AbortSignal.timeout(1500) });",
                        "            if (r && r.ok) return true;",
                        "        } catch (_) {}",
                        "        return spawnControlCenter([]);",
                        "    });",
                        "    // --- End Antigravity Control Center IPC ---",
                        "    " + target
                    ].join('\n');

                    ipcContent = ipcContent.replace(target, injection);

                    fs.writeFileSync(ipcPath, ipcContent, 'utf8');
                } else {
                    console.warn('[AutoPatcher] Warning: ipcMain.handle anchor not found in dist/ipcHandlers.js');
                }

            }

        }



        // 4. Repack

        execSync(`npx --yes asar pack "${tempDir}" "${patchedAsar}" --unpack-dir "node_modules/chrome-devtools-mcp"`, { stdio: 'ignore' });



        // 5. Replace app.asar

        fs.copyFileSync(patchedAsar, ASAR_PATH);



        // 6. Copy unpacked files if generated

        const patchedUnpacked = patchedAsar + '.unpacked';

        if (fs.existsSync(patchedUnpacked)) {

            try {

                fs.cpSync(patchedUnpacked, UNPACKED_PATH, { recursive: true, force: true });

            } catch (_) {}

        }



        cleanUpdaterCache();



        console.log('[AutoPatcher] Successfully patched Antigravity app.asar!');

        return true;

    } catch (err) {

        console.error('[AutoPatcher] Patching failed:', err.message);

        return false;

    } finally {

        try {

            if (fs.existsSync(tempDir)) fs.rmSync(tempDir, { recursive: true, force: true });

            if (fs.existsSync(patchedAsar)) fs.rmSync(patchedAsar, { force: true });

            const pUnpacked = patchedAsar + '.unpacked';

            if (fs.existsSync(pUnpacked)) fs.rmSync(pUnpacked, { recursive: true, force: true });

        } catch (_) {}

    }

}



async function isAntigravityRunning() {

    const portFile = path.join(process.env.APPDATA, 'Antigravity', 'DevToolsActivePort');

    if (!fs.existsSync(portFile)) return false;

    try {

        const port = fs.readFileSync(portFile, 'utf8').trim().split('\n')[0].trim();

        const resp = await fetch(`http://127.0.0.1:${port}/json`, { signal: AbortSignal.timeout(1500) });

        return resp.ok;

    } catch (_) {

        return false;

    }

}



async function injectLiveCDP() {

    const portFile = path.join(process.env.APPDATA, 'Antigravity', 'DevToolsActivePort');

    if (!fs.existsSync(portFile)) {

        console.log('[AutoPatcher] DevToolsActivePort not found. Antigravity may not be running.');

        return false;

    }



    const DRAG_PERSISTENT_SCRIPT = `

(function installAntigravityDragStyles() {

    function applyStyles() {

        if (!document.getElementById('ag-window-drag-fix')) {

            const style = document.createElement('style');

            style.id = 'ag-window-drag-fix';

            style.textContent = \`

                /* Titlebar & Top Bar Draggable Regions */

                [class*="@container/titlebar"],

                .shrink-0:has(> [class*="@container/titlebar"]),

                .bg-sidebar > .shrink-0,

                #ag-quota-pill {

                    -webkit-app-region: drag !important;

                }



                /* Interactive Controls Inside Titlebar Must Be Clickable */

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

            const root = document.head || document.documentElement;

            if (root) root.appendChild(style);

        }

    }



    if (document.readyState === 'loading') {

        window.addEventListener('DOMContentLoaded', applyStyles);

    } else {

        applyStyles();

    }

    setInterval(applyStyles, 1000);

})();

`;



    try {

        const port = fs.readFileSync(portFile, 'utf8').trim().split('\n')[0].trim();

        const resp = await fetch(`http://127.0.0.1:${port}/json`, { signal: AbortSignal.timeout(2000) });

        if (!resp.ok) return false;

        const targets = await resp.json();

        const pages = targets.filter(t => {
            if (t.type !== 'page' || !t.webSocketDebuggerUrl) return false;
            const u = t.url || '';
            if (u.startsWith('data:') || u.startsWith('about:')) return false;
            if (/^https?:\/\/(?!127\.0\.0\.1|localhost)/i.test(u)) return false;
            return true;
        });

        if (!pages.length) {
            console.log('[AutoPatcher] No active Antigravity page targets found.');
            return false;
        }

        let injected = 0;
        for (const page of pages) {
            await new Promise((resolve) => {
                const ws = new WebSocket(page.webSocketDebuggerUrl);
                ws.onopen = () => {
                    // 1. Invalidate/ensure drag styles immediately
                    ws.send(JSON.stringify({
                        id: 1,
                        method: 'Runtime.evaluate',
                        params: { expression: DRAG_PERSISTENT_SCRIPT }
                    }));
                    // 2. Persist drag styles across ALL future document navigations/reloads
                    ws.send(JSON.stringify({
                        id: 2,
                        method: 'Page.addScriptToEvaluateOnNewDocument',
                        params: { source: DRAG_PERSISTENT_SCRIPT }
                    }));
                    // 3. Ensure Quota Pill
                    ws.send(JSON.stringify({
                        id: 3,
                        method: 'Runtime.evaluate',
                        params: { expression: 'Boolean(document.getElementById("ag-quota-pill"))' }
                    }));
                };
                ws.onmessage = (msg) => {
                    try {
                        const data = JSON.parse(msg.data);
                        if (data.id === 3) {
                            ws.send(JSON.stringify({
                                id: 4,
                                method: 'Runtime.evaluate',
                                params: { expression: PRELOAD_INJECTION }
                            }));
                        } else if (data.id === 4) {

                            injected++;

                            setImmediate(() => { try { ws.close(); } catch(_) {} resolve(); });

                        }

                    } catch (_) {

                        ws.close();

                        resolve();

                    }

                };

                ws.onerror = () => resolve();

                setTimeout(() => {

                    try { ws.close(); } catch(_) {}

                    resolve();

                }, 2500);

            });

        }

        console.log(`[AutoPatcher] Successfully ensured draggable titlebar & quota pill on ${injected} page(s).`);

        return true;

    } catch (e) {

        console.error('[AutoPatcher] Live CDP injection error:', e.message);

        return false;

    }

}



async function applyPatch(force = false) {
    const isLiveOnly = process.argv.includes('--live');
    const isDiskOnly = process.argv.includes('--disk');

    let liveOk = false;
    if (!isDiskOnly) {
        const running = await isAntigravityRunning();
        if (running) {
            console.log('[AutoPatcher] Antigravity CDP active. Performing zero-downtime Live CDP injection...');
            liveOk = await injectLiveCDP();
            if (liveOk && !force && isAlreadyPatched()) return true;
        }
    }

    if (isLiveOnly) {
        return liveOk;
    }

    return applyDiskPatch(force);
}



// If run directly:

if (require.main === module) {
    const force = process.argv.includes('--force');
    applyPatch(force).then(success => {
        setTimeout(() => {
            process.exit(success ? 0 : 1);
        }, 200);
    }).catch(err => {
        console.error('[AutoPatcher] Fatal error:', err);
        setTimeout(() => {
            process.exit(1);
        }, 200);
    });
}



module.exports = { isAlreadyPatched, applyPatch, applyDiskPatch, injectLiveCDP, isAntigravityRunning, ASAR_PATH };




