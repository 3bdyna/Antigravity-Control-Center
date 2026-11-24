let currentState = null;
    let currentTab = 'accounts';
    let currentTimeRange = 'month';
    let cachedHeatmapData = null;
    let cachedHourlyData = null;
    let cachedSessionsList = [];
    let selectedSessionId = null;
    let expandedTurns = new Set();

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
      if (pct > 50) return 'text-gray-200';
      if (pct > 20) return 'text-amber-300/85';
      return 'text-rose-400/85';
    }
    function getBarColor(pct) {
      if (pct > 50) return 'bg-zinc-400';
      if (pct > 20) return 'bg-amber-400/70';
      return 'bg-rose-400/70';
    }

    // Feature 10: Sleek Toast System
    function showToast(message, type='info', duration=4000) {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      
      let border = 'border-hairline';
      let icon = '<svg class="w-4 h-4 text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
      
      if (type === 'success') {
        border = 'border-hairline-strong bg-surface/95 text-gray-200';
        icon = '<svg class="w-4 h-4 text-emerald-400/90 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
      } else if (type === 'error') {
        border = 'border-rose-900/60 bg-surface/95 text-rose-300';
        icon = '<svg class="w-4 h-4 text-rose-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
      } else {
        border = 'border-hairline-strong bg-surface/95 text-gray-200';
      }

      toast.className = `toast-anim pointer-events-auto px-3.5 py-2 rounded-lg border ${border} shadow-xl backdrop-blur-md flex items-center gap-2.5 text-xs max-w-md`;
      toast.innerHTML = `
        ${icon}
        <div class="flex-1 font-sans leading-snug">${message}</div>
      `;

      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.25s ease-out';
        setTimeout(() => toast.remove(), 260);
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
          const name = d.filename || 'database.db';
          showToast(`Snapshot created: <strong>${name}</strong>${sizeKb}`, 'success', 5000);
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
            <span class="text-gray-400 font-medium text-[11px] whitespace-nowrap shrink-0">${label}</span>
            <span class="${getPercentColor(rem)} font-bold font-mono text-xs">${rem.toFixed(0)}%</span>
          </div>
          <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden my-1">
            <div class="quota-bar-fill h-full ${getBarColor(rem)} rounded-full transition-all duration-300" style="width: ${Math.max(2, rem)}%"></div>
          </div>
          <div class="flex items-center justify-between text-[9.5px] font-mono text-gray-400 leading-none">
            <span class="text-gray-400 flex items-center shrink-0" title="Time remaining until reset">
              <svg class="w-2.5 h-2.5 text-gray-500 mr-1.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              <span>${delta}</span>
            </span>
            <span class="text-gray-500 font-medium whitespace-nowrap ml-1 text-right truncate" title="${localTarget ? 'Exact reset time: ' + localTarget : ''}">
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
        card.className = `rounded-xl border ${isActive ? 'acc-card acc-card-active' : 'acc-card'} p-4 flex flex-col justify-between min-h-[224px]`;

        let badgeHtml = '';
        const badgeLabel = rec.badge_label || (isActive ? 'Active' : (acc === best ? 'Recommended' : 'Standby'));
        const badgeColor = rec.badge_color || (isActive ? 'emerald' : (acc === best ? 'white' : 'gray'));
        const reasonText = rec.reason || (isActive ? 'Active • Quota Healthy' : 'Standby • Ready');

        if (badgeColor === 'emerald') {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium text-emerald-400 font-mono">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse mr-1.5 inline-block shrink-0"></span><span>${badgeLabel}</span>
          </span>`;
        } else if (badgeColor === 'blue' || badgeColor === 'white') {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium text-white font-mono">
            <span class="w-1.5 h-1.5 rounded-full bg-white mr-1.5 inline-block shrink-0"></span><span>${badgeLabel}</span>
          </span>`;
        } else if (badgeColor === 'amber') {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium text-amber-400 font-mono">
            <span class="w-1.5 h-1.5 rounded-full bg-amber-400 mr-1.5 inline-block shrink-0"></span><span>${badgeLabel}</span>
          </span>`;
        } else {
          badgeHtml = `<span class="inline-flex items-center text-[10.5px] font-medium text-gray-400 font-mono">
            <span class="w-1.5 h-1.5 rounded-full bg-gray-600 mr-1.5 inline-block shrink-0"></span><span>${badgeLabel}</span>
          </span>`;
        }

        let actionBtn = '';
        if (isActive) {
          actionBtn = `<span class="h-6 px-2.5 rounded text-[11px] font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-800/60 flex items-center justify-center cursor-default shrink-0">In Use</span>`;
        } else {
          actionBtn = `<button type="button" onclick="switchAccount('${acc}')" class="btn-spring h-6 px-2.5 rounded text-[11px] font-semibold bg-white hover:bg-gray-200 text-gray-950 flex items-center shadow-sm shrink-0">
            <span class="mr-1.5">Switch</span>
            <svg class="w-3 h-3 text-gray-700 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </button>`;
        }

        let deleteBtn = '';
        if (!isActive) {
          deleteBtn = `<button type="button" onclick="deleteAccount('${acc}')" title="Delete Account" class="h-6 w-6 rounded hover:bg-surface-2 text-gray-500 hover:text-gray-300 border border-hairline flex items-center justify-center transition-colors shrink-0">
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>`;
        }

        const isDup = q.is_duplicate || (q.google_account && q.google_account !== acc);
        let dupWarning = '';
        if (isDup) {
          const linkedTo = q.duplicate_of || q.google_account || 'another account';
          dupWarning = `
            <div class="px-2 py-1.5 rounded-md bg-amber-950/40 border border-amber-600/40 text-amber-300 text-[10px] font-mono flex items-center gap-1.5 shadow-sm mt-1">
              <svg class="w-3.5 h-3.5 shrink-0 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <div class="truncate">
                <span>Linked to <strong class="text-white">${linkedTo}</strong></span>
                <span class="text-amber-400/80 text-[9px] block font-sans">Shared quota • Re-enroll to isolate</span>
              </div>
            </div>
          `;
        }

        card.innerHTML = `
          <div class="border-b border-hairline pb-2.5 space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center min-w-0 flex-1">
                <div class="w-6 h-6 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-white shrink-0 mr-2.5">
                  <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                </div>
                <span class="font-mono font-semibold text-xs text-white truncate min-w-0 tracking-tight" title="${acc}">${acc}</span>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                ${actionBtn}
                ${deleteBtn}
              </div>
            </div>
            <div class="flex items-center justify-between text-[10.5px] min-h-[18px]">
              ${badgeHtml}
              <span class="text-[9.5px] font-mono text-gray-400 truncate max-w-[200px]" title="${reasonText}">${reasonText}</span>
            </div>
            ${dupWarning}
          </div>

          <!-- 2-Column Limits Grid -->
          <div class="grid grid-cols-2 gap-3 pt-2 divide-x divide-hairline">
            <div class="space-y-2">
              <div class="flex items-center text-[9.5px] font-mono font-semibold uppercase tracking-wider text-gray-400">
                <span class="w-1.5 h-1.5 rounded-full bg-white mr-1.5 inline-block shrink-0"></span>
                <span>Gemini</span>
              </div>
              ${renderQuotaRow('5h Cycle', gemini['5h'])}
              ${renderQuotaRow('Weekly', gemini['weekly'])}
            </div>

            <div class="space-y-2 pl-3">
              <div class="flex items-center text-[9.5px] font-mono font-semibold uppercase tracking-wider text-gray-400">
                <span class="w-1.5 h-1.5 rounded-full bg-gray-400 mr-1.5 inline-block shrink-0"></span>
                <span>Claude & GPT</span>
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
        async function loadContextModeData() {
      try {
        const res = await fetch('/api/context-mode/stats');
        const d = await res.json();
        const active = d.active || false;
        const statusBadge = document.getElementById('cm-status-badge');
        if (statusBadge) {
          if (active) {
            statusBadge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> Active';
            statusBadge.className = 'text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface-2 border border-hairline text-gray-300 font-medium flex items-center gap-1';
          } else {
            statusBadge.innerHTML = 'Idle';
            statusBadge.className = 'text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface-2 border border-hairline text-gray-400 font-medium flex items-center gap-1';
          }
        }
        if (document.getElementById('cm-reduction-pct')) {
          const pct = d.reduction_pct || 0;
          const pctStr = (pct >= 99 && pct < 100) ? pct.toFixed(2) : pct.toFixed(1);
          document.getElementById('cm-reduction-pct').innerText = `${pctStr}%`;
        }
        if (document.getElementById('cm-tokens-saved')) {
          document.getElementById('cm-tokens-saved').innerText = fmt(d.tokens_saved || 0);
        }
        if (document.getElementById('cm-bytes-sandboxed')) {
          const mb = ((d.bytes_sandboxed || 0) / (1024 * 1024)).toFixed(1);
          document.getElementById('cm-bytes-sandboxed').innerText = `${mb} MB`;
        }
        if (document.getElementById('cm-dollars-saved')) {
          document.getElementById('cm-dollars-saved').innerText = `$${(d.dollars_saved || 0).toFixed(2)}`;
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
      } catch (e) {
        console.error('Failed to load context-mode stats:', e);
      }
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

      // Context-Mode Optimizer Live Stats
      loadContextModeData();
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
    async function loadHeatmapData(acc) {
      try {
        const res = await fetch(`/api/tokens/heatmap?account=${encodeURIComponent(acc || 'all')}`);
        let data = await res.json();
        if (data && data.heatmap) data = data.heatmap;
        if (data && data.days) data = data.days;
        cachedHeatmapData = Array.isArray(data) ? data : [];
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
      // Sunday is 0, Saturday is 6
      const cellSize = 11;
      const cellGap = 3;
      const leftPad = 28;
      const topPad = 20;

      const endDate = new Date();
      // Align end to Saturday of current week to make complete column
      const endDayOfWeek = endDate.getDay(); // 0..6
      const startDate = new Date(endDate.getTime() - (51 * 7 + endDayOfWeek) * 86400000);

      const maxTokens = Math.max(...daysData.map(d => d.total_tokens || 0), 50000);

      // Create SVG
      const totalWidth = leftPad + 53 * (cellSize + cellGap);
      const totalHeight = topPad + 7 * (cellSize + cellGap);
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', `0 0 ${totalWidth} ${totalHeight}`);
      svg.setAttribute('class', 'w-full h-auto overflow-visible');

      // Month labels
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      let lastMonth = -1;

      // Day labels on left
      const dayLabels = [
        { label: 'Mon', row: 1 },
        { label: 'Wed', row: 3 },
        { label: 'Fri', row: 5 }
      ];
      dayLabels.forEach(dl => {
        const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('x', '4');
        t.setAttribute('y', topPad + dl.row * (cellSize + cellGap) + cellSize - 2);
        t.setAttribute('fill', '#6b7280');
        t.setAttribute('font-size', '8.5');
        t.setAttribute('font-family', 'Inter, sans-serif');
        t.textContent = dl.label;
        svg.appendChild(t);
      });

      // Generate week columns
      let cur = new Date(startDate.getTime());
      for (let w = 0; w < 52; w++) {
        // Check if this week starts a new month for label
        const monthIdx = cur.getMonth();
        if (monthIdx !== lastMonth && w < 50) {
          const mt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
          mt.setAttribute('x', leftPad + w * (cellSize + cellGap));
          mt.setAttribute('y', topPad - 6);
          mt.setAttribute('fill', '#9ca3af');
          mt.setAttribute('font-size', '9');
          mt.setAttribute('font-family', 'Inter, sans-serif');
          mt.textContent = months[monthIdx];
          svg.appendChild(mt);
          lastMonth = monthIdx;
        }

        for (let d = 0; d < 7; d++) {
          const y = cur.getFullYear();
          const m = String(cur.getMonth() + 1).padStart(2, '0');
          const dayNum = String(cur.getDate()).padStart(2, '0');
          const dateStr = `${y}-${m}-${dayNum}`;

          const dayInfo = dayMap[dateStr] || { date: dateStr, total_tokens: 0, turns: 0, top_model: 'None' };
          const tok = dayInfo.total_tokens || 0;

          // Color scale
          let fillColor = '#1a1a20'; // Level 0
          let strokeColor = '#24242e';
          if (tok > 0) {
            const ratio = tok / maxTokens;
            if (ratio < 0.15) fillColor = '#064e3b';
            else if (ratio < 0.40) fillColor = '#047857';
            else if (ratio < 0.70) fillColor = '#059669';
            else fillColor = '#10b981';
            strokeColor = 'none';
          }

          const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('x', leftPad + w * (cellSize + cellGap));
          rect.setAttribute('y', topPad + d * (cellSize + cellGap));
          rect.setAttribute('width', cellSize);
          rect.setAttribute('height', cellSize);
          rect.setAttribute('rx', '2');
          rect.setAttribute('fill', fillColor);
          rect.setAttribute('stroke', strokeColor);
          rect.setAttribute('class', 'hm-cell');

          // Tooltip interactions
          rect.addEventListener('mouseenter', (ev) => {
            showHeatmapTooltip(ev, dayInfo);
          });
          rect.addEventListener('mouseleave', () => {
            hideHeatmapTooltip();
          });

          svg.appendChild(rect);
          cur.setDate(cur.getDate() + 1);
        }
      }

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
        <div class="text-white font-semibold text-xs border-b border-hairline pb-1 mb-1">${day.date}</div>
        <div class="text-gray-100 font-bold">${fmt(tok)} tokens <span class="text-gray-400 font-normal">(${fmt(turns)} turns)</span></div>
        <div class="text-gray-400 text-[10px]">In: ${fmt(inp)} • Out: ${fmt(outp)}</div>
        <div class="text-gray-500 text-[10px] truncate max-w-[170px]">Top: <span class="text-gray-300">${model}</span></div>
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

      for (let h = 0; h < 24; h++) {
        const item = hourMap[h] || { hour: h, total_tokens: 0, turns: 0, primary_model: 'None' };
        const tok = item.total_tokens || 0;
        const hPct = Math.max(3, Math.round((tok / maxTokens) * 78));
        const pctOfPeak = maxTokens > 0 ? Math.round((tok / maxTokens) * 100) : 0;

        const col = document.createElement('div');
        col.className = 'flex-1 min-w-0 flex flex-col items-center h-full justify-end group relative cursor-pointer px-[1px]';

        const hour12 = (h === 0) ? '12:00 AM' : (h < 12) ? `${h}:00 AM` : (h === 12) ? '12:00 PM' : `${h - 12}:00 PM`;
        const hour24 = `${String(h).padStart(2, '0')}:00`;

        // Enhanced, clear hover tooltip
        const tip = document.createElement('div');
        tip.className = 'pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 absolute -top-12 left-1/2 -translate-x-1/2 px-2 py-1 rounded-md bg-surface-3/95 backdrop-blur text-[10px] font-mono text-white whitespace-nowrap border border-hairline-strong z-30 shadow-xl flex flex-col items-center gap-0.5';
        tip.innerHTML = `
          <div class="font-bold text-gray-200 flex items-center gap-1.5 border-b border-hairline/60 pb-0.5 mb-0.5">
            <span>${hour12}</span>
            <span class="text-gray-400 text-[9px] font-normal">(${hour24})</span>
          </div>
          <div class="text-gray-200 font-semibold">${fmt(tok)} tokens <span class="text-gray-400 font-normal">(${pctOfPeak}%)</span></div>
          <div class="text-gray-400 text-[9px]">${item.turns || 0} prompt turns • ${item.primary_model || 'No activity'}</div>
        `;

        // Bar coloring: Peak is sky-400, Daytime is slate-500, Night is zinc-700
        let barColor = 'bg-slate-500/70 hover:bg-slate-400 border-slate-400/20';
        if (h === peakHour && tok > 0) {
          barColor = 'bg-sky-400/90 hover:bg-sky-300 border-sky-300/30';
        } else if (h < 7 || h >= 22) {
          barColor = 'bg-zinc-700/60 hover:bg-zinc-600 border-zinc-600/20';
        }

        const barWrap = document.createElement('div');
        barWrap.className = 'w-full flex justify-center items-end';
        barWrap.style.height = `${hPct}%`;

        const bar = document.createElement('div');
        bar.className = `w-full max-w-[12px] min-w-[2px] h-full ${barColor} rounded-t-sm transition-all border-t border-x`;
        barWrap.appendChild(bar);

        const lbl = document.createElement('div');
        lbl.className = 'h-5 flex items-center justify-center w-full select-none';
        if (shortLabels[h]) {
          lbl.innerHTML = `<span class="text-[8.5px] font-mono text-gray-400 tracking-tight whitespace-nowrap">${shortLabels[h]}</span>`;
        } else {
          lbl.innerHTML = `<span class="text-[7px] text-gray-600 leading-none">·</span>`;
        }

        col.appendChild(tip);
        col.appendChild(barWrap);
        col.appendChild(lbl);
        container.appendChild(col);
      }
    }

    function renderSvgChart(timeline) {
      const container = document.getElementById('chart-svg-container');
      container.innerHTML = '';
      if (!timeline || !timeline.length) {
        container.innerHTML = '<div class="w-full text-center text-xs text-gray-500 py-16 font-mono">No token history recorded for this period.</div>';
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

      timeline.forEach((item, idx) => {
        const tok = item.total_tokens || 0;
        // Calculate bar height relative to maximum, leaving room for baseline label (max 78% of column height)
        const hPct = Math.max(3, Math.round((tok / maxVal) * 78));

        const col = document.createElement('div');
        col.className = 'flex-1 min-w-0 flex flex-col items-center h-full justify-end group relative cursor-pointer px-[1.5px]';

        // Floating tooltip
        const tip = document.createElement('div');
        tip.className = 'pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 absolute -top-10 left-1/2 -translate-x-1/2 px-2 py-1 rounded-md bg-surface-3/95 backdrop-blur text-[10px] font-mono text-white whitespace-nowrap border border-hairline-strong z-30 shadow-xl flex flex-col items-center gap-0.5';
        tip.innerHTML = `
          <div class="font-semibold text-gray-200">${item.period}</div>
          <div class="text-gray-300">${fmt(tok)} tokens (${Math.round((tok / maxVal) * 100)}%)</div>
        `;

        // Bar with calm matte fill
        const barWrap = document.createElement('div');
        barWrap.className = 'w-full flex justify-center items-end';
        barWrap.style.height = `${hPct}%`;

        const bar = document.createElement('div');
        bar.className = 'w-full max-w-[14px] min-w-[3px] h-full bg-slate-500/70 group-hover:bg-slate-400 rounded-t-sm transition-all border-t border-x border-slate-400/20';
        barWrap.appendChild(bar);

        // Date label decimation
        const isLabeled = (idx === 0) || (idx === n - 1) || (idx % stride === 0 && idx < n - 2);
        
        let displayLabel = item.period;
        if (item.period && item.period.length === 10) {
          displayLabel = item.period.slice(5); // e.g. "10-02"
        }

        const lbl = document.createElement('div');
        lbl.className = 'h-5 flex items-center justify-center w-full select-none';
        if (isLabeled) {
          lbl.innerHTML = `<span class="text-[9px] font-mono text-gray-400 tracking-tight whitespace-nowrap">${displayLabel}</span>`;
        } else {
          lbl.innerHTML = `<span class="text-[7px] text-gray-600 leading-none">·</span>`;
        }

        col.appendChild(tip);
        col.appendChild(barWrap);
        col.appendChild(lbl);
        container.appendChild(col);
      });
    }

    function renderModelSplit(models, totalTokens) {
      const list = document.getElementById('model-split-list');
      list.innerHTML = '';
      if (!models.length) {
        list.innerHTML = '<div class="text-xs text-gray-500">No model usage recorded.</div>';
        return;
      }
      models.forEach(m => {
        const pct = totalTokens > 0 ? Math.round((m.total_tokens / totalTokens) * 100) : 0;
        const div = document.createElement('div');
        div.className = 'space-y-1';
        div.innerHTML = `
          <div class="flex items-center justify-between text-xs">
            <span class="font-mono text-gray-300 truncate max-w-[160px]">${m.model}</span>
            <span class="font-mono text-gray-400 font-semibold">${fmt(m.total_tokens)} (${pct}%)</span>
          </div>
          <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden">
            <div class="h-full bg-slate-400 rounded-full" style="width: ${pct}%"></div>
          </div>
        `;
        list.appendChild(div);
      });
    }

    function renderEventsTable(events) {
      const tbody = document.getElementById('token-events-tbody');
      tbody.innerHTML = '';
      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="py-3 text-center text-gray-500">No recent events found.</td></tr>';
        return;
      }
      events.slice(0, 50).forEach(ev => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-surface-2 transition-colors';
        let timeStr = '--';
        if (ev.created_at) {
          try {
            const dt = new Date(ev.created_at);
            timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          } catch(e) {
            timeStr = ev.created_at.slice(11, 19);
          }
        }
        tr.innerHTML = `
          <td class="py-1.5 px-3 text-gray-400 whitespace-nowrap">${ev.day ? ev.day.slice(5) : ''} ${timeStr}</td>
          <td class="py-1.5 px-3 text-gray-300 truncate max-w-[130px]" title="${ev.model}">${ev.model}</td>
          <td class="py-1.5 px-3 text-right text-gray-300">${fmt(ev.input_tokens)}</td>
          <td class="py-1.5 px-3 text-right text-gray-300">${fmt(ev.output_tokens)}</td>
          <td class="py-1.5 px-3 text-right text-gray-400">${fmt(ev.cache_read_tokens || 0)}</td>
          <td class="py-1.5 px-3 text-right font-bold text-gray-100">${fmt(ev.total_tokens)}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    function exportTokenData(format) {
      const sel = document.getElementById('analytics-account-select');
      const acc = sel ? sel.value : 'all';
      window.open(`/api/tokens/export?format=${format}&range=${currentTimeRange}&account=${encodeURIComponent(acc)}`, '_blank');
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
      if (!s) return { dot: '🟢', status: 'Optimal', pct: 0, textClass: 'text-emerald-400' };
      const modelStr = (s.model || '').toLowerCase();
      let maxContextLimit = 512000; // Antigravity doubled auto-compaction ceiling (512k tokens)
      if (modelStr.includes('claude')) {
        maxContextLimit = 160000;
      }
      const currentContext = s.max_context_tokens || s.avg_context_tokens || 0;
      const pct = Math.min(100, (currentContext / maxContextLimit) * 100);
      if (pct >= 85) return { dot: '🔴', status: 'Near Compaction', pct: pct, textClass: 'text-rose-400' };
      if (pct >= 60) return { dot: '🟡', status: 'Elevated', pct: pct, textClass: 'text-amber-300' };
      return { dot: '🟢', status: 'Optimal', pct: pct, textClass: 'text-emerald-400' };
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
          const compText = s.compactions > 0 ? ` • ⚡${s.compactions} ${s.compactions === 1 ? 'compact' : 'compacts'}` : '';
          opt.innerText = `${st.dot} ${title} • ${turns} turns${compText}`;
          opt.title = `${title}\nContext Load: ${st.dot} ${st.pct.toFixed(1)}% (${st.status})\nCapacity: 512k Compaction Limit\nCompactions: ${s.compactions || 0}\nTurns: ${turns}\nID: ${s.session_id}`;
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
          const compText = s.compactions > 0 ? ` • ⚡${s.compactions}` : '';
          opt.innerText = `${st.dot} ↳ ${title} • ${turns} turns${compText}`;
          opt.title = `${title}\nContext Load: ${st.dot} ${st.pct.toFixed(1)}% (${st.status})\nCapacity: 512k Compaction Limit\nCompactions: ${s.compactions || 0}\nTurns: ${turns}\nID: ${s.session_id}`;
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

    function copySessionId() {
      if (selectedSessionId) {
        navigator.clipboard.writeText(selectedSessionId);
        showToast('Session ID copied to clipboard', 'success', 2000);
      }
    }

    function renderActiveSessionCard(s) {
      if (!s) return;
      const st = getContextStatus(s);
      const titleElem = document.getElementById('session-title-display');
      if (titleElem) titleElem.innerText = `${st.dot} ${s.title || s.session_id}`;
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
      if (compPillEl) compPillEl.innerText = `⚡ ${compLabel}`;
      if (compBadgeEl) {
        if (compCount > 0) {
          compBadgeEl.className = 'inline-flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.2 rounded bg-purple-500/25 text-purple-300 border border-purple-500/40 font-semibold';
        } else {
          compBadgeEl.className = 'inline-flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.2 rounded bg-surface-2 text-gray-400 border border-hairline font-medium';
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
      const pctColor = ctxPct < 60 ? 'text-gray-200' : ctxPct < 85 ? 'text-amber-300/90' : 'text-rose-400/90';
      const pctEl = document.getElementById('session-context-pct');
      if (pctEl) {
        pctEl.className = `${pctColor} font-bold`;
        pctEl.innerText = `${st.dot} ${ctxPct.toFixed(1)}% of ${ceilingText} (${statusText})`;
      }
      
      const bar = document.getElementById('session-context-bar');
      if (bar) {
        bar.style.width = `${Math.max(1.5, ctxPct)}%`;
        if (ctxPct >= 85) {
          bar.className = 'h-full bg-rose-500/80 rounded-full transition-all duration-500';
        } else if (ctxPct >= 60) {
          bar.className = 'h-full bg-amber-500/80 rounded-full transition-all duration-500';
        } else {
          bar.className = 'h-full bg-slate-400 rounded-full transition-all duration-500';
        }
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
      tbody.innerHTML = '<tr><td colspan="10" class="py-4 text-center text-gray-500">Loading turns for session...</td></tr>';

      try {
        const res = await fetch(`/api/sessions/turns?session_id=${encodeURIComponent(sid)}&limit=100`);
        let turns = await res.json();
        if (turns && turns.turns) turns = turns.turns;
        const turnList = Array.isArray(turns) ? turns : [];

        document.getElementById('turns-table-count').innerText = `${turnList.length} steps`;
        renderSessionTurnsTable(turnList);
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="10" class="py-4 text-center text-rose-400">Failed to load turns: ${e.message}</td></tr>`;
      }
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

        const isCompaction = Boolean(turn.is_compaction);
        const isAgent = outp > 0;
        let typeBadge = isAgent
          ? `<span class="inline-flex items-center gap-1 text-[9.5px] px-1.5 py-0.5 rounded bg-white/10 text-white border border-white/20 font-sans font-medium whitespace-nowrap"><span class="w-1.5 h-1.5 rounded-full bg-white"></span>Agent Turn</span>`
          : `<span class="inline-flex items-center gap-1 text-[9.5px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-sans font-medium whitespace-nowrap"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>User Prompt</span>`;

        if (isCompaction) {
          typeBadge = `<span class="inline-flex items-center gap-1 text-[9.5px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40 font-sans font-semibold whitespace-nowrap"><span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"></span>⚡ Compaction</span>`;
        }

        const cacheEff = (inp + cache) > 0 ? ((cache / (inp + cache)) * 100) : 0;
        let badgeColor = 'bg-surface-3 text-gray-400 border-hairline';
        let badgeText = 'Full Context';
        if (cacheEff > 0) {
          badgeColor = 'bg-surface-2 text-gray-200 border-hairline';
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
        tr.className = 'hover:bg-surface-2/60 cursor-pointer transition-colors';
        tr.onclick = (e) => {
          if (!e.target.closest('button')) toggleTurnExpand(stepNum);
        };

        const isExpanded = expandedTurns.has(stepNum);

        tr.innerHTML = `
          <td class="py-1.5 px-3 text-center font-bold text-gray-400">${stepNum}</td>
          <td class="py-1.5 px-3 text-gray-400 whitespace-nowrap">${timeStr}</td>
          <td class="py-1.5 px-3 text-center">${typeBadge}</td>
          <td class="py-1.5 px-3 text-gray-200 truncate max-w-[130px]" title="${turn.model}">${modelDisplay}</td>
          <td class="py-1.5 px-3 text-right text-gray-300">${fmt(inp)}</td>
          <td class="py-1.5 px-3 text-right text-gray-300">${fmt(outp)}</td>
          <td class="py-1.5 px-3 text-right text-gray-400">${fmt(cache)}</td>
          <td class="py-1.5 px-3 text-right font-bold text-gray-100">${fmt(tot)}</td>
          <td class="py-1.5 px-3 text-center">
            <span class="text-[9px] px-1.5 py-0.2 rounded border ${badgeColor} font-sans font-medium whitespace-nowrap">
              ${badgeText}
            </span>
          </td>
          <td class="py-1.5 px-3 text-center text-gray-500">
            <button type="button" class="p-0.5 hover:text-white rounded hover:bg-surface-3 transition-colors" title="Toggle Detail">
              <svg class="w-3 h-3 transform transition-transform ${isExpanded ? 'rotate-180' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
          </td>
        `;
        tbody.appendChild(tr);

        // Expandable Detail Drawer Row
        if (isExpanded) {
          const expTr = document.createElement('tr');
          expTr.className = 'bg-surface-2/40 border-b border-hairline';
          expTr.innerHTML = `
            <td colspan="10" class="p-3 space-y-2">
              <div class="flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
                <div class="space-y-1">
                  <div class="text-gray-300 font-semibold text-[11px] flex items-center gap-2">
                    <span>Step ${stepNum} Detailed Volume Breakdown</span>
                    ${typeBadge}
                  </div>
                  <div class="flex items-center gap-3 text-[11px] text-gray-400">
                    <span>Prompt: <strong class="text-gray-200">${fmt(inp)}</strong> (${tot > 0 ? (inp/tot*100).toFixed(1) : 0}%)</span>
                    <span>Output: <strong class="text-gray-200">${fmt(outp)}</strong> (${tot > 0 ? (outp/tot*100).toFixed(1) : 0}%)</span>
                    <span>Cache Hit: <strong class="text-gray-200">${fmt(cache)}</strong></span>
                  </div>
                </div>
                <div class="text-[10.5px] font-mono text-gray-400">
                  <span>Timestamp: <strong class="text-gray-200">${turn.created_at || '--'}</strong></span>
                </div>
              </div>
              <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden flex">
                <div class="h-full bg-slate-500" style="width: ${tot > 0 ? (inp/tot*100) : 50}%" title="Input Prompt"></div>
                <div class="h-full bg-sky-500" style="width: ${tot > 0 ? (outp/tot*100) : 50}%" title="Generated Output"></div>
              </div>
            </td>
          `;
          tbody.appendChild(expTr);
        }
      });
    }

    function toggleTurnExpand(stepNum) {
      if (expandedTurns.has(stepNum)) {
        expandedTurns.delete(stepNum);
      } else {
        expandedTurns.add(stepNum);
      }
      loadSessionTurns(selectedSessionId);
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
      // Real-time Server-Sent Events stream (replaces constant 8s polling)
      let _sseFallbackTimer = null;
      function setSseState(connected) {
        const dot = document.getElementById('sse-dot');
        const lbl = document.getElementById('sse-label');
        if (dot) dot.className = connected
          ? 'w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0 mr-2 inline-block'
          : 'w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0 mr-2 inline-block';
        if (lbl) lbl.innerText = connected ? 'Live Sync' : 'Reconnecting';
      }
      function connectSSE() {
        try {
          const es = new EventSource('/api/events');
          es.onopen = () => setSseState(true);
          es.addEventListener('status', () => {
            if (!document.hidden) fetchStatus(false);
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
