// Stockify SPA — vanilla JS router + page renderers + D3 graph viz.

// ---------------------- Theme ----------------------
const savedTheme = localStorage.getItem('theme') || 'light';
document.documentElement.setAttribute('data-theme', savedTheme);
document.getElementById('theme-toggle').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
});

// ---------------------- API helpers ----------------------
async function api(path, opts = {}) {
  const r = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (r.status === 401) { window.location.href = '/'; throw new Error('unauthorized'); }
  if (!r.ok) {
    const msg = (await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`;
    throw new Error(msg);
  }
  if (r.status === 204) return null;
  return r.json();
}

// ---------------------- Utilities ----------------------
function fmtPct(p) {
  if (p === null || p === undefined) return '<span class="pct-flat">—</span>';
  const cls = p > 0 ? 'pct-up' : (p < 0 ? 'pct-down' : 'pct-flat');
  const sign = p > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${p.toFixed(2)}%</span>`;
}
function fmtMoney(v) {
  if (v === null || v === undefined) return '<span class="pct-flat">—</span>';
  return `<span class="mono">$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
}
function fmtShares(v) {
  return `<span class="mono">${v.toLocaleString(undefined, { maximumFractionDigits: 4 })}</span>`;
}
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

// ---------------------- Auth header ----------------------
let CURRENT_USER = null;
async function loadUser() {
  try {
    CURRENT_USER = await api('/auth/me');
    document.getElementById('user-info').innerHTML =
      `<div class="mono text-xs text-soft">${escapeHtml(CURRENT_USER.email)}</div>`;
  } catch (_) {
    window.location.href = '/';
  }
}

document.getElementById('logout-btn').addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/';
});

// ---------------------- Router ----------------------
function parseRoute() {
  const hash = window.location.hash.slice(1) || 'dashboard';
  const [name, ...args] = hash.split('/');
  return { name, args };
}

function navigate(route) {
  window.location.hash = '#' + route;
}

function setActiveNav(name) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.route === name);
  });
}

document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', e => { e.preventDefault(); navigate(el.dataset.route); });
});

window.addEventListener('hashchange', render);
window.addEventListener('load', async () => {
  await loadUser();
  render();
});

async function render() {
  const { name, args } = parseRoute();
  setActiveNav(name);
  const main = document.getElementById('main');
  main.innerHTML = '<div class="loading"><span class="spinner"></span>Loading…</div>';
  try {
    switch (name) {
      case 'dashboard': await renderDashboard(main); break;
      case 'watchlist': await renderWatchlist(main); break;
      case 'portfolio': await renderPortfolio(main); break;
      case 'alerts': await renderAlerts(main); break;
      case 'compare': await renderCompare(main, args); break;
      case 'ticker': await renderTicker(main, args[0]); break;
      default: main.innerHTML = `<div class="banner banner-error">Unknown route: ${name}</div>`;
    }
  } catch (err) {
    main.innerHTML = `<div class="banner banner-error">${escapeHtml(err.message)}</div>`;
  }
}

// ---------------------- Dashboard ----------------------
async function renderDashboard(main) {
  const [watchlist, portfolio, alerts] = await Promise.all([
    api('/watchlist').catch(() => []),
    api('/portfolio').catch(() => null),
    api('/alerts').catch(() => ({ alerts: [] })),
  ]);

  const greeting = CURRENT_USER?.display_name || 'there';

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Hi, ${escapeHtml(greeting)}</div>
        <div class="text-soft text-sm">Quick look at your stocks today.</div>
      </div>
      <form id="quick-brief" class="flex gap-1">
        <input class="input input-mono" style="width:160px;" id="quick-ticker" placeholder="NVDA" maxlength="5" autocomplete="off" />
        <button class="btn btn-primary btn-sm" type="submit">Brief</button>
      </form>
    </div>

    <div class="grid grid-3 mb-3">
      <div class="card card-compact">
        <div class="text-xs text-soft">Watchlist</div>
        <div class="mono" style="font-size:1.6rem;">${watchlist.length}</div>
      </div>
      <div class="card card-compact">
        <div class="text-xs text-soft">Positions</div>
        <div class="mono" style="font-size:1.6rem;">${portfolio?.position_count || 0}</div>
      </div>
      <div class="card card-compact">
        <div class="text-xs text-soft">Portfolio value</div>
        <div class="mono" style="font-size:1.6rem;">${portfolio?.total_value !== null && portfolio?.total_value !== undefined
          ? '$' + portfolio.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })
          : '—'}</div>
        <div class="text-xs">${fmtPct(portfolio?.total_pnl_pct)} unrealized</div>
      </div>
    </div>

    ${alerts.alerts?.length ? `
      <div class="card mb-3">
        <h3 class="card-title">Alerts · moved >5% this week</h3>
        <div class="card-subtitle">Tickers from your watchlist with notable 7-day moves.</div>
        <table class="table">
          <tbody>
            ${alerts.alerts.map(a => `
              <tr>
                <td class="mono">${a.ticker}</td>
                <td>${a.direction === 'up' ? 'moved up' : 'moved down'}</td>
                <td class="num">${fmtPct(a.pct_change_7d)}</td>
                <td class="num"><a href="#ticker/${a.ticker}">View brief →</a></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    ` : ''}

    <div class="grid grid-2">
      <div class="card">
        <div class="flex items-center justify-between mb-2">
          <h3 class="card-title">Watchlist</h3>
          <a href="#watchlist" class="btn btn-ghost btn-sm">Manage →</a>
        </div>
        ${watchlist.length === 0
          ? `<div class="text-sm text-muted">No tickers yet. Add one from the watchlist page.</div>`
          : `<table class="table">
              <tbody>
                ${watchlist.slice(0, 5).map(w => `
                  <tr>
                    <td class="mono"><a href="#ticker/${w.ticker}">${w.ticker}</a></td>
                    <td class="num">${fmtMoney(w.current_price)}</td>
                    <td class="num">${fmtPct(w.pct_change_7d)}</td>
                  </tr>`).join('')}
              </tbody>
            </table>`
        }
      </div>

      <div class="card">
        <div class="flex items-center justify-between mb-2">
          <h3 class="card-title">Top positions</h3>
          <a href="#portfolio" class="btn btn-ghost btn-sm">Manage →</a>
        </div>
        ${!portfolio || portfolio.holdings.length === 0
          ? `<div class="text-sm text-muted">No holdings yet. Add one from the portfolio page.</div>`
          : `<table class="table">
              <tbody>
                ${portfolio.holdings.slice(0, 5).map(h => `
                  <tr>
                    <td class="mono"><a href="#ticker/${h.ticker}">${h.ticker}</a></td>
                    <td class="num">${fmtMoney(h.market_value)}</td>
                    <td class="num">${fmtPct(h.unrealized_pnl_pct)}</td>
                  </tr>`).join('')}
              </tbody>
            </table>`
        }
      </div>
    </div>
  `;

  document.getElementById('quick-brief').addEventListener('submit', e => {
    e.preventDefault();
    const t = document.getElementById('quick-ticker').value.trim().toUpperCase();
    if (t) navigate(`ticker/${t}`);
  });
}

// ---------------------- Watchlist ----------------------
async function renderWatchlist(main) {
  const items = await api('/watchlist');
  main.innerHTML = `
    <div class="page-header">
      <div class="page-title">Watchlist</div>
      <form id="add-form" class="flex gap-1">
        <input class="input input-mono" style="width:160px;" id="add-ticker" placeholder="Add ticker" maxlength="5" />
        <button class="btn btn-primary btn-sm" type="submit">Add</button>
      </form>
    </div>

    <div class="card">
      ${items.length === 0 ? `<div class="text-sm text-muted">No tickers yet. Add one above.</div>` : `
        <table class="table">
          <thead><tr><th>Ticker</th><th class="num">Price</th><th class="num">7-day</th><th></th></tr></thead>
          <tbody>
            ${items.map(w => `
              <tr>
                <td class="mono"><a href="#ticker/${w.ticker}">${w.ticker}</a></td>
                <td class="num">${fmtMoney(w.current_price)}</td>
                <td class="num">${fmtPct(w.pct_change_7d)}</td>
                <td class="num"><button class="btn btn-danger btn-sm" data-remove="${w.ticker}">Remove</button></td>
              </tr>`).join('')}
          </tbody>
        </table>
      `}
    </div>
  `;

  document.getElementById('add-form').addEventListener('submit', async e => {
    e.preventDefault();
    const t = document.getElementById('add-ticker').value.trim().toUpperCase();
    if (!t) return;
    await api('/watchlist', { method: 'POST', body: JSON.stringify({ ticker: t }) });
    render();
  });

  main.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api(`/watchlist/${btn.dataset.remove}`, { method: 'DELETE' });
      render();
    });
  });
}

// ---------------------- Portfolio ----------------------
function renderRiskProfile(rp) {
  if (!rp) return '';

  const beta = rp.portfolio_beta;
  let betaHint = '—';
  if (beta !== null && beta !== undefined) {
    if (beta > 1.3) betaHint = 'more volatile than S&P 500';
    else if (beta < 0.7) betaHint = 'less volatile than S&P 500';
    else betaHint = 'moves with the market';
  }

  const concColor = rp.concentration.level === 'diversified' ? 'var(--up)'
    : rp.concentration.level === 'moderate' ? 'var(--warn)'
    : 'var(--down)';

  const top = rp.top_position;
  const topLine = top
    ? `<a href="#ticker/${top.ticker}" class="mono">${top.ticker}</a> · ${top.weight_pct.toFixed(1)}% of portfolio`
    : '—';

  // Sector bar palette — distinct enough to read without legend noise
  const palette = ['#0a3d62', '#c89f3c', '#0d8f5c', '#6b5b95', '#b5651d', '#8a9ba8', '#4a6fa5', '#9c6b30', '#5d7b6f', '#a85c5c'];
  const sectorBars = rp.sector_exposure.map((s, i) => `
    <div style="margin-bottom:0.5rem;">
      <div class="flex justify-between" style="font-size:0.8rem; margin-bottom:0.2rem;">
        <span>${escapeHtml(s.sector)}</span>
        <span class="mono">${s.weight_pct.toFixed(1)}%</span>
      </div>
      <div style="background:var(--bg-subtle); height:8px; border-radius:var(--radius-sm); overflow:hidden;">
        <div style="width:${Math.min(s.weight_pct, 100)}%; height:100%; background:${palette[i % palette.length]};"></div>
      </div>
    </div>`).join('');

  const coverageNote = rp.coverage_pct < 100
    ? `<div class="text-xs text-soft mt-1">Based on ${rp.coverage_pct.toFixed(0)}% of portfolio value (some tickers had incomplete data).</div>`
    : '';

  return `
    <div class="card mb-3">
      <div class="flex items-center justify-between mb-2">
        <h3 class="card-title" style="margin-bottom:0;">Risk profile</h3>
        <span class="text-xs text-soft">Portfolio-level analytics</span>
      </div>

      <div class="grid grid-3 mb-3">
        <div class="card card-compact" title="Weighted-average beta of your holdings vs the S&P 500. >1 = amplifies market moves, <1 = dampens them.">
          <div class="text-xs text-soft" style="text-transform:uppercase; letter-spacing:0.06em;">Portfolio beta</div>
          <div class="mono" style="font-size:1.35rem; font-weight:500; margin-top:0.15rem;">
            ${beta !== null && beta !== undefined ? beta.toFixed(2) : '—'}
          </div>
          <div class="text-xs text-soft">${betaHint}</div>
        </div>
        <div class="card card-compact" title="Herfindahl index on position weights. Higher = more concentrated. <0.15 diversified, 0.15–0.30 moderate, >0.30 concentrated.">
          <div class="text-xs text-soft" style="text-transform:uppercase; letter-spacing:0.06em;">Concentration</div>
          <div style="font-size:1.2rem; font-weight:500; margin-top:0.15rem; color:${concColor}; text-transform:capitalize;">
            ${rp.concentration.level}
          </div>
          <div class="text-xs text-soft">HHI ${rp.concentration_hhi.toFixed(2)} · ${escapeHtml(rp.concentration.message)}</div>
        </div>
        <div class="card card-compact" title="Largest single-position weight. High values mean one stock dominates your portfolio's fate.">
          <div class="text-xs text-soft" style="text-transform:uppercase; letter-spacing:0.06em;">Top position</div>
          <div style="font-size:1.2rem; font-weight:500; margin-top:0.15rem;">${topLine}</div>
        </div>
      </div>

      <div>
        <div class="text-xs text-soft mb-1" style="text-transform:uppercase; letter-spacing:0.06em; font-weight:500;">Sector exposure</div>
        ${sectorBars || '<div class="text-sm text-muted">No sector data available.</div>'}
        ${coverageNote}
      </div>
    </div>
  `;
}

async function renderPortfolio(main) {
  const p = await api('/portfolio');
  main.innerHTML = `
    <div class="page-header">
      <div class="page-title">Portfolio</div>
      <button class="btn btn-primary btn-sm" id="add-btn">+ Add holding</button>
    </div>

    <div class="grid grid-3 mb-3">
      <div class="card card-compact">
        <div class="text-xs text-soft">Total cost</div>
        <div class="mono" style="font-size:1.4rem;">$${p.total_cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
      </div>
      <div class="card card-compact">
        <div class="text-xs text-soft">Market value</div>
        <div class="mono" style="font-size:1.4rem;">${p.total_value !== null && p.total_value !== undefined ? '$' + p.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—'}</div>
      </div>
      <div class="card card-compact">
        <div class="text-xs text-soft">Unrealized P&L</div>
        <div class="mono" style="font-size:1.4rem;">${p.total_pnl !== null && p.total_pnl !== undefined
          ? (p.total_pnl >= 0 ? '+' : '') + '$' + Math.abs(p.total_pnl).toLocaleString(undefined, { maximumFractionDigits: 0 })
          : '—'}</div>
        <div class="text-xs">${fmtPct(p.total_pnl_pct)}</div>
      </div>
    </div>

    ${renderRiskProfile(p.risk_profile)}

    <div class="card">
      ${p.holdings.length === 0 ? `<div class="text-sm text-muted">No holdings yet.</div>` : `
        <table class="table">
          <thead>
            <tr>
              <th>Ticker</th><th class="num">Shares</th><th class="num">Cost</th>
              <th class="num">Price</th><th class="num">Market value</th>
              <th class="num">P&L</th><th></th>
            </tr>
          </thead>
          <tbody>
            ${p.holdings.map(h => `
              <tr>
                <td class="mono"><a href="#ticker/${h.ticker}">${h.ticker}</a></td>
                <td class="num">${fmtShares(h.shares)}</td>
                <td class="num">${fmtMoney(h.cost_basis)}</td>
                <td class="num">${fmtMoney(h.current_price)}</td>
                <td class="num">${fmtMoney(h.market_value)}</td>
                <td class="num">${fmtPct(h.unrealized_pnl_pct)}</td>
                <td class="num"><button class="btn btn-danger btn-sm" data-del="${h.id}">Remove</button></td>
              </tr>`).join('')}
          </tbody>
        </table>
      `}
    </div>

    <div id="add-modal" class="hidden" style="position:fixed;inset:0;background:rgba(0,0,0,0.35);z-index:100;display:flex;align-items:center;justify-content:center;padding:1rem;">
      <div class="card" style="width:100%;max-width:420px;box-shadow:var(--shadow-lg);">
        <div class="flex items-center justify-between mb-2">
          <h3 class="card-title">Add a holding</h3>
          <button class="btn btn-ghost btn-icon" id="close-add">✕</button>
        </div>
        <form id="add-holding-form">
          <div class="mb-2"><label class="label">Ticker</label><input class="input input-mono" id="h-ticker" maxlength="5" required /></div>
          <div class="mb-2"><label class="label">Shares</label><input class="input mono" id="h-shares" type="number" step="0.0001" min="0.0001" required /></div>
          <div class="mb-3"><label class="label">Average cost per share (USD)</label><input class="input mono" id="h-cost" type="number" step="0.01" min="0.01" required /></div>
          <button type="submit" class="btn btn-primary w-full">Add</button>
        </form>
      </div>
    </div>
  `;

  const modal = document.getElementById('add-modal');
  document.getElementById('add-btn').addEventListener('click', () => modal.classList.remove('hidden'));
  document.getElementById('close-add').addEventListener('click', () => modal.classList.add('hidden'));
  modal.addEventListener('click', e => { if (e.target === modal) modal.classList.add('hidden'); });

  document.getElementById('add-holding-form').addEventListener('submit', async e => {
    e.preventDefault();
    const body = {
      ticker: document.getElementById('h-ticker').value.trim().toUpperCase(),
      shares: parseFloat(document.getElementById('h-shares').value),
      cost_basis: parseFloat(document.getElementById('h-cost').value),
    };
    await api('/holdings', { method: 'POST', body: JSON.stringify(body) });
    render();
  });

  main.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      await api(`/holdings/${btn.dataset.del}`, { method: 'DELETE' });
      render();
    });
  });
}

// ---------------------- Alerts ----------------------
async function renderAlerts(main) {
  const { alerts } = await api('/alerts');
  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title">Alerts</div>
        <div class="text-soft text-sm">Watchlist tickers that moved more than 5% in the past 7 days.</div>
      </div>
    </div>
    <div class="card">
      ${alerts.length === 0 ? `<div class="text-sm text-muted">No alerts right now. Add tickers to your watchlist to monitor them.</div>` : `
        <table class="table">
          <thead><tr><th>Ticker</th><th>Direction</th><th class="num">7-day</th><th></th></tr></thead>
          <tbody>
            ${alerts.map(a => `
              <tr>
                <td class="mono">${a.ticker}</td>
                <td>${a.direction === 'up' ? 'moved up' : 'moved down'}</td>
                <td class="num">${fmtPct(a.pct_change_7d)}</td>
                <td class="num"><a href="#ticker/${a.ticker}">View brief →</a></td>
              </tr>`).join('')}
          </tbody>
        </table>
      `}
    </div>
  `;
}

// ---------------------- Compare ----------------------
async function renderCompare(main, args) {
  const tickers = args.filter(Boolean);
  main.innerHTML = `
    <div class="page-header">
      <div class="page-title">Compare</div>
      <form id="cmp-form" class="flex gap-1">
        <input class="input input-mono" id="c1" style="width:120px;" placeholder="Ticker A" maxlength="5" value="${tickers[0] || ''}" />
        <input class="input input-mono" id="c2" style="width:120px;" placeholder="Ticker B" maxlength="5" value="${tickers[1] || ''}" />
        <button class="btn btn-primary btn-sm">Compare</button>
      </form>
    </div>
    <div id="cmp-body">
      ${tickers.length < 2 ? `<div class="text-sm text-muted">Enter two tickers to compare their knowledge-graph context side-by-side.</div>` : `<div class="loading"><span class="spinner"></span>Loading…</div>`}
    </div>
  `;

  document.getElementById('cmp-form').addEventListener('submit', e => {
    e.preventDefault();
    const a = document.getElementById('c1').value.trim().toUpperCase();
    const b = document.getElementById('c2').value.trim().toUpperCase();
    if (a && b) navigate(`compare/${a}/${b}`);
  });

  if (tickers.length >= 2) {
    const [ctxA, ctxB] = await Promise.all([
      api(`/context/${tickers[0]}`).catch(e => ({ error: e.message })),
      api(`/context/${tickers[1]}`).catch(e => ({ error: e.message })),
    ]);
    document.getElementById('cmp-body').innerHTML = `
      <div class="grid grid-2">
        ${[ctxA, ctxB].map((c, i) => `
          <div class="card">
            <h3 class="card-title mono">${tickers[i]}</h3>
            ${c.error ? `<div class="banner banner-error">${escapeHtml(c.error)}</div>` : `
              <div class="card-subtitle">${escapeHtml(c.company_name || '')} · ${escapeHtml(c.sector || '')}</div>
              ${renderCompareTable('Competitors', c.competitors)}
              ${renderCompareTable('Suppliers', c.key_suppliers)}
              ${renderCompareTable('Customers', c.key_customers)}
              ${renderMacroTable(c.macro_factors)}
            `}
          </div>
        `).join('')}
      </div>`;
  }
}
function renderCompareTable(title, items) {
  if (!items || items.length === 0) return '';
  return `
    <div class="mb-2"><div class="text-xs text-soft" style="text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.3rem;">${title}</div>
      <table class="table">
        <tbody>${items.slice(0, 5).map(i => `
          <tr><td class="mono">${i.ticker}</td><td class="text-sm">${escapeHtml(i.name || '')}</td><td class="num">${fmtPct(i.pct_change_7d)}</td></tr>
        `).join('')}</tbody>
      </table>
    </div>`;
}
function renderMacroTable(items) {
  if (!items || items.length === 0) return '';
  return `
    <div class="mb-2"><div class="text-xs text-soft" style="text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.3rem;">Macro factors</div>
      <table class="table">
        <tbody>${items.slice(0, 4).map(i => `
          <tr><td class="text-sm">${escapeHtml(i.factor_name || i.factor_id)}</td><td class="text-xs text-soft">${escapeHtml(i.direction || '')}</td><td class="num">${fmtPct(i.pct_change_7d)}</td></tr>
        `).join('')}</tbody>
      </table>
    </div>`;
}

// ---------------------- Ticker / Brief + Graph ----------------------
async function renderTicker(main, rawTicker) {
  const ticker = (rawTicker || '').toUpperCase();
  if (!ticker) { main.innerHTML = `<div class="banner banner-error">No ticker specified.</div>`; return; }

  // Pull watchlist status to show add/remove button
  let inWatchlist = false;
  try {
    const wl = await api('/watchlist');
    inWatchlist = wl.some(w => w.ticker === ticker);
  } catch (_) {}

  main.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-title mono">${ticker}</div>
        <div class="text-soft text-sm" id="company-sub">Loading context…</div>
      </div>
      <div class="flex gap-1">
        <button class="btn btn-secondary btn-sm" id="wl-btn">${inWatchlist ? '★ On watchlist' : '+ Watchlist'}</button>
        <button class="btn btn-primary btn-sm" id="refresh-btn">Refresh</button>
      </div>
    </div>

    <div id="risk-stats" class="mb-3"></div>

    <div class="grid grid-2">
      <div>
        <div class="card mb-3">
          <div class="flex items-center justify-between gap-1 mb-1" style="flex-wrap: wrap;">
            <h3 class="card-title" style="margin-bottom:0;">Brief</h3>
            <div id="earnings-chip"></div>
          </div>
          <div class="card-subtitle" id="brief-meta">Generating…</div>
          <div id="brief-body" class="prose"><div class="loading"><span class="spinner"></span>Brief is generating. This takes 30–60 seconds.</div></div>
        </div>
      </div>

      <div>
        <div class="card mb-3">
          <h3 class="card-title">Knowledge graph</h3>
          <div class="card-subtitle">Competitors, suppliers, customers, and macro factors with 7-day moves. Click any node to pivot.</div>
          <div class="graph-container" id="graph"></div>
        </div>
        <div class="card mb-3">
          <h3 class="card-title">Peer valuation</h3>
          <div class="card-subtitle">${ticker} vs top competitors — how expensive is the stock relative to peers?</div>
          <div id="peer-valuation"><div class="loading"><span class="spinner"></span>Loading peers…</div></div>
        </div>
        <div class="card">
          <h3 class="card-title">Relationships</h3>
          <div id="context-tables" class="mt-2"><div class="loading"><span class="spinner"></span>Loading context…</div></div>
        </div>
      </div>
    </div>
  `;

  document.getElementById('wl-btn').addEventListener('click', async (e) => {
    if (inWatchlist) {
      await api(`/watchlist/${ticker}`, { method: 'DELETE' });
      e.currentTarget.textContent = '+ Watchlist';
      inWatchlist = false;
    } else {
      await api('/watchlist', { method: 'POST', body: JSON.stringify({ ticker }) });
      e.currentTarget.textContent = '★ On watchlist';
      inWatchlist = true;
    }
  });

  document.getElementById('refresh-btn').addEventListener('click', () => render());

  // Fire context first (fast) and brief in parallel
  loadContext(ticker);
  loadBrief(ticker);
}

async function loadContext(ticker) {
  try {
    const ctx = await api(`/context/${ticker}`);
    document.getElementById('company-sub').textContent =
      [ctx.company_name, ctx.sector, ctx.sub_industry].filter(Boolean).join(' · ') || '—';
    if (ctx.error) {
      document.getElementById('context-tables').innerHTML = `<div class="banner banner-warn">${escapeHtml(ctx.error)}</div>`;
      document.getElementById('graph').innerHTML = `<div class="loading" style="padding:1rem;">No knowledge graph data for ${ticker}.</div>`;
      return;
    }
    drawGraph(ctx);
    const peerEl = document.getElementById('peer-valuation');
    if (peerEl) peerEl.innerHTML = renderPeerValuation(ctx.peer_valuation);
    document.getElementById('context-tables').innerHTML =
      renderCompareTable('Competitors', ctx.competitors)
      + renderCompareTable('Key suppliers', ctx.key_suppliers)
      + renderCompareTable('Key customers', ctx.key_customers)
      + renderMacroTable(ctx.macro_factors);
  } catch (err) {
    document.getElementById('context-tables').innerHTML = `<div class="banner banner-error">${escapeHtml(err.message)}</div>`;
  }
}

async function loadBrief(ticker) {
  const meta = document.getElementById('brief-meta');
  const body = document.getElementById('brief-body');
  const chip = document.getElementById('earnings-chip');
  const risk = document.getElementById('risk-stats');
  try {
    const r = await api('/brief', { method: 'POST', body: JSON.stringify({ ticker, experience_level: 'first_year' }) });
    meta.textContent = r.cached ? 'Served from cache (<4h old). Click Refresh for live generation.' : 'Generated just now.';
    body.innerHTML = marked.parse(r.full_brief);
    if (chip) chip.innerHTML = renderEarningsChip(r);
    if (risk) risk.innerHTML = renderRiskStats(r.risk_metrics);
  } catch (err) {
    body.innerHTML = `<div class="banner banner-error">${escapeHtml(err.message)}</div>`;
    meta.textContent = '';
    if (chip) chip.innerHTML = '';
    if (risk) risk.innerHTML = '';
  }
}

function renderRiskStats(rm) {
  if (!rm) return '';
  const hasAny = ['beta_1y','volatility_30d_annualized_pct','max_drawdown_1y_pct','sharpe_1y']
    .some(k => rm[k] !== null && rm[k] !== undefined);
  if (!hasAny) return '';

  const beta = rm.beta_1y;
  let betaHint = '—';
  if (beta !== null && beta !== undefined) {
    if (beta > 1.3) betaHint = 'more volatile than market';
    else if (beta < 0.7) betaHint = 'less volatile than market';
    else betaHint = 'moves with the market';
  }

  const vol = rm.volatility_30d_annualized_pct;
  const volLabel = rm.volatility_label || '—';
  const dd = rm.max_drawdown_1y_pct;
  const sharpe = rm.sharpe_1y;
  const sharpeHint = sharpe === null || sharpe === undefined ? '—'
    : sharpe > 1 ? 'strong risk-adjusted return'
    : sharpe > 0 ? 'positive risk-adjusted return'
    : 'negative risk-adjusted return';

  const cell = (label, value, hint, tooltip) => `
    <div class="card card-compact" title="${tooltip}" style="flex:1;">
      <div class="text-xs text-soft" style="text-transform:uppercase; letter-spacing:0.06em;">${label}</div>
      <div class="mono" style="font-size:1.35rem; font-weight:500; margin-top:0.15rem;">${value}</div>
      <div class="text-xs text-soft" style="margin-top:0.1rem;">${hint}</div>
    </div>`;

  return `
    <div class="flex gap-1" style="flex-wrap:wrap;">
      ${cell(
        'Beta (1y)',
        beta !== null && beta !== undefined ? beta.toFixed(2) : '—',
        betaHint,
        'Beta measures how much the stock moves when the S&P 500 moves 1%. >1 = more volatile than market, <1 = less.'
      )}
      ${cell(
        'Volatility (30d)',
        vol !== null && vol !== undefined ? vol.toFixed(1) + '%' : '—',
        volLabel,
        '30-day annualized volatility — how much the stock typically swings in a year based on recent daily moves.'
      )}
      ${cell(
        'Max drawdown (1y)',
        dd !== null && dd !== undefined ? dd.toFixed(1) + '%' : '—',
        'worst peak-to-trough over 1y',
        'The largest peak-to-trough decline over the last year. A sense of worst-case pain.'
      )}
      ${cell(
        'Sharpe (1y)',
        sharpe !== null && sharpe !== undefined ? sharpe.toFixed(2) : '—',
        sharpeHint,
        'Sharpe ratio: return per unit of risk, assuming a 4.5% risk-free rate. >1 is generally considered good.'
      )}
    </div>`;
}

function fmtMarketCap(v) {
  if (v === null || v === undefined) return '<span class="pct-flat">—</span>';
  const abs = Math.abs(v);
  if (abs >= 1e12) return `<span class="mono">$${(v / 1e12).toFixed(2)}T</span>`;
  if (abs >= 1e9)  return `<span class="mono">$${(v / 1e9).toFixed(1)}B</span>`;
  if (abs >= 1e6)  return `<span class="mono">$${(v / 1e6).toFixed(1)}M</span>`;
  return `<span class="mono">$${v.toLocaleString()}</span>`;
}

function fmtRatio(v, digits = 1) {
  if (v === null || v === undefined || !isFinite(v)) return '<span class="pct-flat">—</span>';
  return `<span class="mono">${v.toFixed(digits)}</span>`;
}

function renderPeerValuation(rows) {
  if (!rows || rows.length === 0) {
    return '<div class="text-sm text-muted">No peer data available for this ticker.</div>';
  }
  // Compute medians across non-target rows for relative shading
  const peers = rows.filter(r => !r.is_target);
  const medians = {};
  ['trailing_pe', 'forward_pe', 'ev_to_ebitda', 'revenue_growth_yoy'].forEach(k => {
    const vals = peers.map(r => r[k]).filter(v => v !== null && v !== undefined && isFinite(v)).sort((a, b) => a - b);
    medians[k] = vals.length ? vals[Math.floor(vals.length / 2)] : null;
  });

  // Cheaper P/E or EV/EBITDA vs peer median = green (relatively cheap); higher = red.
  // Higher revenue growth vs peer median = green; lower = red.
  function cellCmp(v, med, higherBetter) {
    if (v === null || v === undefined || med === null) return '';
    const better = higherBetter ? v > med : v < med;
    if (Math.abs(v - med) / Math.max(Math.abs(med), 1e-9) < 0.05) return '';
    return better ? 'pct-up' : 'pct-down';
  }

  const rowsHtml = rows.map(r => {
    const shade = r.is_target ? 'style="background: var(--accent-soft);"' : '';
    const growthPct = (r.revenue_growth_yoy !== null && r.revenue_growth_yoy !== undefined)
      ? fmtPct(r.revenue_growth_yoy * 100)
      : '<span class="pct-flat">—</span>';
    const peClass = cellCmp(r.trailing_pe, medians.trailing_pe, false);
    const fpeClass = cellCmp(r.forward_pe, medians.forward_pe, false);
    const evClass = cellCmp(r.ev_to_ebitda, medians.ev_to_ebitda, false);
    return `
      <tr ${shade}>
        <td class="mono" style="font-weight:${r.is_target ? '700' : '500'};">
          ${r.ticker}${r.is_target ? ' <span class="text-xs text-soft">(this stock)</span>' : ''}
        </td>
        <td class="num">${fmtMarketCap(r.market_cap)}</td>
        <td class="num"><span class="${peClass} mono">${r.trailing_pe ? r.trailing_pe.toFixed(1) : '—'}</span></td>
        <td class="num"><span class="${fpeClass} mono">${r.forward_pe ? r.forward_pe.toFixed(1) : '—'}</span></td>
        <td class="num"><span class="${evClass} mono">${r.ev_to_ebitda ? r.ev_to_ebitda.toFixed(1) : '—'}</span></td>
        <td class="num">${growthPct}</td>
      </tr>`;
  }).join('');

  return `
    <table class="table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th class="num">Market cap</th>
          <th class="num" title="Price ÷ trailing 12-month earnings. Lower = cheaper vs peers.">P/E</th>
          <th class="num" title="Price ÷ next 12-month expected earnings.">Fwd P/E</th>
          <th class="num" title="Enterprise value ÷ EBITDA. Capital-structure-neutral valuation.">EV/EBITDA</th>
          <th class="num" title="Year-over-year revenue growth.">Rev growth</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>
    <div class="text-xs text-soft mt-1">Green = cheaper valuation or faster growth vs peer median. Red = more expensive or slower. Hover column headers for definitions.</div>
  `;
}

function renderEarningsChip(r) {
  if (r.earnings_window === 'pre_earnings') {
    const d = r.days_until_earnings;
    const when = d === 0 ? 'today' : d === 1 ? 'tomorrow' : `in ${d} days`;
    const date = r.next_earnings_date ? ` · ${r.next_earnings_date}` : '';
    return `<span class="chip chip-lg chip-warn" title="Stock may see higher-than-usual price swings before and after the report.">⏱ Earnings ${when}${date}</span>`;
  }
  if (r.earnings_window === 'post_earnings') {
    const d = r.days_since_last_earnings;
    const when = d === 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`;
    return `<span class="chip chip-lg chip-accent" title="Most recent earnings report — the brief leads with beat/miss framing.">📊 Reported ${when}</span>`;
  }
  return '';
}

// ---------------------- D3 Knowledge Graph ----------------------
function drawGraph(ctx) {
  const container = document.getElementById('graph');
  container.innerHTML = '';
  const width = container.clientWidth;
  const height = container.clientHeight;

  const center = { id: ctx.ticker, label: ctx.ticker, group: 'self', size: 28, color: 'var(--accent)' };
  const nodes = [center];
  const links = [];

  const colorMap = {
    competes_with: '#c92a2a',
    supplies_to: '#0d8f5c',
    supplied_by: '#0d8f5c',
    customer_of: '#0a3d62',
    macro_sensitivity: '#c89f3c',
  };

  (ctx.competitors || []).slice(0, 5).forEach(c => {
    nodes.push({ id: c.ticker, label: c.ticker, group: 'competitor', size: 14, pct: c.pct_change_7d, name: c.name });
    links.push({ source: ctx.ticker, target: c.ticker, type: 'competes_with' });
  });
  (ctx.key_suppliers || []).slice(0, 4).forEach(s => {
    if (!nodes.find(n => n.id === s.ticker)) {
      nodes.push({ id: s.ticker, label: s.ticker, group: 'supplier', size: 14, pct: s.pct_change_7d, name: s.name });
      links.push({ source: s.ticker, target: ctx.ticker, type: 'supplies_to' });
    }
  });
  (ctx.key_customers || []).slice(0, 4).forEach(c => {
    if (!nodes.find(n => n.id === c.ticker)) {
      nodes.push({ id: c.ticker, label: c.ticker, group: 'customer', size: 14, pct: c.pct_change_7d, name: c.name });
      links.push({ source: ctx.ticker, target: c.ticker, type: 'customer_of' });
    }
  });
  (ctx.macro_factors || []).slice(0, 4).forEach(m => {
    const mid = 'M:' + m.factor_id;
    nodes.push({ id: mid, label: m.factor_name || m.factor_id, group: 'macro', size: 12, pct: m.pct_change_7d, isMacro: true });
    links.push({ source: ctx.ticker, target: mid, type: 'macro_sensitivity' });
  });

  const svg = d3.select(container).append('svg')
    .attr('width', width).attr('height', height).attr('viewBox', [0, 0, width, height]);

  const legend = d3.select(container).append('div').attr('class', 'graph-legend').html(`
    <div><span class="graph-legend-dot" style="background:#c92a2a"></span>Competitor</div>
    <div><span class="graph-legend-dot" style="background:#0d8f5c"></span>Supplier → Customer</div>
    <div><span class="graph-legend-dot" style="background:#0a3d62"></span>Customer of</div>
    <div><span class="graph-legend-dot" style="background:#c89f3c"></span>Macro factor</div>
  `);

  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(100))
    .force('charge', d3.forceManyBody().strength(-240))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(d => d.size + 6));

  const link = svg.append('g')
    .attr('stroke-opacity', 0.55)
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', d => colorMap[d.type] || '#999')
    .attr('stroke-width', 1.4);

  const node = svg.append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .style('cursor', d => d.group === 'self' || d.isMacro ? 'default' : 'pointer')
    .call(drag(simulation))
    .on('click', (event, d) => {
      if (d.group !== 'self' && !d.isMacro) navigate(`ticker/${d.id}`);
    });

  node.append('circle')
    .attr('r', d => d.size)
    .attr('fill', d => d.color || {
      self: 'var(--accent)',
      competitor: '#c92a2a',
      supplier: '#0d8f5c',
      customer: '#0a3d62',
      macro: '#c89f3c',
    }[d.group])
    .attr('stroke', 'var(--bg)')
    .attr('stroke-width', 2.5);

  node.append('text')
    .text(d => d.label)
    .attr('text-anchor', 'middle')
    .attr('dy', d => d.size + 12)
    .attr('fill', 'var(--text)')
    .attr('font-size', d => d.group === 'self' ? 13 : 11)
    .attr('font-family', 'var(--font-mono)')
    .attr('font-weight', d => d.group === 'self' ? 600 : 400);

  node.append('text')
    .text(d => (d.pct !== null && d.pct !== undefined) ? `${d.pct > 0 ? '+' : ''}${d.pct.toFixed(1)}%` : '')
    .attr('text-anchor', 'middle')
    .attr('dy', 3.5)
    .attr('fill', 'white')
    .attr('font-size', 9)
    .attr('font-family', 'var(--font-mono)')
    .attr('font-weight', 600);

  node.append('title').text(d => d.name ? `${d.id} — ${d.name}` : d.label);

  simulation.on('tick', () => {
    link
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('transform', d => `translate(${d.x},${d.y})`);
  });
}

function drag(simulation) {
  return d3.drag()
    .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
    .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; });
}
