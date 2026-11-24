let currentState = null;
    let currentTab = 'accounts';
    let currentTimeRange = 'month';
    let cachedHeatmapData = null;
    let cachedHeatmapAccount = null;
    let cachedHeatmapAt = 0;
    let cachedHourlyData = null;
    let cachedModelsList = [];
    let cachedModelsTotal = 0;
    let showZeroPctModels = false;
    let cachedSessionsList = [];
    let selectedSessionId = null;
    let expandedTurns = new Set();
    let cachedSessionTurns = [];
    let cachedTurnsSessionId = null;

    // Native Window Dragging on Header
    const header = document.getElementById('header-bar');
    header.addEventListener('mousedown', (e) => {
      if (e.button === 0 && !e.target.closest('button, select, input, a, .tab-pill')) {
        fetch('/api/window/drag', { method: 'POST' }).catch(() => {});
      }
    });

    header.addEventListener('dblclick', (e) => {
      if (!e.target.closest('button, select, input, a, .tab-pill')) {
        fetch('/api/window/maximize', { method: 'POST' }).catch(() => {});
      }
    });

    function fmt(n) {
      return (n || 0).toLocaleString();
    }

    function getPercentColor(pct) {
      if (pct > 50) return 'swiss-text-primary';
      if (pct > 20) return 'text-amber-300';
      return 'swiss-text-accent';
    }
    function getBarColor(pct) {
      if (pct > 50) return 'var(--chart-day)';
      if (pct > 20) return 'var(--amber-text)';
      return 'var(--accent)';
    }

    // Feature 10: Crisp Swiss Toast System
    function showToast(message, type='info', duration=4000) {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      
      let accentBorder = 'border-left: 3px solid var(--border-strong);';
      let icon = '<svg class="w-4 h-4 swiss-text-secondary shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
      
      if (type === 'success') {
        accentBorder = 'border-left: 3px solid var(--sage-text);';
        icon = '<svg class="w-4 h-4 swiss-text-sage shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
      } else if (type === 'error') {
        accentBorder = 'border-left: 3px solid var(--accent);';
        icon = '<svg class="w-4 h-4 swiss-text-accent shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
      }

      toast.className = 'toast-anim pointer-events-auto px-3.5 py-2 swiss-tooltip flex items-center gap-2.5 text-xs max-w-md';
      toast.style.cssText = accentBorder;
      toast.innerHTML = `
        ${icon}
        <div class="flex-1 font-sans leading-snug swiss-text-primary">${message}</div>
      `;

      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(8px)';
        toast.style.transition = 'all 0.2s ease-out';
        setTimeout(() => toast.remove(), 220);
      }, duration);
    }

    // Feature 10 Action: Trigger DB Backup
    async function triggerDbBackup() {
      showToast('Initiating SQLite database backup...', 'info', 2000);
      try {
        const res = await fetch('/api/backup/db', { method: 'POST' });
        const d = await res.json();
        if (d && d.ok) {
          const sizeKb = d.size_bytes ? ` (${(d.size_bytes / 1024 / 1024).toFixed(2)} MB)` : '';
          const loc = d.path || d.filename || 'database.db';
          showToast(`Snapshot saved: <strong>${loc}</strong>${sizeKb}`, 'success', 5500);
        } else {
          showToast(`Backup error: ${d.error || 'Unknown'}`, 'error', 4500);
        }
      } catch (e) {
        showToast(`Failed to trigger DB backup: ${e.message}`, 'error', 4500);
      }
    }

    // Feature 10 Action: Open Executive Report
    function openExecutiveReport() {
      const sel = document.getElementById('analytics-account-select');
      const acc = sel ? sel.value : 'all';
      showToast('Opening executive report in browser...', 'info', 2500);
      window.open(`/api/export/report?range=${currentTimeRange}&account=${encodeURIComponent(acc)}`, '_blank');
    }

    function switchTab(tabId) {
      currentTab = tabId;
      document.querySelectorAll('.tab-pill').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById('tab-' + tabId);
      if (activeBtn) activeBtn.classList.add('active');

      ['accounts', 'analytics', 'sessions'].forEach(id => {
        const el = document.getElementById('page-' + id);
        if (!el) return;
        const show = (id === tabId);
        el.classList.toggle('hidden', !show);
        if (show) {
          el.classList.remove('panel-fade');
          void el.offsetWidth;
          el.classList.add('panel-fade');
        }
      });

      if (tabId === 'analytics') {
        loadAnalytics();
      } else if (tabId === 'sessions') {
        loadFleetSessions();
      }
    }

    function renderQuotaRow(label, bucket) {
      const b = bucket || {};
      const rem = typeof b.remaining === 'number' ? b.remaining : 100.0;
      const delta = b.resetDelta || 'Ready';
      const localTarget = b.resetLocalTime || '';

      return `
        <div class="space-y-1">
          <div class="flex items-center justify-between text-xs leading-none">
            <span class="swiss-text-secondary font-medium text-[11px] whitespace-nowrap shrink-0">${label}</span>
            <span class="${getPercentColor(rem)} font-bold font-mono text-xs">${rem.toFixed(0)}%</span>
          </div>
          <div class="w-full overflow-hidden my-1" style="height: 4px; background-color: var(--bg-well); border-radius: 1px;">
            <div class="quota-bar-fill h-full" style="width: ${Math.max(2, rem)}%; background-color: ${getBarColor(rem)}; border-radius: 1px;"></div>
          </div>
          <div class="flex items-center justify-between text-[9.5px] font-mono swiss-text-muted leading-none">
            <span class="swiss-text-muted flex items-center shrink-0" title="Time remaining until reset">
              <svg class="w-2.5 h-2.5 swiss-text-muted mr-1.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              <span>${delta}</span>
            </span>
            <span class="swiss-text-muted font-medium whitespace-nowrap ml-1 text-right truncate" title="${localTarget ? 'Exact reset time: ' + localTarget : ''}">
              ${localTarget || 'Immediate'}
            </span>
          </div>
        </div>
      `;
    }

    function renderAccounts() {
      if (!currentState) return;
      const active = currentState.active;
      const accounts = currentState.accounts || [];
      const quotas = currentState.quotas || {};
      const best = currentState.best;
      const recommendations = currentState.recommendations || {};

      document.getElementById('active-account-text').innerText = active;
      document.getElementById('active-acc-display').innerText = active;
      document.getElementById('acc-count-badge').innerText = accounts.length;

      const grid = document.getElementById('accounts-grid');
      grid.innerHTML = '';

      accounts.forEach(acc => {
        const isActive = acc === active;
        const q = quotas[acc] || {};
        const gemini = q.gemini || {};
        const claude = q.claude || {};
        const rec = recommendations[acc] || {};

        const card = document.createElement('div');
        card.className = `${isActive ? 'acc-card acc-card-active' : 'acc-card'} p-4 flex flex-col justify-between min-h-[224px]`;

        let badgeHtml = '';
        const badgeLabel = rec.badge_label || (isActive ? 'Active' : (acc === best ? 'Recommended' : 'Standby'));
        const badgeColor = rec.badge_color || (isActive ? 'emerald' : (acc === best ? 'white' : 'gray'));
        const reasonText = rec.reason || (isActive ? 'Active • Quota Healthy' : 'Standby • Ready');

        if (badgeColor === 'emerald') {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium swiss-text-sage font-mono">
            <span class="status-dot w-1.5 h-1.5 mr-1.5 inline-block shrink-0" style="background-color: var(--sage-text); border-radius: 1px;" aria-hidden="true"></span><span>${badgeLabel}</span>
          </span>`;
        } else if (badgeColor === 'blue' || badgeColor === 'white') {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium swiss-text-primary font-mono">
            <span class="status-dot w-1.5 h-1.5 mr-1.5 inline-block shrink-0" style="background-color: var(--text-primary); border-radius: 1px;" aria-hidden="true"></span><span>${badgeLabel}</span>
          </span>`;
        } else if (badgeColor === 'amber') {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium text-amber-300 font-mono">
            <span class="status-dot w-1.5 h-1.5 mr-1.5 inline-block shrink-0" style="background-color: var(--amber-text); border-radius: 1px;" aria-hidden="true"></span><span>${badgeLabel}</span>
          </span>`;
        } else {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium swiss-text-muted font-mono">
            <span class="status-dot w-1.5 h-1.5 mr-1.5 inline-block shrink-0" style="background-color: var(--text-muted); border-radius: 1px;" aria-hidden="true"></span><span>${badgeLabel}</span>
          </span>`;
        }

        let actionBtn = '';
        if (isActive) {
          actionBtn = `<span class="swiss-badge swiss-badge-sage h-6 px-2.5 flex items-center justify-center cursor-default shrink-0">In Use</span>`;
        } else {
          actionBtn = `<button type="button" onclick="switchAccount('${acc}')" class="swiss-btn-accent h-6 px-2.5 text-[11px] font-semibold flex items-center shrink-0">
            <span class="mr-1.5">Switch</span>
            <svg class="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </button>`;
        }

        let deleteBtn = '';
        if (!isActive) {
          deleteBtn = `<button type="button" onclick="deleteAccount('${acc}')" title="Delete Account" aria-label="Delete ${acc}" class="swiss-btn h-6 w-6 swiss-text-muted flex items-center justify-center shrink-0">
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>`;
        }

        const isDup = q.is_duplicate || (q.google_account && q.google_account !== acc);
        let dupWarning = '';
        if (isDup) {
          const linkedTo = q.duplicate_of || q.google_account || 'another account';
          dupWarning = `
            <div class="px-2 py-1.5 text-[10px] font-mono flex items-center gap-1.5 mt-1" style="background-color: var(--amber-bg); border: 1px solid var(--amber-border); border-radius: 2px; color: var(--amber-text);">
              <svg class="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <div class="truncate">
                <span>Linked to <strong class="swiss-text-primary">${linkedTo}</strong></span>
                <span class="text-[9px] block font-sans swiss-text-secondary">Shared quota • Re-enroll to isolate</span>
              </div>
            </div>
          `;
        }

        card.innerHTML = `
          <div class="border-b border-hairline pb-2.5 space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center min-w-0 flex-1">
                <div class="w-6 h-6 swiss-well flex items-center justify-center swiss-text-primary shrink-0 mr-2.5">
                  <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                </div>
                <span class="font-mono font-semibold text-xs swiss-text-primary truncate min-w-0 tracking-tight" title="${acc}">${acc}</span>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                ${actionBtn}
                ${deleteBtn}
              </div>
            </div>
            <div class="flex items-center justify-between text-[10.5px] min-h-[18px]">
              ${badgeHtml}
              <span class="text-[9.5px] font-mono swiss-text-muted truncate max-w-[200px]" title="${reasonText}">${reasonText}</span>
            </div>
            ${dupWarning}
          </div>

          <!-- 2-Column Limits Grid -->
          <div class="grid grid-cols-2 gap-3 pt-2 divide-x divide-hairline">
            <div class="space-y-2">
              <div class="flex items-center swiss-micro-label">
                <span class="status-dot w-1.5 h-1.5 mr-1.5 inline-block shrink-0" style="background-color: var(--accent); border-radius: 1px;" aria-hidden="true"></span>
                <span>Gemini</span>
              </div>
              ${renderQuotaRow('5h Cycle', gemini['5h'])}
              ${renderQuotaRow('Weekly', gemini['weekly'])}
            </div>

            <div class="space-y-2 pl-3">
              <div class="flex items-center swiss-micro-label">
                <span class="status-dot w-1.5 h-1.5 mr-1.5 inline-block shrink-0" style="background-color: var(--chart-day); border-radius: 1px;" aria-hidden="true"></span>
                <span>Claude &amp; GPT</span>
              </div>
              ${renderQuotaRow('5h Cycle', claude['5h'])}
              ${renderQuotaRow('Weekly', claude['weekly'])}
            </div>
          </div>
        `;
        grid.appendChild(card);
      });

      // Populate Account Selector in Analytics Tab only if changed
      const sel = document.getElementById('analytics-account-select');
      const curVal = sel.value;
      const existingOptions = Array.from(sel.options).map(o => o.value).filter(v => v !== 'all');
      const accountsMatch = existingOptions.length === accounts.length && accounts.every((a, i) => existingOptions[i] === a);
      if (!accountsMatch) {
        sel.innerHTML = '<option value="all">All Accounts (Combined)</option>';
        accounts.forEach(a => {
          const opt = document.createElement('option');
          opt.value = a;
          opt.innerText = a;
          sel.appendChild(opt);
        });
        if (curVal && (curVal === 'all' || accounts.includes(curVal))) {
          sel.value = curVal;
        }
      }
    }

    async function switchAccount(email, force=false) {
      try {
        const res = await fetch('/api/switch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({email, force})
        });
        const d = await res.json();
        if (d.ok) {
          const extra = d.restarted ? ' (Restarting Antigravity IDE...)' : '';
          showToast(`Active account switched to <strong>${email}</strong>${extra}`, 'success');
          await fetchStatus(true);
        } else if (d.ai_generating && !force) {
          if (confirm('Antigravity AI is currently generating a response. Switching now will restart the IDE and interrupt it. Switch anyway?')) {
            return switchAccount(email, true);
          }
          showToast('Switch cancelled to protect active AI generation', 'info');
        } else {
          showToast('Switch error: ' + (d.error || 'Unknown'), 'error');
        }
      } catch (e) {
        showToast('Switch failed: ' + e.message, 'error');
      }
    }

    async function deleteAccount(email) {
      if (!confirm(`Are you sure you want to remove ${email} from Antigravity Control Center?`)) return;
      try {
        const res = await fetch('/api/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({email})
        });
        const d = await res.json();
        if (d.ok) {
          showToast(`Account ${email} removed`, 'info');
          await fetchStatus(true);
        } else {
          showToast('Delete blocked: ' + (d.error || 'Unknown error'), 'error');
        }
      } catch (e) {
        showToast('Delete failed: ' + e.message, 'error');
      }
    }

    async function refreshAllQuotas(force=true) {
      const icon = document.getElementById('refresh-icon');
      if (icon) icon.classList.add('animate-spin');
      try {
        const res = await fetch('/api/refresh-quotas?force=' + (force ? '1' : '0'));
        const d = await res.json();
        if (d && d.quotas) {
          currentState.quotas = d.quotas;
          currentState.best = d.best;
          renderAccounts();
          showToast('Quotas refreshed successfully', 'success', 2500);
        }
      } catch (e) {
        console.error('Refresh error:', e);
      } finally {
        if (icon) setTimeout(() => icon.classList.remove('animate-spin'), 400);
      }
    }

    async function toggleAutopilot() {
      const cur = currentState ? currentState.autopilot : false;
      const res = await fetch('/api/toggle-autopilot', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enable: !cur})
      });
      const d = await res.json();
      if (currentState) {
        currentState.autopilot = d.autopilot;
        currentState.autopilot_status = d.autopilot ? 'Active (Monitoring)' : 'OFF';
      }
      updateAutopilotUI();
      showToast(`Auto-Pilot turned <strong>${d.autopilot ? 'ON' : 'OFF'}</strong>`, d.autopilot ? 'success' : 'info');
    }

    function updateAutopilotUI() {
      const on = currentState ? currentState.autopilot : false;
      const statusText = (currentState && currentState.autopilot_status) ? currentState.autopilot_status : (on ? 'Active (Monitoring)' : 'OFF');
      const textElem = document.getElementById('autopilot-text');
      const dotElem = document.getElementById('autopilot-dot');
      const detailElem = document.getElementById('autopilot-detail');

      if (textElem) {
        if (!on) {
          textElem.innerText = 'OFF';
        } else if (statusText.startsWith('Waiting')) {
          textElem.innerText = 'WAITING IDLE';
        } else if (statusText.startsWith('Switching')) {
          textElem.innerText = 'SWITCHING...';
        } else if (statusText.startsWith('Cooldown')) {
          textElem.innerText = 'COOLDOWN';
        } else {
          textElem.innerText = 'ARMED';
        }
        textElem.title = statusText;
      }
      if (dotElem) {
        if (!on) {
          dotElem.className = 'w-1.5 h-1.5 rounded-full bg-gray-600 shrink-0';
        } else if (statusText.startsWith('Waiting')) {
          dotElem.className = 'w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0';
        } else if (statusText.startsWith('Switching')) {
          dotElem.className = 'w-1.5 h-1.5 rounded-full bg-white animate-pulse shrink-0';
        } else {
          dotElem.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0';
        }
      }
      if (detailElem) {
        if (on && statusText && statusText !== 'OFF' && statusText !== 'Active (Monitoring)' && statusText !== 'Idle (Monitoring)') {
          detailElem.innerText = statusText;
          detailElem.title = statusText;
          detailElem.classList.remove('hidden');
        } else {
          detailElem.classList.add('hidden');
        }
      }
    }

    async function fetchStatus(forceRefresh=false) {
      try {
        const res = await fetch('/api/status' + (forceRefresh ? '?refresh=1' : ''));
        currentState = await res.json();
        try { localStorage.setItem('ag_last_status', JSON.stringify(currentState)); } catch (e) {}
        renderAccounts();
        updateAutopilotUI();

        if (currentState.burn_rate !== undefined) {
          const tpm = currentState.burn_rate || 0;
          const tps = currentState.tokens_per_sec !== undefined ? currentState.tokens_per_sec : Number((tpm / 60.0).toFixed(1));
          document.getElementById('top-burn-rate').innerText = `${tps} tok/s (${fmt(tpm)}/m)`;
          const statTps = document.getElementById('stat-tokens-per-sec');
          if (statTps) statTps.innerText = `${tps} tok/s`;
          const statTpm = document.getElementById('stat-tokens-per-min');
          if (statTpm) statTpm.innerText = `${fmt(tpm)} tok/min total burn`;
        }

        if (currentState.logs) {
          const lb = document.getElementById('system-logs-box');
          lb.innerHTML = currentState.logs.map(l => `<div>${l}</div>`).join('') || '<div class="text-gray-600">No logs yet.</div>';
        }

        if (currentTab === 'analytics') {
          loadAnalytics();
        }
      } catch (e) {
        console.error('Fetch status error:', e);
      }
    }

    function setTimeRange(r) {
      currentTimeRange = r;
      document.querySelectorAll('.time-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.range === r);
      });
      loadAnalytics();
    }

    // Main Analytics Tab Loader
    function setOptimizerStatusBadge(el, isActive, activeLabel = 'Active', idleLabel = 'Idle') {
      if (!el) return;
      if (isActive) {
        el.innerHTML = `<span class="status-dot w-1.5 h-1.5 shrink-0" style="background-color: var(--sage-text); border-radius: 1px;" aria-hidden="true"></span><span>${activeLabel}</span>`;
        el.className = 'swiss-badge flex items-center gap-1 swiss-text-primary';
      } else {
        el.innerHTML = idleLabel;
        el.className = 'swiss-badge flex items-center gap-1 swiss-text-muted';
      }
    }

    async function loadContextModeData() {
      try {
        const res = await fetch('/api/context-mode/stats');
        const d = await res.json();
        setOptimizerStatusBadge(document.getElementById('cm-status-badge'), Boolean(d.active));
        if (document.getElementById('cm-reduction-pct')) {
          const pct = d.reduction_pct || 0;
          const pctStr = (pct >= 99 && pct < 100) ? pct.toFixed(2) : pct.toFixed(1);
          document.getElementById('cm-reduction-pct').innerText = `${pctStr}%`;
        }
        if (document.getElementById('cm-tokens-saved')) {
          const tok = d.tokens_saved || 0;
          document.getElementById('cm-tokens-saved').innerText = tok > 0 ? `~${fmt(tok)}` : '0';
        }
        const cmSavedCell = document.getElementById('cm-saved-cell');
        if (cmSavedCell) {
          const mb = ((d.bytes_sandboxed || 0) / (1024 * 1024)).toFixed(2);
          cmSavedCell.title = `Estimated ~${fmt(d.tokens_saved || 0)} prompt tokens kept out of context (${mb} MB suppressed output ÷ 4 bytes/tok, single-turn lower bound)`;
        }
        if (document.getElementById('cm-bytes-sandboxed')) {
          const mb = ((d.bytes_sandboxed || 0) / (1024 * 1024)).toFixed(1);
          document.getElementById('cm-bytes-sandboxed').innerText = `${mb} MB`;
        }
        if (document.getElementById('cm-total-calls')) {
          document.getElementById('cm-total-calls').innerText = fmt(d.total_calls || 0);
        }
        if (document.getElementById('cm-calls-detail')) {
          const tools = Object.entries(d.by_tool || {}).map(([t, info]) => `${t}: ${info.calls}`).join(' · ');
          document.getElementById('cm-calls-detail').innerText = tools || 'No intercepted calls';
        }
        if (document.getElementById('cm-last-updated') && d.last_updated) {
          document.getElementById('cm-last-updated').innerText = `Last sync: ${d.last_updated}`;
        }
        renderContextModeDaily(d);
      } catch (e) {
        console.error('Failed to load context-mode stats:', e);
      }
    }

    const AGY_FAST_SHORT_NAMES = {
      batch_search: 'search',
      apply_edits: 'edit',
      quick_outline: 'outline',
      read_slices: 'slice',
      run_checks: 'check'
    };

    async function loadAgyFastData() {
      try {
        const res = await fetch('/api/agy-fast/stats');
        const d = await res.json();

        const verBadge = document.getElementById('af-version-badge');
        if (verBadge) {
          verBadge.innerText = d.version ? `v${d.version}` : 'Not Installed';
          const modeLabel = d.tool_loading && d.tool_loading !== 'unknown' ? d.tool_loading : 'mcp';
          verBadge.title = d.installed
            ? `agy-fast v${d.version || '--'} (${modeLabel} mode · hook ${d.hook_ready ? 'ok' : 'missing'})`
            : 'agy-fast plugin not detected';
        }

        const statusLabel = d.active ? 'Active' : (d.installed ? 'Ready' : 'Offline');
        setOptimizerStatusBadge(document.getElementById('af-status-badge'), Boolean(d.active), statusLabel, statusLabel);

        const batchBadge = document.getElementById('af-batch-badge');
        if (batchBadge) {
          const mult = Number(d.batch_multiplier || 0);
          batchBadge.innerText = `${mult.toFixed(1)}× batch`;
        }

        if (document.getElementById('af-tokens-saved')) {
          const tok = d.tokens_saved || 0;
          document.getElementById('af-tokens-saved').innerText = tok > 0 ? `~${fmt(tok)}` : '0';
        }
        const afSavedCell = document.getElementById('af-saved-cell');
        if (afSavedCell) {
          afSavedCell.title = `Conservative uncached tokens saved: ~${fmt(d.outline_tokens_saved || 0)} tok (outline file-reads avoided) + ~${fmt(d.turn_tokens_saved || 0)} tok (collapsed turn output) · Plus ~${fmt(d.cache_reads_avoided || 0)} cached prefix re-reads avoided`;
        }
        if (document.getElementById('af-batched-ops')) {
          document.getElementById('af-batched-ops').innerText = fmt(d.batched_ops || 0);
        }
        if (document.getElementById('af-turns-saved')) {
          document.getElementById('af-turns-saved').innerText = fmt(d.turns_saved || 0);
        }
        if (document.getElementById('af-total-calls')) {
          document.getElementById('af-total-calls').innerText = fmt(d.total_calls || 0);
        }

        if (document.getElementById('af-calls-detail')) {
          const tools = Object.entries(d.by_tool || {})
            .map(([t, info]) => `${AGY_FAST_SHORT_NAMES[t] || t}: ${info.calls}`)
            .join(' · ');
          document.getElementById('af-calls-detail').innerText = tools || (d.installed ? 'Ready for batched MCP calls' : 'Plugin not installed');
        }

        const healthEl = document.getElementById('af-health-detail');
        if (healthEl) {
          const h = d.health || {};
          const spills = h.spills || 0;
          const errs = (h.errors || 0) + (h.corrupted_args || 0);
          const sessFast = d.sessions_with_fast || 0;
          const snaps = d.sessions_with_snapshot || 0;
          healthEl.innerText = errs > 0
            ? `${sessFast} sess · ${spills} spills · ${errs} err`
            : `${sessFast} sess · ${snaps} snap · ${spills} spills`;
          const speedTip = (d.with_fast_tps > 0 && d.baseline_tps > 0)
            ? ` · ${d.with_fast_tps} vs ${d.baseline_tps} tok/s`
            : '';
          healthEl.title = `Sessions: ${sessFast}/${d.total_sessions || 0} · Snapshots: ${snaps} · Spills: ${spills} · Errors: ${h.errors || 0} · Corrupted args: ${h.corrupted_args || 0}${speedTip}`;
        }

        renderAgyFastDaily(d);
      } catch (e) {
        console.error('Failed to load agy-fast stats:', e);
      }
    }

    function formatShortDay(isoDate) {
      if (!isoDate) return '--';
      const parts = isoDate.split('-');
      if (parts.length !== 3) return isoDate;
      const dt = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
      return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    function formatFullDay(isoDate) {
      if (!isoDate) return '--';
      const parts = isoDate.split('-');
      if (parts.length !== 3) return isoDate;
      const dt = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
      return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function formatShortMonth(ym, includeYear = false) {
      if (!ym) return '--';
      const parts = ym.split('-');
      if (parts.length < 2) return ym;
      const dt = new Date(Number(parts[0]), Number(parts[1]) - 1, 1);
      const mon = dt.toLocaleDateString('en-US', { month: 'short' });
      return includeYear ? `${mon} '${String(parts[0]).slice(-2)}` : mon;
    }

    function formatFullMonth(ym) {
      if (!ym) return '--';
      const parts = ym.split('-');
      if (parts.length < 2) return ym;
      const dt = new Date(Number(parts[0]), Number(parts[1]) - 1, 1);
      return dt.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    }

    function renderOptimizerActivityDaily(d, opts) {
      const container = document.getElementById(opts.containerId);
      if (!container) return;
      container.innerHTML = '';

      const daily = Array.isArray(d.daily) ? d.daily : [];
      const totalDays = d.total_days || daily.length;
      const activeDays = d.active_days || 0;
      const peakDay = d.peak_day;

      const titleEl = document.getElementById(opts.titleId);
      const activeBadge = document.getElementById(opts.activeId);
      const peakBadge = document.getElementById(opts.peakId);

      if (daily.length === 0) {
        if (titleEl) titleEl.innerText = opts.dayTitle;
        if (activeBadge) activeBadge.innerText = '0d active';
        if (peakBadge) peakBadge.innerText = 'Peak: --';
        container.innerHTML = `<div class="w-full h-full flex items-center justify-center text-[10px] font-mono swiss-text-muted">${opts.emptyText}</div>`;
        return;
      }

      // Switch automatically to monthly rollup after 6 months (>180d) or when daily columns get crowded (<4px/day)
      const containerWidth = container.clientWidth || 0;
      const isCrowded = containerWidth > 0 && (containerWidth / daily.length) < 4;
      const useMonthly = daily.length > 180 || isCrowded;

      let series = [];
      let peakKey = peakDay;

      if (useMonthly) {
        const monthMap = new Map();
        daily.forEach(item => {
          const ym = (item.date || '').slice(0, 7);
          if (!ym) return;
          if (!monthMap.has(ym)) {
            monthMap.set(ym, { key: ym, calls: 0, sessions: 0, secMetric: 0, terMetric: 0, quaMetric: 0, active_days: 0 });
          }
          const m = monthMap.get(ym);
          const c = item.calls || 0;
          const s = item.sessions || 0;
          m.calls += c;
          m.sessions += s;
          m.secMetric += (item[opts.secondaryField] || 0);
          m.terMetric += (opts.tertiaryField ? (item[opts.tertiaryField] || 0) : 0);
          m.quaMetric += (opts.quaternaryField ? (item[opts.quaternaryField] || 0) : 0);
          if (c > 0 || s > 0) m.active_days += 1;
        });
        series = Array.from(monthMap.values());

        let peakScore = 0;
        let activeMonths = 0;
        peakKey = null;
        series.forEach(m => {
          if (m.calls > 0 || m.sessions > 0) activeMonths += 1;
          const score = m.calls > 0 ? m.calls : (m.sessions * 0.01);
          if (score > peakScore) {
            peakScore = score;
            peakKey = m.key;
          }
        });

        const spansMultiYear = series.length > 1 && series[0].key.slice(0, 4) !== series[series.length - 1].key.slice(0, 4);
        if (titleEl) titleEl.innerText = opts.monthTitle;
        if (activeBadge) activeBadge.innerText = `${activeMonths}m/${series.length}m active`;
        if (peakBadge) peakBadge.innerText = peakKey ? `Peak: ${formatShortMonth(peakKey, spansMultiYear)}` : 'Peak: --';
      } else {
        series = daily.map(item => ({
          key: item.date,
          calls: item.calls || 0,
          sessions: item.sessions || 0,
          secMetric: item[opts.secondaryField] || 0,
          terMetric: opts.tertiaryField ? (item[opts.tertiaryField] || 0) : 0,
          quaMetric: opts.quaternaryField ? (item[opts.quaternaryField] || 0) : 0,
          active_days: ((item.calls || 0) > 0 || (item.sessions || 0) > 0) ? 1 : 0
        }));
        if (titleEl) titleEl.innerText = opts.dayTitle;
        if (activeBadge) activeBadge.innerText = totalDays > 0 ? `${activeDays}d/${totalDays}d active` : '0d active';
        if (peakBadge) peakBadge.innerText = peakDay ? `Peak: ${formatShortDay(peakDay)}` : 'Peak: --';
      }

      let maxVal = 0;
      series.forEach(item => {
        if (item.calls > maxVal) maxVal = item.calls;
      });
      const useCalls = maxVal > 0;
      if (!useCalls) {
        series.forEach(item => {
          if (item.sessions > maxVal) maxVal = item.sessions;
        });
      }
      const denom = Math.max(1, maxVal);

      const n = series.length;
      const labelIndices = new Set([0, n - 1]);
      if (useMonthly && n <= 12) {
        for (let i = 0; i < n; i++) labelIndices.add(i);
      } else if (n >= 6) {
        const steps = Math.min(4, Math.floor(n / 4));
        for (let s = 1; s < steps; s++) {
          const idx = Math.round((s * (n - 1)) / steps);
          if (idx > 1 && idx < n - 2) labelIndices.add(idx);
        }
      }

      const spansMultiYear = useMonthly && n > 1 && series[0].key.slice(0, 4) !== series[n - 1].key.slice(0, 4);
      const colPadding = useMonthly ? (n > 24 ? '0 1px' : '0 2px') : (n > 60 ? '0 0.5px' : n > 35 ? '0 1px' : '0 1.5px');
      const barMinWidth = useMonthly ? '4px' : (n > 90 ? '1px' : '2px');
      const barMaxWidth = useMonthly ? '18px' : (n === 1 ? '22px' : n <= 7 ? '16px' : '10px');
      const maxBarPx = 38;
      const frag = document.createDocumentFragment();

      series.forEach((item, idx) => {
        const calls = item.calls;
        const sessions = item.sessions;
        const metric = useCalls ? calls : sessions;

        let barPx = 2;
        let barCls = opts.barEmpty;
        if (calls > 0) {
          barPx = Math.max(5, Math.round((metric / denom) * maxBarPx));
          barCls = (item.key === peakKey) ? opts.barPeak : opts.barActive;
        } else if (sessions > 0) {
          barPx = Math.max(4, useCalls ? 6 : Math.round((sessions / denom) * maxBarPx));
          barCls = opts.barIdle;
        }

        const col = document.createElement('div');
        col.className = 'swiss-chart-col group';
        col.style.padding = colPadding;

        const tip = document.createElement('div');
        tip.className = 'pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 absolute -top-12 left-1/2 -translate-x-1/2 px-2 py-1 swiss-tooltip text-[10px] font-mono whitespace-nowrap z-30 flex flex-col items-center gap-0.5';
        const tipTitle = useMonthly ? formatFullMonth(item.key) : formatFullDay(item.key);
        const tipSub = useMonthly
          ? `${item.active_days}d · ${sessions} sess`
          : `${sessions} sess`;
        tip.innerHTML = opts.renderTooltip(tipTitle, calls, tipSub, item);

        const bar = document.createElement('div');
        bar.className = `swiss-bar ${barCls}`;
        bar.style.height = `${barPx}px`;
        bar.style.maxWidth = barMaxWidth;
        bar.style.minWidth = barMinWidth;

        const lbl = document.createElement('div');
        const alignCls = n === 1 ? 'justify-center' : (idx === 0) ? 'justify-start' : (idx === n - 1) ? 'justify-end' : 'justify-center';
        lbl.className = `h-3.5 flex items-center ${alignCls} w-full select-none mt-0.5 overflow-visible`;
        if (labelIndices.has(idx)) {
          const shortLbl = useMonthly
            ? formatShortMonth(item.key, spansMultiYear && (idx === 0 || idx === n - 1 || item.key.endsWith('-01')))
            : formatShortDay(item.key);
          lbl.innerHTML = `<span class="text-[8.5px] font-mono swiss-text-muted leading-none whitespace-nowrap">${shortLbl}</span>`;
        } else {
          lbl.innerHTML = `<span class="text-[7px] swiss-text-muted leading-none">·</span>`;
        }

        col.appendChild(tip);
        col.appendChild(bar);
        col.appendChild(lbl);
        frag.appendChild(col);
      });
      container.appendChild(frag);
    }

    function renderContextModeDaily(d) {
      renderOptimizerActivityDaily(d, {
        containerId: 'cm-daily-bars',
        titleId: 'cm-chart-title',
        activeId: 'cm-active-days-label',
        peakId: 'cm-peak-day-badge',
        dayTitle: 'Shield Activity by Day (All Time)',
        monthTitle: 'Shield Activity by Month (All Time)',
        emptyText: 'No context-mode history yet',
        secondaryField: 'tokens_saved',
        barPeak: 'cm-bar-peak',
        barActive: 'cm-bar-active',
        barIdle: 'cm-bar-idle',
        barEmpty: 'cm-bar-empty',
        renderTooltip: (title, calls, tipSub, item) => `
          <div class="font-bold swiss-text-primary">${title}</div>
          <div class="swiss-text-sage font-semibold">${fmt(calls)} calls <span class="swiss-text-muted font-normal">(${tipSub})</span></div>
          <div class="swiss-text-secondary text-[9px]">${fmt(item.secMetric)} tok shielded</div>
        `
      });
    }

    function renderAgyFastDaily(d) {
      renderOptimizerActivityDaily(d, {
        containerId: 'af-daily-bars',
        titleId: 'af-chart-title',
        activeId: 'af-active-days-label',
        peakId: 'af-peak-day-badge',
        dayTitle: 'Fast Activity by Day (All Time)',
        monthTitle: 'Fast Activity by Month (All Time)',
        emptyText: d.installed ? 'No agy-fast calls logged yet' : 'agy-fast plugin not installed',
        secondaryField: 'batched_ops',
        tertiaryField: 'turns_saved',
        quaternaryField: 'tokens_saved',
        barPeak: 'af-bar-peak',
        barActive: 'af-bar-active',
        barIdle: 'af-bar-idle',
        barEmpty: 'af-bar-empty',
        renderTooltip: (title, calls, tipSub, item) => `
          <div class="font-bold swiss-text-primary">${title}</div>
          <div class="swiss-text-accent font-semibold">${fmt(calls)} calls <span class="swiss-text-muted font-normal">(${tipSub})</span></div>
          <div class="swiss-text-secondary text-[9px]">${fmt(item.secMetric)} ops · ${fmt(item.terMetric)} turns · ~${fmt(item.quaMetric)} tok saved</div>
        `
      });
    }

async function loadAnalytics() {
      const acc = document.getElementById('analytics-account-select').value;
      try {
        const res = await fetch(`/api/tokens/summary?range=${currentTimeRange}&account=${encodeURIComponent(acc)}`);
        const data = await res.json();
        renderAnalyticsData(data);
      } catch (e) {
        console.error('Failed to load token analytics:', e);
      }

      // Feature 1: Load Activity Heatmap (Yearly/365d)
      loadHeatmapData(acc);

      // Feature 5: Load 24-Hour Productivity Data
      loadHourlyData(acc);

      // Optimizer Live Stats (context-mode + agy-fast)
      loadContextModeData();
      loadAgyFastData();
    }

    function renderAnalyticsData(data) {
      const tot = data.totals || {};
      const totalTokens = tot.total_tokens || 0;
      const inp = tot.total_in || 0;
      const outp = tot.total_out || 0;
      const cache = tot.total_cache || 0;

      // Card Totals
      document.getElementById('stat-total-tokens').innerText = fmt(totalTokens);
      document.getElementById('stat-turns-count').innerText = `${fmt(tot.total_steps || 0)} turns logged`;
      document.getElementById('stat-sessions-count').innerText = fmt(tot.total_sessions || 0);
      document.getElementById('stat-input-tokens').innerText = fmt(inp);
      document.getElementById('stat-output-tokens').innerText = fmt(outp);
      document.getElementById('stat-cache-tokens').innerText = fmt(cache);

      // Feature 3: Cache Hit Ratio & Gauge Ring
      const cacheRatio = (inp + cache) > 0 ? ((cache / (inp + cache)) * 100) : 0;
      const cacheRatioVal = typeof tot.cache_hit_rate === 'number' ? tot.cache_hit_rate : cacheRatio;
      document.getElementById('stat-cache-ratio').innerText = `${cacheRatioVal.toFixed(1)}%`;
      document.getElementById('stat-quota-saved').innerText = `${fmt(cache)} tok`;

      // Context Window Average
      const avgCtx = tot.total_sessions > 0 ? Math.round((inp + cache) / Math.max(1, tot.total_steps || 1)) : 0;
      document.getElementById('stat-avg-context').innerText = fmt(avgCtx);

      // Input vs Output Percentages
      const inPct = totalTokens > 0 ? ((inp / totalTokens) * 100).toFixed(1) : 0;
      const outPct = totalTokens > 0 ? ((outp / totalTokens) * 100).toFixed(1) : 0;
      document.getElementById('stat-input-pct').innerText = `${inPct}%`;
      document.getElementById('stat-output-pct').innerText = `${outPct}%`;
      document.getElementById('stat-input-bar').style.width = `${inPct}%`;
      document.getElementById('stat-output-bar').style.width = `${outPct}%`;

      const ioRatio = outp > 0 ? (inp / outp).toFixed(1) : (inp > 0 ? 'inf' : '1.0');
      document.getElementById('stat-io-ratio').innerText = `${ioRatio} : 1`;

      // Burn rate velocity
      const burn = data.burn_rate || {};
      const tpm = burn.tokens_per_min || 0;
      const tps = burn.tokens_per_sec !== undefined ? burn.tokens_per_sec : Number((tpm / 60.0).toFixed(1));
      const hourly = burn.tokens_last_hour !== undefined ? burn.tokens_last_hour : Math.round(tpm * 60);

      document.getElementById('top-burn-rate').innerText = `${tps} tok/s (${fmt(tpm)}/m)`;
      const statTps = document.getElementById('stat-tokens-per-sec');
      if (statTps) statTps.innerText = `${tps} tok/s`;
      const statTpm = document.getElementById('stat-tokens-per-min');
      if (statTpm) statTpm.innerText = `${fmt(tpm)} tok/min total burn`;
      const statHourly = document.getElementById('stat-hourly-burn');
      if (statHourly) statHourly.innerText = `${fmt(hourly)} tok/h`;

      // Timeline & Model Split & Events
      renderSvgChart(data.timeline || []);
      renderModelSplit(data.by_model || [], totalTokens);
      renderEventsTable(data.recent_events || []);
    }

    // Feature 1: 52-Week GitHub-style Activity Heatmap
    async function loadHeatmapData(acc, force=false) {
      const targetAcc = acc || 'all';
      const now = Date.now();
      if (!force && cachedHeatmapData && cachedHeatmapAccount === targetAcc && (now - cachedHeatmapAt < 30000)) {
        return;
      }
      try {
        const res = await fetch(`/api/tokens/heatmap?account=${encodeURIComponent(targetAcc)}`);
        let data = await res.json();
        if (data && data.heatmap) data = data.heatmap;
        if (data && data.days) data = data.days;
        cachedHeatmapData = Array.isArray(data) ? data : [];
        cachedHeatmapAccount = targetAcc;
        cachedHeatmapAt = Date.now();
        renderHeatmapGrid(cachedHeatmapData);
      } catch (e) {
        console.warn('Heatmap endpoint not ready or empty:', e);
        renderHeatmapGrid([]);
      }
    }

    function renderHeatmapGrid(daysData) {
      const container = document.getElementById('heatmap-svg-wrap');
      container.innerHTML = '';

      // Build a fast lookup map: 'YYYY-MM-DD' -> object
      const dayMap = {};
      let totalYearTokens = 0;
      let activeDaysCount = 0;

      daysData.forEach(d => {
        const dateKey = d.date || d.day;
        if (dateKey) {
          dayMap[dateKey] = d;
          totalYearTokens += (d.total_tokens || 0);
          if ((d.total_tokens || 0) > 0) activeDaysCount++;
        }
      });

      document.getElementById('heatmap-year-tokens').innerText = fmt(totalYearTokens);
      document.getElementById('heatmap-active-days').innerText = fmt(activeDaysCount);

      // Compute streak (consecutive active days backwards from today)
      let streak = 0;
      const now = new Date();
      for (let i = 0; i < 365; i++) {
        const checkDate = new Date(now.getTime() - i * 86400000);
        const y = checkDate.getFullYear();
        const m = String(checkDate.getMonth() + 1).padStart(2, '0');
        const dayStr = String(checkDate.getDate()).padStart(2, '0');
        const key = `${y}-${m}-${dayStr}`;
        const item = dayMap[key];
        if (item && item.total_tokens > 0) {
          streak++;
        } else {
          if (i === 0) continue; // Allow today to not be active yet
          break;
        }
      }
      document.getElementById('heatmap-streak').innerText = `${streak} ${streak === 1 ? 'day' : 'days'}`;

      // Build 52 weeks x 7 days grid (364 days ending today)
      const cellSize = 11;
      const cellGap = 3;
      const leftPad = 30;
      const topPad = 20;

      const endDate = new Date();
      const endDayOfWeek = endDate.getDay(); // 0..6
      const startDate = new Date(endDate.getTime() - (51 * 7 + endDayOfWeek) * 86400000);

      const maxTokens = Math.max(...daysData.map(d => d.total_tokens || 0), 50000);

      // Create SVG
      const totalWidth = leftPad + 53 * (cellSize + cellGap);
      const totalHeight = topPad + 7 * (cellSize + cellGap);
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', `0 0 ${totalWidth} ${totalHeight}`);
      svg.setAttribute('class', 'w-full h-auto overflow-visible');

      const svgFrag = document.createDocumentFragment();
      const cellInfoMap = {};

      // Month labels (enforce >= 3 week columns apart to prevent Nov/Dec collision)
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      let lastMonth = -1;
      let lastMonthCol = -99;

      // Day labels on left (monospace)
      const dayLabels = [
        { label: 'Mon', row: 1 },
        { label: 'Wed', row: 3 },
        { label: 'Fri', row: 5 }
      ];
      dayLabels.forEach(dl => {
        const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('x', '2');
        t.setAttribute('y', topPad + dl.row * (cellSize + cellGap) + cellSize - 2);
        t.setAttribute('fill', '#76736b');
        t.setAttribute('font-size', '8.5');
        t.setAttribute('font-family', '"IBM Plex Mono", "Cascadia Mono", Consolas, monospace');
        t.textContent = dl.label;
        svgFrag.appendChild(t);
      });

      // Generate week columns
      let cur = new Date(startDate.getTime());
      for (let w = 0; w < 52; w++) {
        const monthIdx = cur.getMonth();
        if (monthIdx !== lastMonth && w < 50 && (w - lastMonthCol >= 3)) {
          const mt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
          mt.setAttribute('x', leftPad + w * (cellSize + cellGap));
          mt.setAttribute('y', topPad - 6);
          mt.setAttribute('fill', '#76736b');
          mt.setAttribute('font-size', '8.5');
          mt.setAttribute('font-family', '"IBM Plex Mono", "Cascadia Mono", Consolas, monospace');
          mt.textContent = months[monthIdx];
          svgFrag.appendChild(mt);
          lastMonth = monthIdx;
          lastMonthCol = w;
        } else if (monthIdx !== lastMonth) {
          lastMonth = monthIdx;
        }

        for (let d = 0; d < 7; d++) {
          const y = cur.getFullYear();
          const m = String(cur.getMonth() + 1).padStart(2, '0');
          const dayNum = String(cur.getDate()).padStart(2, '0');
          const dateStr = `${y}-${m}-${dayNum}`;

          const dayInfo = dayMap[dateStr] || { date: dateStr, total_tokens: 0, turns: 0, top_model: 'None' };
          cellInfoMap[dateStr] = dayInfo;
          const tok = dayInfo.total_tokens || 0;

          // Swiss Studio 5-step sage scale (Levels 0-4)
          let fillColor = '#1f1e1c'; // Level 0
          let strokeColor = '#2b2a27';
          let strokeWidth = '0.5';
          if (tok > 0) {
            const ratio = tok / maxTokens;
            if (ratio < 0.15) fillColor = '#1b3b27';      // Level 1
            else if (ratio < 0.40) fillColor = '#25613d'; // Level 2
            else if (ratio < 0.70) fillColor = '#36945c'; // Level 3
            else fillColor = '#52c47e';                   // Level 4
            strokeColor = 'none';
            strokeWidth = '0';
          }

          const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('x', leftPad + w * (cellSize + cellGap));
          rect.setAttribute('y', topPad + d * (cellSize + cellGap));
          rect.setAttribute('width', cellSize);
          rect.setAttribute('height', cellSize);
          rect.setAttribute('rx', '1');
          rect.setAttribute('fill', fillColor);
          rect.setAttribute('stroke', strokeColor);
          if (strokeWidth !== '0') rect.setAttribute('stroke-width', strokeWidth);
          rect.setAttribute('class', 'hm-cell');
          rect.setAttribute('data-date', dateStr);

          svgFrag.appendChild(rect);
          cur.setDate(cur.getDate() + 1);
        }
      }

      svg.appendChild(svgFrag);

      // Single delegated tooltip handler (replaces 728 per-cell listeners)
      svg.addEventListener('mouseover', (ev) => {
        const target = ev.target;
        if (target && target.classList && target.classList.contains('hm-cell')) {
          const info = cellInfoMap[target.getAttribute('data-date')];
          if (info) showHeatmapTooltip(ev, info);
        }
      });
      svg.addEventListener('mouseout', (ev) => {
        if (ev.target && ev.target.classList && ev.target.classList.contains('hm-cell')) {
          hideHeatmapTooltip();
        }
      });
      svg.addEventListener('mouseleave', hideHeatmapTooltip);
      container.appendChild(svg);
    }

    function showHeatmapTooltip(ev, day) {
      const tip = document.getElementById('heatmap-tooltip');
      if (!tip) return;
      const rect = ev.target.getBoundingClientRect();

      const tok = day.total_tokens || 0;
      const inp = day.input_tokens || 0;
      const outp = day.output_tokens || 0;
      const turns = day.turns || 0;
      const model = day.top_model || 'None';

      tip.innerHTML = `
        <div class="swiss-text-primary font-semibold text-xs border-b border-hairline pb-1 mb-1">${day.date}</div>
        <div class="swiss-text-primary font-bold">${fmt(tok)} tokens <span class="swiss-text-muted font-normal">(${fmt(turns)} turns)</span></div>
        <div class="swiss-text-secondary text-[10px]">In: ${fmt(inp)} • Out: ${fmt(outp)}</div>
        <div class="swiss-text-muted text-[10px] truncate max-w-[170px]">Top: <span class="swiss-text-primary">${model}</span></div>
      `;

      const tipWidth = 190;
      const tipHeight = 78;
      let left = rect.left + (rect.width / 2) - (tipWidth / 2);
      let top = rect.top - tipHeight - 10;

      // Flip below if cell is too close to window top
      if (top < 12) {
        top = rect.bottom + 10;
      }
      // Clamp within horizontal viewport
      if (left < 10) left = 10;
      if (left + tipWidth > window.innerWidth - 10) {
        left = window.innerWidth - tipWidth - 10;
      }

      tip.style.left = `${Math.round(left)}px`;
      tip.style.top = `${Math.round(top)}px`;
      tip.classList.remove('hidden');
    }

    function hideHeatmapTooltip() {
      const tip = document.getElementById('heatmap-tooltip');
      if (tip) tip.classList.add('hidden');
    }

    // Feature 5: 24-Hour Productivity Radar / Hourly Chart
    async function loadHourlyData(acc) {
      try {
        const res = await fetch(`/api/tokens/hourly?account=${encodeURIComponent(acc || 'all')}&range=${currentTimeRange}`);
        let data = await res.json();
        if (data && data.hourly) data = data.hourly;
        cachedHourlyData = Array.isArray(data) ? data : [];
        renderHourlyChart(cachedHourlyData);
      } catch (e) {
        console.warn('Hourly productivity endpoint not ready:', e);
        renderHourlyChart([]);
      }
    }

    function renderHourlyChart(hourlyList) {
      const container = document.getElementById('hourly-radar-container');
      container.innerHTML = '';

      // Prepare 24 hours (0..23)
      const hourMap = {};
      let maxTokens = 1;
      let nightTokens = 0;
      let dayTokens = 0;
      let peakHour = 0;
      let peakHourTokens = -1;

      hourlyList.forEach(h => {
        const hr = h.hour;
        hourMap[hr] = h;
        const t = h.total_tokens || 0;
        if (t > maxTokens) maxTokens = t;
        if (t > peakHourTokens) {
          peakHourTokens = t;
          peakHour = hr;
        }
        if (hr >= 0 && hr < 7) nightTokens += t;
        else if (hr >= 22) nightTokens += t;
        else dayTokens += t;
      });

      const totalH = Math.max(1, nightTokens + dayTokens);
      const nightPct = Math.round((nightTokens / totalH) * 100);
      const dayPct = Math.round((dayTokens / totalH) * 100);

      const peak12 = (peakHour === 0) ? '12 AM' : (peakHour < 12) ? `${peakHour} AM` : (peakHour === 12) ? '12 PM' : `${peakHour - 12} PM`;
      const peakEndHour = (peakHour + 2) % 24;
      const peakEnd12 = (peakEndHour === 0) ? '12 AM' : (peakEndHour < 12) ? `${peakEndHour} AM` : (peakEndHour === 12) ? '12 PM' : `${peakEndHour - 12} PM`;

      const peakBadge = document.getElementById('peak-hour-badge');
      if (peakBadge) peakBadge.innerText = `Peak: ${peak12} (${String(peakHour).padStart(2, '0')}:00)`;

      const peakTok = document.getElementById('hourly-peak-tok');
      if (peakTok) peakTok.innerText = `Peak Vol: ${fmt(peakHourTokens > 0 ? peakHourTokens : 0)} tok`;

      document.getElementById('hourly-night-pct').innerText = `${nightPct}%`;
      document.getElementById('hourly-day-pct').innerText = `${dayPct}%`;
      document.getElementById('hourly-top-span').innerText = `${peak12} – ${peakEnd12}`;

      const shortLabels = {
        0: '12 AM',
        3: '3 AM',
        6: '6 AM',
        9: '9 AM',
        12: '12 PM',
        15: '3 PM',
        18: '6 PM',
        21: '9 PM'
      };

      const maxBarPx = 116;
      const frag = document.createDocumentFragment();
      for (let h = 0; h < 24; h++) {
        const item = hourMap[h] || { hour: h, total_tokens: 0, turns: 0, primary_model: 'None' };
        const tok = item.total_tokens || 0;
        const barPx = tok > 0 ? Math.max(4, Math.round((tok / maxTokens) * maxBarPx)) : 2;
        const pctOfPeak = maxTokens > 0 ? Math.round((tok / maxTokens) * 100) : 0;

        const col = document.createElement('div');
        col.className = 'swiss-chart-col group';

        const hour12 = (h === 0) ? '12:00 AM' : (h < 12) ? `${h}:00 AM` : (h === 12) ? '12:00 PM' : `${h - 12}:00 PM`;
        const hour24 = `${String(h).padStart(2, '0')}:00`;

        // Crisp Swiss hover tooltip
        const tip = document.createElement('div');
        tip.className = 'pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 absolute -top-12 left-1/2 -translate-x-1/2 px-2 py-1 swiss-tooltip text-[10px] font-mono whitespace-nowrap z-30 flex flex-col items-center gap-0.5';
        tip.innerHTML = `
          <div class="font-bold swiss-text-primary flex items-center gap-1.5 border-b border-hairline pb-0.5 mb-0.5">
            <span>${hour12}</span>
            <span class="swiss-text-muted text-[9px] font-normal">(${hour24})</span>
          </div>
          <div class="swiss-text-primary font-semibold">${fmt(tok)} tokens <span class="swiss-text-muted font-normal">(${pctOfPeak}%)</span></div>
          <div class="swiss-text-secondary text-[9px]">${item.turns || 0} prompt turns • ${item.primary_model || 'No activity'}</div>
        `;

        // Bar coloring: Peak is Signal Vermilion (#e55333), Day is #66635b, Night is #2c2b27
        let barColor = 'swiss-bar-day';
        if (h === peakHour && tok > 0) {
          barColor = 'swiss-bar-peak';
        } else if (h < 7 || h >= 22) {
          barColor = 'swiss-bar-night';
        }

        const bar = document.createElement('div');
        bar.className = `swiss-bar ${barColor}`;
        bar.style.height = `${barPx}px`;
        bar.style.maxWidth = '12px';
        bar.style.minWidth = '3px';

        const lbl = document.createElement('div');
        lbl.className = 'h-5 flex items-center justify-center w-full select-none';
        if (shortLabels[h]) {
          lbl.innerHTML = `<span class="text-[8.5px] font-mono swiss-text-muted tracking-tight whitespace-nowrap">${shortLabels[h]}</span>`;
        } else {
          lbl.innerHTML = `<span class="text-[7px] swiss-text-muted leading-none">·</span>`;
        }

        col.appendChild(tip);
        col.appendChild(bar);
        col.appendChild(lbl);
        frag.appendChild(col);
      }
      container.appendChild(frag);
    }

    function renderSvgChart(timeline) {
      const container = document.getElementById('chart-svg-container');
      container.innerHTML = '';
      if (!timeline || !timeline.length) {
        container.innerHTML = '<div class="w-full text-center text-xs swiss-text-muted py-16 font-mono">No token history recorded for this period.</div>';
        const label = document.getElementById('chart-timeline-label');
        if (label) label.innerText = 'Distribution';
        return;
      }

      const maxVal = Math.max(...timeline.map(d => d.total_tokens || 0), 1);
      const label = document.getElementById('chart-timeline-label');
      if (label) label.innerText = `Peak: ${fmt(maxVal)} tok`;

      const n = timeline.length;
      // Stride calculation for label decimation to prevent overlapping
      let stride = 1;
      if (n >= 22) stride = 4;
      else if (n >= 14) stride = 3;
      else if (n >= 8) stride = 2;

      const maxBarPx = 116;
      const frag = document.createDocumentFragment();
      timeline.forEach((item, idx) => {
        const tok = item.total_tokens || 0;
        const isPeak = tok > 0 && tok === maxVal;
        const barPx = tok > 0 ? Math.max(4, Math.round((tok / maxVal) * maxBarPx)) : 2;

        const col = document.createElement('div');
        col.className = 'swiss-chart-col group';

        // Crisp Swiss hover tooltip
        const tip = document.createElement('div');
        tip.className = 'pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 absolute -top-10 left-1/2 -translate-x-1/2 px-2 py-1 swiss-tooltip text-[10px] font-mono whitespace-nowrap z-30 flex flex-col items-center gap-0.5';
        tip.innerHTML = `
          <div class="font-semibold swiss-text-primary">${item.period}</div>
          <div class="swiss-text-secondary">${fmt(tok)} tokens (${Math.round((tok / maxVal) * 100)}%)</div>
        `;

        // Bar: Signal Vermilion for peak day, #525049 base for remaining bars (explicit px height)
        const bar = document.createElement('div');
        bar.className = `swiss-bar ${isPeak ? 'swiss-bar-peak' : 'swiss-bar-base'}`;
        bar.style.height = `${barPx}px`;
        bar.style.maxWidth = n <= 10 ? '24px' : '14px';
        bar.style.minWidth = '4px';

        // Date label decimation
        const isLabeled = (idx === 0) || (idx === n - 1) || (idx % stride === 0 && idx < n - 2);

        let displayLabel = item.period;
        if (item.period && item.period.length === 10) {
          displayLabel = item.period.slice(5); // e.g. "10-02"
        }

        const lbl = document.createElement('div');
        lbl.className = 'h-5 flex items-center justify-center w-full select-none';
        if (isLabeled) {
          lbl.innerHTML = `<span class="text-[9px] font-mono swiss-text-muted tracking-tight whitespace-nowrap">${displayLabel}</span>`;
        } else {
          lbl.innerHTML = `<span class="text-[7px] swiss-text-muted leading-none">·</span>`;
        }

        col.appendChild(tip);
        col.appendChild(bar);
        col.appendChild(lbl);
        frag.appendChild(col);
      });
      container.appendChild(frag);
    }

    function toggleZeroPctModels() {
      showZeroPctModels = !showZeroPctModels;
      renderModelSplit(cachedModelsList, cachedModelsTotal);
    }

    function renderModelSplit(models, totalTokens) {
      cachedModelsList = Array.isArray(models) ? models : [];
      cachedModelsTotal = totalTokens || 0;
      const list = document.getElementById('model-split-list');
      list.innerHTML = '';
      if (!cachedModelsList.length) {
        list.innerHTML = '<div class="text-xs swiss-text-muted font-mono">No model usage recorded.</div>';
        return;
      }

      const primaryModels = [];
      const minorModels = [];
      cachedModelsList.forEach((m, idx) => {
        const exactPct = cachedModelsTotal > 0 ? (m.total_tokens / cachedModelsTotal) * 100 : 0;
        const roundPct = Math.round(exactPct);
        const entry = { m, idx, exactPct, roundPct };
        if (roundPct >= 1 || idx === 0) {
          primaryModels.push(entry);
        } else {
          minorModels.push(entry);
        }
      });

      const visible = showZeroPctModels ? primaryModels.concat(minorModels) : primaryModels;
      const frag = document.createDocumentFragment();

      visible.forEach(({ m, idx, exactPct, roundPct }) => {
        const isTop = idx === 0;
        const pctLabel = roundPct >= 1 ? `${roundPct}%` : (exactPct >= 0.05 ? `${exactPct.toFixed(1)}%` : '<0.1%');
        const barWidth = Math.max(exactPct > 0 ? 1 : 0, Math.min(100, exactPct));
        const div = document.createElement('div');
        div.className = 'space-y-1.5';
        div.innerHTML = `
          <div class="flex items-center justify-between text-xs gap-2">
            <span class="font-mono ${isTop ? 'swiss-text-primary font-semibold' : 'swiss-text-secondary'} truncate max-w-[160px]" title="${m.model}">${m.model}</span>
            <span class="font-mono ${isTop ? 'swiss-text-primary font-semibold' : 'swiss-text-muted'} whitespace-nowrap">${fmt(m.total_tokens)} (${pctLabel})</span>
          </div>
          <div class="swiss-model-track">
            <div class="${isTop ? 'swiss-model-fill-top' : 'swiss-model-fill-rest'}" style="width: ${barWidth}%"></div>
          </div>
        `;
        frag.appendChild(div);
      });

      if (minorModels.length > 0) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'swiss-model-toggle';
        btn.onclick = toggleZeroPctModels;
        const chevron = showZeroPctModels
          ? '<svg class="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="18 15 12 9 6 15"/></svg>'
          : '<svg class="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
        btn.innerHTML = `${chevron}<span>${showZeroPctModels ? `Hide ${minorModels.length} low-usage (~0%) models` : `Show ${minorModels.length} low-usage (~0%) models`}</span>`;
        frag.appendChild(btn);
      }

      list.appendChild(frag);
    }

    function renderEventsTable(events) {
      const tbody = document.getElementById('token-events-tbody');
      tbody.innerHTML = '';
      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="py-3 text-center swiss-text-muted">No recent events found.</td></tr>';
        return;
      }
      const frag = document.createDocumentFragment();
      events.slice(0, 50).forEach(ev => {
        const tr = document.createElement('tr');
        let timeStr = '--';
        if (ev.created_at) {
          try {
            const dt = new Date(ev.created_at);
            timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          } catch(e) {
            timeStr = ev.created_at.slice(11, 19);
          }
        }
        const cacheVal = ev.cache_read_tokens || 0;
        const cacheClass = cacheVal > 0 ? 'swiss-text-accent font-semibold' : 'swiss-text-muted';
        tr.innerHTML = `
          <td class="swiss-text-muted whitespace-nowrap">${ev.day ? ev.day.slice(5) : ''} ${timeStr}</td>
          <td class="swiss-text-secondary truncate max-w-[130px]" title="${ev.model}">${ev.model}</td>
          <td class="text-right swiss-text-secondary">${fmt(ev.input_tokens)}</td>
          <td class="text-right swiss-text-secondary">${fmt(ev.output_tokens)}</td>
          <td class="text-right ${cacheClass}">${fmt(cacheVal)}</td>
          <td class="text-right font-bold swiss-text-primary">${fmt(ev.total_tokens)}</td>
        `;
        frag.appendChild(tr);
      });
      tbody.appendChild(frag);
    }

    function exportTokenData(format) {
      const sel = document.getElementById('analytics-account-select');
      const acc = sel ? sel.value : 'all';
      const url = `/api/tokens/export?format=${format}&range=${currentTimeRange}&account=${encodeURIComponent(acc)}`;
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
      showToast(`Preparing ${format.toUpperCase()} export...`, 'info', 2500);
    }

    // ==========================================
    // PAGE 3: FEATURE 8 SESSION & FLEET INSPECTOR
    // ==========================================
    async function loadFleetSessions(forceNotice=false) {
      try {
        const inc = hideSubagentsFilter ? '0' : '1';
        const res = await fetch(`/api/sessions/recent?limit=25&include_subagents=${inc}`);
        let sessions = await res.json();
        if (sessions && sessions.sessions) sessions = sessions.sessions;
        cachedSessionsList = Array.isArray(sessions) ? sessions : [];

        populateSessionDropdown(cachedSessionsList);

        if (cachedSessionsList.length > 0) {
          // If no session selected, select the first
          if (!selectedSessionId || !cachedSessionsList.find(s => s.session_id === selectedSessionId)) {
            selectedSessionId = cachedSessionsList[0].session_id;
          }
          renderActiveSessionCard(cachedSessionsList.find(s => s.session_id === selectedSessionId) || cachedSessionsList[0]);
          loadSessionTurns(selectedSessionId);
        } else {
          const titleElem = document.getElementById('session-title-display');
          if (titleElem) titleElem.innerText = 'No Active Sessions';
          document.getElementById('session-selected-id').innerText = 'No sessions found in history';
          document.getElementById('session-turns-tbody').innerHTML = '<tr><td colspan="9" class="py-8 text-center text-gray-500">No session turns recorded.</td></tr>';
        }

        if (forceNotice) showToast(`Fleet updated (${cachedSessionsList.length} sessions detected)`, 'info', 2500);
      } catch (e) {
        console.warn('Failed to load fleet sessions:', e);
      }
    }

    let hideSubagentsFilter = true;

    function toggleSubagentsFilter() {
      hideSubagentsFilter = !hideSubagentsFilter;
      const btn = document.getElementById('btn-toggle-subagents');
      const lbl = document.getElementById('subagents-toggle-label');
      if (hideSubagentsFilter) {
        if (lbl) lbl.innerText = 'Show Subagents';
        if (btn) btn.classList.remove('border-sky-500/60', 'bg-surface-3');
      } else {
        if (lbl) lbl.innerText = 'Hide Subagents';
        if (btn) btn.classList.add('border-sky-500/60', 'bg-surface-3');
      }
      loadFleetSessions();
    }

    function getContextStatus(s) {
      if (!s) return { tag: 'OK', dotColor: 'var(--sage-text)', status: 'Optimal', pct: 0, textClass: 'swiss-text-sage' };
      const modelStr = (s.model || '').toLowerCase();
      let maxContextLimit = 512000; // Antigravity doubled auto-compaction ceiling (512k tokens)
      if (modelStr.includes('claude')) {
        maxContextLimit = 160000;
      }
      const currentContext = s.max_context_tokens || s.avg_context_tokens || 0;
      const pct = Math.min(100, (currentContext / maxContextLimit) * 100);
      if (pct >= 85) return { tag: 'HIGH', dotColor: 'var(--accent)', status: 'Near Compaction', pct: pct, textClass: 'swiss-text-accent' };
      if (pct >= 60) return { tag: 'MED', dotColor: 'var(--amber-text)', status: 'Elevated', pct: pct, textClass: 'text-amber-300' };
      return { tag: 'OK', dotColor: 'var(--sage-text)', status: 'Optimal', pct: pct, textClass: 'swiss-text-sage' };
    }

    function populateSessionDropdown(sessions) {
      const select = document.getElementById('session-dropdown-select');
      select.innerHTML = '';

      if (!sessions || !sessions.length) {
        select.innerHTML = '<option value="">No sessions found</option>';
        return;
      }

      // Filter subagents if toggled
      let displayList = sessions;
      if (hideSubagentsFilter) {
        displayList = sessions.filter(s => !s.is_subagent);
        // If selected session was a subagent and got filtered out, fallback to first main session
        if (displayList.length > 0 && !displayList.find(s => s.session_id === selectedSessionId)) {
          selectedSessionId = displayList[0].session_id;
          renderActiveSessionCard(displayList[0]);
          loadSessionTurns(selectedSessionId);
        }
      }

      // Partition into Main Conversations and Autonomous Subagents
      const mainSessions = displayList.filter(s => !s.is_subagent);
      const subagentSessions = displayList.filter(s => s.is_subagent);

      if (mainSessions.length > 0) {
        const groupMain = document.createElement('optgroup');
        groupMain.label = `Main Conversations (${mainSessions.length})`;
        mainSessions.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.session_id;
          const title = s.title || (s.session_id ? s.session_id.slice(0, 18) + '...' : 'Unknown Session');
          const turns = s.total_turns || 0;
          const st = getContextStatus(s);
          const compText = s.compactions > 0 ? ` • ${s.compactions} ${s.compactions === 1 ? 'compact' : 'compacts'}` : '';
          opt.innerText = `[${st.tag}] ${title} • ${turns} turns${compText}`;
          opt.title = `${title}\nContext Load: ${st.pct.toFixed(1)}% (${st.status})\nCapacity: 512k Compaction Limit\nCompactions: ${s.compactions || 0}\nTurns: ${turns}\nID: ${s.session_id}`;
          if (s.session_id === selectedSessionId) opt.selected = true;
          groupMain.appendChild(opt);
        });
        select.appendChild(groupMain);
      }

      if (subagentSessions.length > 0) {
        const groupSub = document.createElement('optgroup');
        groupSub.label = `Autonomous Subagents (${subagentSessions.length})`;
        subagentSessions.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.session_id;
          const title = s.title || (s.session_id ? s.session_id.slice(0, 18) + '...' : 'Subagent Session');
          const turns = s.total_turns || 0;
          const st = getContextStatus(s);
          const compText = s.compactions > 0 ? ` • ${s.compactions}c` : '';
          opt.innerText = `[${st.tag}] ↳ ${title} • ${turns} turns${compText}`;
          opt.title = `${title}\nContext Load: ${st.pct.toFixed(1)}% (${st.status})\nCapacity: 512k Compaction Limit\nCompactions: ${s.compactions || 0}\nTurns: ${turns}\nID: ${s.session_id}`;
          if (s.session_id === selectedSessionId) opt.selected = true;
          groupSub.appendChild(opt);
        });
        select.appendChild(groupSub);
      }
    }

    function onSessionSelectChange(sid) {
      selectedSessionId = sid;
      const s = cachedSessionsList.find(x => x.session_id === sid);
      if (s) renderActiveSessionCard(s);
      loadSessionTurns(sid);
    }

    async function copySessionId() {
      if (!selectedSessionId) return;
      try {
        await navigator.clipboard.writeText(selectedSessionId);
        showToast('Session ID copied to clipboard', 'success', 2000);
      } catch (e) {
        try {
          const ta = document.createElement('textarea');
          ta.value = selectedSessionId;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          const ok = document.execCommand('copy');
          ta.remove();
          if (ok) {
            showToast('Session ID copied to clipboard', 'success', 2000);
          } else {
            showToast('Failed to copy Session ID', 'error', 3000);
          }
        } catch (err) {
          showToast('Failed to copy Session ID', 'error', 3000);
        }
      }
    }

    async function clearSystemLogs() {
      try {
        await fetch('/api/clear-logs', { method: 'POST' });
        await fetchStatus(false);
        showToast('System logs cleared', 'info', 2000);
      } catch (e) {
        showToast('Failed to clear logs: ' + e.message, 'error', 3000);
      }
    }

    function renderActiveSessionCard(s) {
      if (!s) return;
      const st = getContextStatus(s);
      const titleElem = document.getElementById('session-title-display');
      if (titleElem) {
        titleElem.innerHTML = `<span class="swiss-dot-inline" style="background-color: ${st.dotColor};" aria-hidden="true"></span><span>${s.title || s.session_id}</span>`;
      }
      document.getElementById('session-selected-id').innerText = s.session_id;

      const subBadge = document.getElementById('session-subagent-badge');
      if (subBadge) {
        if (s.is_subagent) {
          subBadge.classList.remove('hidden');
          subBadge.innerText = s.agent_name ? `Subagent: ${s.agent_name}` : 'Subagent';
        } else {
          subBadge.classList.add('hidden');
        }
      }

      // Feature: Compaction tracker badge & card indicator
      const compCount = s.compactions || 0;
      const compTextEl = document.getElementById('session-compaction-text');
      const compBadgeEl = document.getElementById('session-compaction-badge');
      const compPillEl = document.getElementById('session-compaction-count-pill');
      const compLabel = `${compCount} ${compCount === 1 ? 'Compaction' : 'Compactions'}`;
      if (compTextEl) compTextEl.innerText = compLabel;
      if (compPillEl) compPillEl.innerText = compLabel;
      if (compBadgeEl) {
        if (compCount > 0) {
          compBadgeEl.className = 'swiss-badge swiss-badge-accent gap-1';
        } else {
          compBadgeEl.className = 'swiss-badge gap-1';
        }
      }

      document.getElementById('session-turn-count').innerText = `${fmt(s.total_turns || 0)} turns`;
      document.getElementById('session-account-pill').innerText = `Account: ${s.account || 'default'} • ${s.model || 'Gemini 3.8 Flash'}`;

      // Feature 3: Context Window Token Gauge (Antigravity Desktop auto-compaction ceiling)
      const modelStr = (s.model || '').toLowerCase();
      let maxContextLimit = 512000; // Antigravity doubled auto-compaction ceiling (512k tokens)
      let ceilingText = '512k';

      if (modelStr.includes('claude')) {
        maxContextLimit = 160000;
        ceilingText = '160k';
      }

      const limitLabelEl = document.getElementById('session-context-limit-label');
      const currentContext = s.max_context_tokens || s.avg_context_tokens || 0;
      const ctxPct = Math.min(100, Math.max(0.1, (currentContext / maxContextLimit) * 100));
      const headroom = Math.max(0, maxContextLimit - currentContext);

      if (limitLabelEl) limitLabelEl.innerText = `${fmt(headroom)} headroom (${ceilingText} limit)`;

      document.getElementById('session-context-val').innerText = fmt(currentContext);
      
      const statusText = ctxPct < 60 ? 'Optimal' : ctxPct < 85 ? 'Elevated' : 'Near Compaction';
      const pctColor = ctxPct < 60 ? 'swiss-text-primary' : ctxPct < 85 ? 'text-amber-300' : 'swiss-text-accent';
      const pctEl = document.getElementById('session-context-pct');
      if (pctEl) {
        pctEl.className = `font-mono text-[10.5px] ${pctColor} font-bold`;
        pctEl.innerText = `${ctxPct.toFixed(1)}% of ${ceilingText} (${statusText})`;
      }
      
      const bar = document.getElementById('session-context-bar');
      if (bar) {
        bar.style.width = `${Math.max(1.5, ctxPct)}%`;
        bar.style.backgroundColor = ctxPct >= 85 ? 'var(--accent)' : ctxPct >= 60 ? 'var(--amber-text)' : 'var(--chart-day)';
      }

      // Cache percentage for session
      const inp = s.input_tokens || 0;
      const cache = s.cache_tokens || 0;
      const cachePct = (inp + cache) > 0 ? ((cache / (inp + cache)) * 100) : 0;
      document.getElementById('session-cache-pct').innerText = `${cachePct.toFixed(1)}%`;
      document.getElementById('session-cache-tokens').innerText = `${fmt(cache)} tokens saved from quota`;
    }

    async function loadSessionTurns(sid) {
      if (!sid) return;
      const tbody = document.getElementById('session-turns-tbody');
      const isSameSession = (sid === cachedTurnsSessionId);
      if (!isSameSession) {
        tbody.innerHTML = '<tr><td colspan="10" class="py-4 text-center text-gray-500">Loading turns for session...</td></tr>';
      }

      try {
        const res = await fetch(`/api/sessions/turns?session_id=${encodeURIComponent(sid)}&limit=100`);
        let turns = await res.json();
        if (turns && turns.turns) turns = turns.turns;
        const turnList = Array.isArray(turns) ? turns : [];

        cachedTurnsSessionId = sid;
        cachedSessionTurns = turnList;
        document.getElementById('turns-table-count').innerText = `${turnList.length} steps`;
        const wrap = tbody.closest('.swiss-table-wrap');
        const prevScrollTop = (isSameSession && wrap) ? wrap.scrollTop : 0;
        renderSessionTurnsTable(turnList);
        if (isSameSession && wrap) wrap.scrollTop = prevScrollTop;
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="10" class="py-4 text-center text-rose-400">Failed to load turns: ${e.message}</td></tr>`;
      }
    }

    function getTurnTypeBadge(turn) {
      const outp = turn.output_tokens || 0;
      if (turn.is_compaction) {
        return `<span class="swiss-badge swiss-badge-accent whitespace-nowrap gap-1"><svg class="w-2.5 h-2.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span>Compaction</span></span>`;
      }
      return outp > 0
        ? `<span class="swiss-badge whitespace-nowrap gap-1"><span class="w-1.5 h-1.5 inline-block" style="background-color: var(--text-primary); border-radius: 1px;" aria-hidden="true"></span><span>Agent Turn</span></span>`
        : `<span class="swiss-badge swiss-badge-sage whitespace-nowrap gap-1"><span class="w-1.5 h-1.5 inline-block" style="background-color: var(--sage-text); border-radius: 1px;" aria-hidden="true"></span><span>User Prompt</span></span>`;
    }

    function createTurnDetailRow(turn, stepNum, typeBadge) {
      const inp = turn.input_tokens || 0;
      const outp = turn.output_tokens || 0;
      const cache = turn.cache_read_tokens || 0;
      const tot = turn.total_tokens || (inp + outp);
      const badge = typeBadge || getTurnTypeBadge(turn);

      const expTr = document.createElement('tr');
      expTr.dataset.detailFor = String(stepNum);
      expTr.style.backgroundColor = 'var(--bg-card)';
      expTr.innerHTML = `
        <td colspan="10" class="p-3 space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
            <div class="space-y-1">
              <div class="swiss-text-primary font-semibold text-[11px] flex items-center gap-2">
                <span>Step ${stepNum} Detailed Volume Breakdown</span>
                ${badge}
              </div>
              <div class="flex items-center gap-3 text-[11px] swiss-text-muted">
                <span>Prompt: <strong class="swiss-text-primary">${fmt(inp)}</strong> (${tot > 0 ? (inp/tot*100).toFixed(1) : 0}%)</span>
                <span>Output: <strong class="swiss-text-primary">${fmt(outp)}</strong> (${tot > 0 ? (outp/tot*100).toFixed(1) : 0}%)</span>
                <span>Cache Hit: <strong class="${cache > 0 ? 'swiss-text-accent' : 'swiss-text-primary'}">${fmt(cache)}</strong></span>
              </div>
            </div>
            <div class="text-[10.5px] font-mono swiss-text-muted">
              <span>Timestamp: <strong class="swiss-text-primary">${turn.created_at || '--'}</strong></span>
            </div>
          </div>
          <div class="swiss-io-track">
            <div class="h-full" style="width: ${tot > 0 ? (inp/tot*100) : 50}%; background-color: var(--accent);" title="Input Prompt"></div>
            <div class="h-full" style="width: ${tot > 0 ? (outp/tot*100) : 50}%; background-color: var(--chart-day);" title="Generated Output"></div>
          </div>
        </td>
      `;
      return expTr;
    }

    function renderSessionTurnsTable(turns) {
      const tbody = document.getElementById('session-turns-tbody');
      tbody.innerHTML = '';

      if (!turns.length) {
        tbody.innerHTML = '<tr><td colspan="10" class="py-4 text-center text-gray-500">No recorded turns for this session.</td></tr>';
        return;
      }

      turns.forEach((turn, idx) => {
        const stepNum = turn.step_index !== undefined ? turn.step_index : (idx + 1);
        const inp = turn.input_tokens || 0;
        const outp = turn.output_tokens || 0;
        const cache = turn.cache_read_tokens || 0;
        const tot = turn.total_tokens || (inp + outp);
        const typeBadge = getTurnTypeBadge(turn);

        const cacheEff = (inp + cache) > 0 ? ((cache / (inp + cache)) * 100) : 0;
        let badgeClass = 'swiss-badge';
        let badgeText = 'Full Context';
        if (cacheEff > 0) {
          badgeClass = 'swiss-badge swiss-badge-sage';
          badgeText = `${cacheEff.toFixed(0)}% Cached`;
        }

        let timeStr = '--';
        if (turn.created_at) {
          try {
            timeStr = new Date(turn.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          } catch(e) {
            timeStr = turn.created_at.slice(11, 19);
          }
        }

        const modelDisplay = (turn.model || 'Gemini')
          .replace('gemini-', '')
          .replace('-thinking', ' (think)');

        // Main Turn Row
        const tr = document.createElement('tr');
        tr.dataset.step = String(stepNum);
        tr.className = 'hover:bg-surface-2/60 cursor-pointer transition-colors';
        tr.onclick = () => toggleTurnExpand(stepNum, tr, turn);

        const isExpanded = expandedTurns.has(stepNum);

        tr.innerHTML = `
          <td class="py-1.5 px-3 text-center font-bold swiss-text-muted">${stepNum}</td>
          <td class="py-1.5 px-3 swiss-text-muted whitespace-nowrap">${timeStr}</td>
          <td class="py-1.5 px-3 text-center">${typeBadge}</td>
          <td class="py-1.5 px-3 swiss-text-secondary truncate max-w-[130px]" title="${turn.model}">${modelDisplay}</td>
          <td class="py-1.5 px-3 text-right swiss-text-secondary">${fmt(inp)}</td>
          <td class="py-1.5 px-3 text-right swiss-text-secondary">${fmt(outp)}</td>
          <td class="py-1.5 px-3 text-right ${cache > 0 ? 'swiss-text-accent font-semibold' : 'swiss-text-muted'}">${fmt(cache)}</td>
          <td class="py-1.5 px-3 text-right font-bold swiss-text-primary">${fmt(tot)}</td>
          <td class="py-1.5 px-3 text-center">
            <span class="${badgeClass} whitespace-nowrap">
              ${badgeText}
            </span>
          </td>
          <td class="py-1.5 px-3 text-center swiss-text-muted">
            <button type="button" class="p-0.5 hover:text-white transition-colors" title="Toggle Detail" aria-label="Toggle step ${stepNum} detail" aria-expanded="${isExpanded}">
              <svg class="w-3 h-3 transform transition-transform ${isExpanded ? 'rotate-180' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
          </td>
        `;
        tbody.appendChild(tr);

        // Expandable Detail Drawer Row
        if (isExpanded) {
          tbody.appendChild(createTurnDetailRow(turn, stepNum, typeBadge));
        }
      });
    }

    function toggleTurnExpand(stepNum, rowEl, turnObj) {
      const willExpand = !expandedTurns.has(stepNum);
      if (willExpand) {
        expandedTurns.add(stepNum);
      } else {
        expandedTurns.delete(stepNum);
      }

      const tbody = document.getElementById('session-turns-tbody');
      const mainRow = rowEl || (tbody ? tbody.querySelector(`tr[data-step="${stepNum}"]`) : null);
      if (!mainRow) {
        if (cachedSessionTurns.length) renderSessionTurnsTable(cachedSessionTurns);
        return;
      }

      const btn = mainRow.querySelector('button');
      if (btn) btn.setAttribute('aria-expanded', String(willExpand));
      const icon = mainRow.querySelector('button svg');
      if (icon) icon.classList.toggle('rotate-180', willExpand);

      const nextRow = mainRow.nextElementSibling;
      const hasDetailRow = nextRow && nextRow.dataset.detailFor === String(stepNum);
      if (willExpand && !hasDetailRow) {
        const turn = turnObj || cachedSessionTurns.find((t, i) => (t.step_index !== undefined ? t.step_index : (i + 1)) === stepNum);
        if (turn) {
          mainRow.insertAdjacentElement('afterend', createTurnDetailRow(turn, stepNum));
        }
      } else if (!willExpand && hasDetailRow) {
        nextRow.remove();
      }
    }

    async function cleanStaleLocks() {
      const btn = document.getElementById('stale-lock-status');
      btn.innerText = 'Cleaning...';
      try {
        const res = await fetch('/api/clean-cache', {method: 'POST'});
        const d = await res.json();
        btn.innerText = `Cleaned ${d.cleaned} files`;
        showToast(`Cleaned ${d.cleaned} orphan session locks/cache files`, 'success');
        setTimeout(() => btn.innerText = 'Ready', 3000);
      } catch (e) {
        btn.innerText = 'Error';
        showToast('Error cleaning cache: ' + e.message, 'error');
      }
    }

    function openEnrollModal() {
      document.getElementById('enroll-modal').classList.remove('hidden');
    }
    function closeEnrollModal() {
      document.getElementById('enroll-modal').classList.add('hidden');
    }
    async function importActiveCredential() {
      closeEnrollModal();
      try {
        const res = await fetch('/api/import-active', {method: 'POST'});
        const d = await res.json();
        if (d.ok) {
          showToast(`Successfully imported profile: <strong>${d.imported}</strong>`, 'success', 5000);
          await fetchStatus(true);
        } else {
          showToast(`Import failed: ${d.error || 'Unknown'}`, 'error', 5000);
        }
      } catch (e) {
        showToast('Failed to import profile: ' + e.message, 'error');
      }
    }

    async function startEnrollment() {
      closeEnrollModal();
      try {
        const res = await fetch('/api/enroll', {method: 'POST'});
        const d = await res.json();
        if (d.ok) {
          showToast('Sign-in launched in browser. Select your account and authorize.', 'info', 7000);
          const initialCount = (currentState && currentState.accounts) ? currentState.accounts.length : 0;
          let attempts = 0;
          const pollInterval = setInterval(async () => {
            attempts++;
            await fetchStatus(true);
            const currentCount = (currentState && currentState.accounts) ? currentState.accounts.length : 0;
            if (currentCount > initialCount) {
              clearInterval(pollInterval);
              showToast('New Google account connected successfully!', 'success', 6000);
            } else if (attempts >= 40) {
              clearInterval(pollInterval);
            }
          }, 2500);
        } else {
          showToast('Failed to launch enrollment: ' + (d.error || 'Unknown'), 'error');
        }
      } catch (e) {
        showToast('Failed to launch enrollment: ' + e.message, 'error');
      }
    }

    // ==========================================
    // SOFTWARE SELF-UPDATER MODAL & POLLING
    // ==========================================
    let updateState = null;
    let updatePollTimer = null;
    let autoInstallAfterDownload = false;

    function _stopUpdatePoll() {
      if (updatePollTimer) {
        clearInterval(updatePollTimer);
        updatePollTimer = null;
      }
    }

    function _ensureUpdatePoll() {
      if (!updatePollTimer) {
        updatePollTimer = setInterval(() => {
          fetchUpdateStatus();
        }, 600);
      }
    }

    function renderUpdateUI() {
      if (!updateState) return;
      const badge = document.getElementById('app-version-badge');
      if (badge && updateState.current_version) {
        badge.innerText = `v${updateState.current_version}`;
      }

      const dot = document.getElementById('update-indicator-dot');
      const headerBtn = document.getElementById('btn-check-updates');
      const headerLabel = document.getElementById('btn-check-updates-label');
      const hasUpdate = (updateState.status === 'available' || updateState.status === 'ready');
      if (dot) dot.classList.toggle('hidden', !hasUpdate);
      if (headerBtn) {
        headerBtn.title = hasUpdate && updateState.latest_version
          ? `Update available: v${updateState.latest_version}`
          : 'Check for updates';
      }
      if (headerLabel) {
        headerLabel.innerText = hasUpdate && updateState.latest_version
          ? `Update v${updateState.latest_version}`
          : 'Check for Updates';
      }

      const modal = document.getElementById('update-modal');
      if (!modal || modal.classList.contains('hidden')) return;

      const curEl = document.getElementById('update-current-ver');
      const latEl = document.getElementById('update-latest-ver');
      const statusBadge = document.getElementById('update-status-badge');
      const devNotice = document.getElementById('update-dev-notice');
      const msgBox = document.getElementById('update-message-box');
      const progWrap = document.getElementById('update-progress-wrap');
      const progPct = document.getElementById('update-progress-pct');
      const progBar = document.getElementById('update-progress-bar');
      const notesWrap = document.getElementById('update-notes-wrap');
      const notesEl = document.getElementById('update-release-notes');
      const btnRecheck = document.getElementById('btn-update-recheck');
      const btnCancel = document.getElementById('btn-update-cancel');
      const btnAction = document.getElementById('btn-update-action');

      if (curEl) curEl.innerText = updateState.current_version ? `v${updateState.current_version}` : 'v--';
      if (latEl) latEl.innerText = updateState.latest_version ? `v${updateState.latest_version}` : '--';
      if (devNotice) devNotice.classList.toggle('hidden', Boolean(updateState.is_frozen));

      const st = updateState.status || 'idle';
      const statusMeta = {
        idle: { text: 'Idle', cls: 'swiss-badge shrink-0' },
        checking: { text: 'Checking...', cls: 'swiss-badge shrink-0' },
        up_to_date: { text: 'Up to Date', cls: 'swiss-badge swiss-badge-sage shrink-0' },
        available: { text: 'Update Available', cls: 'swiss-badge shrink-0' },
        downloading: { text: 'Downloading', cls: 'swiss-badge shrink-0' },
        ready: { text: 'Ready to Install', cls: 'swiss-badge swiss-badge-sage shrink-0' },
        error: { text: 'Error', cls: 'swiss-badge shrink-0' }
      }[st] || { text: st, cls: 'swiss-badge shrink-0' };

      if (statusBadge) {
        statusBadge.className = statusMeta.cls;
        statusBadge.innerText = statusMeta.text;
        statusBadge.style.borderColor = st === 'available' || st === 'error' ? 'var(--accent)' : '';
        statusBadge.style.color = st === 'available' || st === 'error' ? 'var(--accent)' : '';
      }

      if (msgBox) {
        let msg = '';
        let borderStyle = '';
        if (st === 'checking') {
          msg = 'Checking GitHub Releases for the latest version...';
        } else if (st === 'up_to_date') {
          msg = `You are running the latest version (v${updateState.current_version}).`;
          borderStyle = 'border-left: 3px solid var(--sage-text);';
        } else if (st === 'error') {
          msg = updateState.error || 'Failed to check or download update.';
          borderStyle = 'border-left: 3px solid var(--accent);';
        } else if (st === 'ready') {
          msg = 'Installer downloaded and verified with SHA-256. Click Install & Restart to apply the update.';
          borderStyle = 'border-left: 3px solid var(--sage-text);';
        } else if (st === 'available' && !updateState.has_installer) {
          msg = 'A new release is available on GitHub, but no matching Windows installer asset was attached yet.';
          borderStyle = 'border-left: 3px solid var(--amber-text);';
        }
        msgBox.style.cssText = borderStyle;
        msgBox.innerText = msg;
        msgBox.classList.toggle('hidden', !msg);
      }

      if (progWrap) {
        const showProg = (st === 'downloading' || st === 'ready');
        progWrap.classList.toggle('hidden', !showProg);
        const pct = Math.max(0, Math.min(100, Number(updateState.progress_pct || 0)));
        if (progPct) progPct.innerText = `${pct}%`;
        if (progBar) progBar.style.width = `${pct}%`;
      }

      if (notesWrap && notesEl) {
        const notes = (updateState.release_notes || '').trim();
        notesWrap.classList.toggle('hidden', !notes);
        notesEl.innerText = notes;
      }

      if (btnRecheck) {
        btnRecheck.disabled = (st === 'checking' || st === 'downloading');
        btnRecheck.classList.toggle('hidden', st === 'downloading');
      }
      if (btnCancel) {
        btnCancel.classList.toggle('hidden', st !== 'downloading');
      }
      if (btnAction) {
        const canDownload = (st === 'available' && Boolean(updateState.has_installer));
        const canInstall = (st === 'ready');
        const showAction = (canDownload || canInstall);
        btnAction.classList.toggle('hidden', !showAction);
        btnAction.disabled = !updateState.is_frozen || st === 'downloading';
        const lbl = btnAction.querySelector('span');
        if (lbl) lbl.innerText = canInstall ? 'Install & Restart' : 'Download & Install';
      }
    }

    async function fetchUpdateStatus() {
      try {
        const res = await fetch('/api/update/status', { cache: 'no-store' });
        if (!res.ok) return;
        updateState = await res.json();
        renderUpdateUI();

        const st = updateState.status;
        if (st === 'checking' || st === 'downloading') {
          _ensureUpdatePoll();
        } else {
          _stopUpdatePoll();
        }

        if (st === 'ready' && autoInstallAfterDownload) {
          autoInstallAfterDownload = false;
          await installReadyUpdate();
        } else if (st === 'error' || st === 'available') {
          if (st === 'error') autoInstallAfterDownload = false;
        }
      } catch (e) {}
    }

    function openUpdateModal() {
      const modal = document.getElementById('update-modal');
      if (modal) modal.classList.remove('hidden');
      renderUpdateUI();
      if (!updateState || ['idle', 'up_to_date', 'error'].includes(updateState.status)) {
        triggerUpdateCheck();
      } else {
        fetchUpdateStatus();
      }
    }

    function closeUpdateModal() {
      const modal = document.getElementById('update-modal');
      if (modal) modal.classList.add('hidden');
      if (!updateState || updateState.status !== 'downloading') {
        _stopUpdatePoll();
      }
    }

    async function triggerUpdateCheck() {
      try {
        const res = await fetch('/api/update/check', { method: 'POST' });
        const d = await res.json();
        if (d && d.update) {
          updateState = d.update;
          renderUpdateUI();
        }
        _ensureUpdatePoll();
      } catch (e) {
        showToast('Failed to check for updates: ' + e.message, 'error');
      }
    }

    async function downloadAndInstallUpdate() {
      if (!updateState) return;
      if (!updateState.is_frozen) {
        showToast('In-app install is disabled in dev mode. Use GitHub Releases instead.', 'info', 4500);
        return;
      }
      if (updateState.status === 'ready') {
        await installReadyUpdate();
        return;
      }
      autoInstallAfterDownload = true;
      try {
        const res = await fetch('/api/update/download', { method: 'POST' });
        const d = await res.json();
        if (!res.ok || !d.ok) {
          autoInstallAfterDownload = false;
          showToast(d.error || 'Failed to start update download', 'error', 5000);
          await fetchUpdateStatus();
          return;
        }
        _ensureUpdatePoll();
        await fetchUpdateStatus();
      } catch (e) {
        autoInstallAfterDownload = false;
        showToast('Download error: ' + e.message, 'error', 5000);
      }
    }

    async function cancelUpdateDownload() {
      autoInstallAfterDownload = false;
      try {
        await fetch('/api/update/cancel', { method: 'POST' });
        showToast('Update download cancelled.', 'info', 3000);
        await fetchUpdateStatus();
      } catch (e) {}
    }

    async function installReadyUpdate() {
      try {
        const res = await fetch('/api/update/install', { method: 'POST' });
        const d = await res.json();
        if (res.ok && d.ok) {
          showToast('Launching verified installer and restarting Control Center...', 'success', 6000);
          _stopUpdatePoll();
        } else {
          showToast(d.error || 'Failed to launch installer', 'error', 5000);
        }
      } catch (e) {
        showToast('Install error: ' + e.message, 'error', 5000);
      }
    }

    function openUpdateReleasePage() {
      const url = (updateState && updateState.release_url)
        ? updateState.release_url
        : 'https://github.com/3bdyna/Antigravity-Control-Center/releases';
      if (url.startsWith('https://github.com/')) {
        window.open(url, '_blank');
      }
    }

    window.addEventListener('DOMContentLoaded', () => {
      // Instant Local Storage Hydration (0ms load time)
      try {
        const cached = localStorage.getItem('ag_last_status');
        if (cached) {
          currentState = JSON.parse(cached);
          renderAccounts();
          updateAutopilotUI();
          if (currentState.burn_rate !== undefined) {
            const tpm = currentState.burn_rate || 0;
            const tps = currentState.tokens_per_sec !== undefined ? currentState.tokens_per_sec : Number((tpm / 60.0).toFixed(1));
            document.getElementById('top-burn-rate').innerText = `${tps} tok/s (${fmt(tpm)}/m)`;
            const statTps = document.getElementById('stat-tokens-per-sec');
            if (statTps) statTps.innerText = `${tps} tok/s`;
          }
          if (currentState.logs) {
            const lb = document.getElementById('system-logs-box');
            lb.innerHTML = currentState.logs.map(l => `<div>${l}</div>`).join('') || '<div class="text-gray-600">No logs yet.</div>';
          }
        }
      } catch (e) {}

      if (window.location.hash === '#analytics') {
        switchTab('analytics');
      } else if (window.location.hash === '#sessions') {
        switchTab('sessions');
      }
      fetchStatus(false);
      fetchUpdateStatus();
      // Real-time Server-Sent Events stream (replaces constant 8s polling)
      let _sseFallbackTimer = null;
      function setSseState(connected) {
        const dot = document.getElementById('sse-dot');
        const lbl = document.getElementById('sse-label');
        if (dot) {
          dot.className = 'status-dot w-1.5 h-1.5 shrink-0 mr-2 inline-block';
          dot.style.backgroundColor = connected ? 'var(--sage-text)' : 'var(--amber-text)';
          dot.style.borderRadius = '1px';
        }
        if (lbl) lbl.innerText = connected ? 'Live Sync' : 'Reconnecting';
      }
      function connectSSE() {
        try {
          const es = new EventSource('/api/events');
          es.onopen = () => setSseState(true);
          es.addEventListener('status', () => {
            if (!document.hidden) fetchStatus(false);
          });
          es.addEventListener('update', () => {
            fetchUpdateStatus();
          });
          es.onerror = () => {
            setSseState(false);
            es.close();
            setTimeout(connectSSE, 5000);
          };
        } catch (e) {}
      }
      connectSSE();
      _sseFallbackTimer = setInterval(() => {
        if (!document.hidden) fetchStatus(false);
      }, 60000);
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) fetchStatus(false);
      });
    });
