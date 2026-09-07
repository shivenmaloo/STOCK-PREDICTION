// ==========================================================
// Stock AI Research Terminal — frontend logic (Phase 1)
// Vanilla JS, no build step. Talks to the FastAPI backend at
// the same origin under /api/*.
// ==========================================================

const API_BASE = "/api";
let currentAnalyzerTicker = null;
let currentAnalyzerPeriod = "6mo";

// ----------------------------------------------------------- utilities
async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function apiPost(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST" });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

async function apiPostJson(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function apiDelete(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function renderProgressBar(label, valuePct, variant = "accent", valueText = null) {
  const clamped = Math.max(0, Math.min(100, valuePct));
  return `
    <div class="progress-label-row">
      <span class="progress-label-row__title">${label}</span>
      <span class="progress-label-row__value">${valueText !== null ? valueText : clamped.toFixed(0) + "%"}</span>
    </div>
    <div class="progress-bar"><div class="progress-bar__fill progress-bar__fill--${variant}" style="width:${clamped}%;"></div></div>`;
}

function renderStatTrend(pct) {
  if (pct === null || pct === undefined) return "";
  const up = pct >= 0;
  return `<span class="stat-trend stat-trend--${up ? "up" : "down"}"><span class="stat-trend__arrow">${up ? "▲" : "▼"}</span>${Math.abs(pct).toFixed(2)}%</span>`;
}

function initTabs(container) {
  const tabBtns = container.querySelectorAll(".tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".tabs-wrapper");
      group.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      group.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      group.querySelector(`.tab-panel[data-tab="${btn.dataset.tab}"]`).classList.add("active");
    });
  });
}

function renderSparkline(closes) {
  if (!closes || closes.length < 2) return `<span class="sparkline-empty">—</span>`;
  const w = 88, h = 30, pad = 2;
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = (max - min) || 1;
  const points = closes.map((c, i) => {
    const x = pad + (i / (closes.length - 1)) * (w - pad * 2);
    const y = h - pad - ((c - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const trendUp = closes[closes.length - 1] >= closes[0];
  const colorVar = trendUp ? "var(--bullish)" : "var(--bearish)";
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" style="stroke:${colorVar};stroke-width:1.6;stroke-linejoin:round;stroke-linecap:round;" />
  </svg>`;
}

async function fetchSparklineCloses(ticker) {
  try {
    const res = await apiGet(`/stock/${ticker}/historical?period=1mo`);
    return (res.bars || []).map((b) => b.close).filter((c) => c !== null && c !== undefined);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------- toasts
function showToast(message, type = "info") {
  let container = document.getElementById("toastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "toastContainer";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast--visible"));
  setTimeout(() => {
    toast.classList.remove("toast--visible");
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

function fmtPrice(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${Number(v).toFixed(2)}`;
}

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(2)}%`;
}

function pctClass(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "pct-flat";
  return v > 0 ? "pct-up" : v < 0 ? "pct-down" : "pct-flat";
}

function fmtVolume(v) {
  if (v === null || v === undefined) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

function qualityBadgeClass(quality) {
  if (quality === "GOOD") return "data-quality-badge--good";
  if (quality === "WARNING") return "data-quality-badge--warning";
  return "data-quality-badge--error";
}

const BENCHMARK_LABELS = { SPY: "S&P 500 (SPY)", QQQ: "Nasdaq 100 (QQQ)", DIA: "Dow (DIA)", IWM: "Russell 2000 (IWM)", "^VIX": "VIX" };

// ----------------------------------------------------------- navigation
function initSiteMenu() {
  const menu = document.getElementById("siteMenu");
  const trigger = document.getElementById("menuTrigger");
  const closeBtn = document.getElementById("siteMenuClose");

  const openMenu = () => menu.classList.add("open");
  const closeMenu = () => menu.classList.remove("open");

  trigger.addEventListener("click", openMenu);
  closeBtn.addEventListener("click", closeMenu);
  menu.addEventListener("click", (e) => {
    if (e.target === menu) closeMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && menu.classList.contains("open")) closeMenu();
  });

  document.querySelectorAll(".site-menu__link").forEach((link) => {
    link.addEventListener("click", () => {
      switchView(link.dataset.view);
      closeMenu();
    });
  });
}

function initNav() {
  // .site-menu__link clicks are handled inside initSiteMenu() (they
  // also need to close the overlay afterward) — this just wires the
  // remaining plain [data-nav] shortcuts elsewhere in the app (e.g.
  // the Watchlist card's "Manage →" button).
  document.querySelectorAll("[data-nav]").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.nav));
  });
}

// ------------------------------------------------- global ticker search
let globalSearchDebounce = null;
let globalSearchHighlightIndex = -1;

function initGlobalSearch() {
  const input = document.getElementById("globalSearchInput");
  const resultsBox = document.getElementById("globalSearchResults");

  input.addEventListener("input", () => {
    const query = input.value.trim();
    clearTimeout(globalSearchDebounce);
    if (!query) {
      hideGlobalSearchResults();
      return;
    }
    globalSearchDebounce = setTimeout(() => runGlobalSearch(query), 220);
  });

  input.addEventListener("keydown", (e) => {
    const items = resultsBox.querySelectorAll(".global-search-result");
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      globalSearchHighlightIndex = Math.min(globalSearchHighlightIndex + 1, items.length - 1);
      updateGlobalSearchHighlight(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      globalSearchHighlightIndex = Math.max(globalSearchHighlightIndex - 1, 0);
      updateGlobalSearchHighlight(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = items[globalSearchHighlightIndex] || items[0];
      if (target) jumpToTicker(target.dataset.ticker);
    } else if (e.key === "Escape") {
      hideGlobalSearchResults();
      input.blur();
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".global-search-wrapper")) hideGlobalSearchResults();
  });

  document.getElementById("globalAlertsBtn").addEventListener("click", () => switchView("alerts"));
}

function updateGlobalSearchHighlight(items) {
  items.forEach((item, i) => item.classList.toggle("highlighted", i === globalSearchHighlightIndex));
}

async function runGlobalSearch(query) {
  const resultsBox = document.getElementById("globalSearchResults");
  try {
    const res = await apiGet(`/search?q=${encodeURIComponent(query)}`);
    globalSearchHighlightIndex = -1;
    const matches = res.results || res || [];
    if (!matches.length) {
      resultsBox.innerHTML = `<div class="global-search-empty">No matches for "${query}"</div>`;
    } else {
      resultsBox.innerHTML = matches.slice(0, 8).map((m) => `
        <div class="global-search-result" data-ticker="${m.ticker}">
          <span class="global-search-result__ticker">${m.ticker}</span>
          <span class="global-search-result__name">${m.name || ""}</span>
        </div>`).join("");
      resultsBox.querySelectorAll(".global-search-result").forEach((row) => {
        row.addEventListener("click", () => jumpToTicker(row.dataset.ticker));
      });
    }
    resultsBox.classList.add("visible");
  } catch {
    resultsBox.innerHTML = `<div class="global-search-empty">Search failed — try again.</div>`;
    resultsBox.classList.add("visible");
  }
}

function hideGlobalSearchResults() {
  document.getElementById("globalSearchResults").classList.remove("visible");
  globalSearchHighlightIndex = -1;
}

function jumpToTicker(ticker) {
  if (!ticker) return;
  document.getElementById("globalSearchInput").value = "";
  hideGlobalSearchResults();
  switchView("analyzer");
  document.getElementById("analyzerTickerInput").value = ticker;
  analyzeTicker(ticker);
}

// ------------------------------------------------------------ command palette
const CMDK_DESTINATIONS = [
  { view: "dashboard", label: "Dashboard", icon: "▣", group: "Research" },
  { view: "watchlist", label: "Watchlist", icon: "☆", group: "Research" },
  { view: "analyzer", label: "Stock Analyzer", icon: "◎", group: "Research" },
  { view: "scanner", label: "Scanner", icon: "⌕", group: "Research" },
  { view: "market", label: "Market", icon: "◐", group: "Research" },
  { view: "news", label: "News", icon: "▥", group: "Research" },
  { view: "portfolio", label: "Portfolio", icon: "◫", group: "Portfolio" },
  { view: "alerts", label: "Alerts", icon: "◭", group: "Portfolio" },
  { view: "predictions", label: "Predictions", icon: "◇", group: "AI & Models" },
  { view: "backtesting", label: "Backtesting", icon: "▤", group: "AI & Models" },
  { view: "models", label: "Models", icon: "⬡", group: "AI & Models" },
  { view: "chat", label: "AI Assistant", icon: "◔", group: "AI & Models" },
  { view: "settings", label: "Settings", icon: "⚙", group: "System" },
];

let cmdkHighlightIndex = -1;
let cmdkTickerDebounce = null;

function initCommandPalette() {
  const trigger = document.getElementById("cmdkTrigger");
  const overlay = document.getElementById("cmdkOverlay");
  const input = document.getElementById("cmdkInput");

  trigger.addEventListener("click", openCommandPalette);

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      overlay.classList.contains("visible") ? closeCommandPalette() : openCommandPalette();
    } else if (e.key === "Escape" && overlay.classList.contains("visible")) {
      closeCommandPalette();
    }
  });

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeCommandPalette();
  });

  input.addEventListener("input", () => {
    const query = input.value.trim();
    clearTimeout(cmdkTickerDebounce);
    renderCommandPaletteResults(query, null);
    if (query.length >= 1) {
      cmdkTickerDebounce = setTimeout(async () => {
        try {
          const res = await apiGet(`/search?q=${encodeURIComponent(query)}`);
          renderCommandPaletteResults(query, res.results || []);
        } catch {
          renderCommandPaletteResults(query, []);
        }
      }, 200);
    }
  });

  input.addEventListener("keydown", (e) => {
    const items = document.querySelectorAll(".cmdk-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      cmdkHighlightIndex = Math.min(cmdkHighlightIndex + 1, items.length - 1);
      updateCmdkHighlight(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      cmdkHighlightIndex = Math.max(cmdkHighlightIndex - 1, 0);
      updateCmdkHighlight(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = items[cmdkHighlightIndex] || items[0];
      if (target) target.click();
    }
  });
}

function updateCmdkHighlight(items) {
  items.forEach((item, i) => item.classList.toggle("highlighted", i === cmdkHighlightIndex));
  if (items[cmdkHighlightIndex]) items[cmdkHighlightIndex].scrollIntoView({ block: "nearest" });
}

function openCommandPalette() {
  const overlay = document.getElementById("cmdkOverlay");
  const input = document.getElementById("cmdkInput");
  overlay.classList.add("visible");
  input.value = "";
  input.focus();
  renderCommandPaletteResults("", null);
}

function closeCommandPalette() {
  document.getElementById("cmdkOverlay").classList.remove("visible");
}

function renderCommandPaletteResults(query, tickerMatches) {
  const container = document.getElementById("cmdkResults");
  cmdkHighlightIndex = -1;
  const lower = query.toLowerCase();

  const matchedDestinations = query
    ? CMDK_DESTINATIONS.filter((d) => d.label.toLowerCase().includes(lower))
    : CMDK_DESTINATIONS;

  const groups = {};
  matchedDestinations.forEach((d) => {
    groups[d.group] = groups[d.group] || [];
    groups[d.group].push(d);
  });

  let html = "";
  Object.entries(groups).forEach(([group, items]) => {
    html += `<div class="cmdk-group-label">${group}</div>`;
    items.forEach((d) => {
      html += `<div class="cmdk-item" data-action="nav" data-view="${d.view}">
        <span class="cmdk-item__icon">${d.icon}</span> ${d.label}
      </div>`;
    });
  });

  if (tickerMatches && tickerMatches.length) {
    html += `<div class="cmdk-group-label">Tickers</div>`;
    tickerMatches.slice(0, 6).forEach((m) => {
      html += `<div class="cmdk-item" data-action="ticker" data-ticker="${m.ticker}">
        <span class="cmdk-item__icon">$</span> ${m.ticker}
        <span class="cmdk-item__meta">${m.name || ""}</span>
      </div>`;
    });
  }

  if (!html) {
    html = `<div class="cmdk-empty">No matches for "${query}"</div>`;
  }

  container.innerHTML = html;
  container.querySelectorAll(".cmdk-item").forEach((item) => {
    item.addEventListener("click", () => {
      if (item.dataset.action === "nav") {
        switchView(item.dataset.view);
      } else if (item.dataset.action === "ticker") {
        jumpToTicker(item.dataset.ticker);
      }
      closeCommandPalette();
    });
  });
}

function switchView(viewId) {
  document.querySelectorAll(".site-menu__link").forEach((b) => b.classList.remove("active"));
  const navBtn = document.querySelector(`.site-menu__link[data-view="${viewId}"]`);
  if (navBtn) navBtn.classList.add("active");

  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const target = document.getElementById(`view-${viewId}`) || document.getElementById("view-placeholder-template");
  target.classList.add("active");

  if (viewId === "dashboard") loadDashboard();
  if (viewId === "watchlist") loadWatchlistView();
  if (viewId === "market") loadMarketView();
  if (viewId === "news") loadNewsView();
  if (viewId === "models") loadModelsPage();
  if (viewId === "portfolio") loadPortfolioView();
  if (viewId === "alerts") loadAlertsView();
  if (viewId === "settings") loadSettingsView();
  if (viewId === "chat") loadChatView();
}

// ----------------------------------------------------------- ticker tape
async function loadTickerTape() {
  const track = document.getElementById("tickerTapeTrack");
  try {
    const dash = await apiGet("/dashboard");
    const items = [...dash.benchmarks, ...dash.watchlist];
    if (items.length === 0) {
      track.innerHTML = `<span class="ticker-tape__item ticker-tape__item--placeholder">Add tickers to your watchlist to see them here.</span>`;
      return;
    }
    const renderItem = (item) => {
      const label = BENCHMARK_LABELS[item.ticker] || item.ticker;
      if (!item.quote) return `<span class="ticker-tape__item" data-ticker="${item.ticker}"><b>${label}</b>no data</span>`;
      const cls = item.change_pct > 0 ? "ticker-tape__item--up" : item.change_pct < 0 ? "ticker-tape__item--down" : "";
      return `<span class="ticker-tape__item ${cls}" data-ticker="${item.ticker}"><b>${label}</b>${fmtPrice(item.quote.price)} ${fmtPct(item.change_pct)}</span>`;
    };
    // duplicate the list so the scroll loop feels continuous
    const html = items.map(renderItem).join("");
    track.innerHTML = html + html;
    attachAnalyzeHandlers(track);
  } catch (e) {
    track.innerHTML = `<span class="ticker-tape__item ticker-tape__item--placeholder">Market data unavailable right now.</span>`;
  }
}

// ----------------------------------------------------------- dashboard
async function loadDashboard() {
  const benchmarkGrid = document.getElementById("benchmarkGrid");
  benchmarkGrid.innerHTML = `<div class="skeleton-card">Loading benchmarks…</div>`;
  const wlWrap = document.getElementById("dashboardWatchlist");

  try {
    const dash = await apiGet("/dashboard");

    benchmarkGrid.innerHTML = dash.benchmarks.map((b) => {
      const label = BENCHMARK_LABELS[b.ticker] || b.ticker;
      if (!b.quote) {
        return `<div class="skeleton-card">${label}<br/><span class="empty-state">No data (${b.meta.error || "provider failed"})</span></div>`;
      }
      return `
        <div class="panel panel--clickable" style="margin-bottom:0;" data-ticker="${b.ticker}">
          <div class="stock-header__meta-label">${label}</div>
          <div class="stock-header__price" style="margin:4px 0;">${fmtPrice(b.quote.price)}</div>
          ${renderStatTrend(b.change_pct)}
        </div>`;
    }).join("");
    attachAnalyzeHandlers(benchmarkGrid);

    if (dash.watchlist.length === 0) {
      wlWrap.innerHTML = `<p class="empty-state">Your watchlist is empty. Add tickers from the Watchlist tab to see them here.</p>`;
    } else {
      wlWrap.innerHTML = renderQuoteTable(dash.watchlist);
      attachAnalyzeHandlers(wlWrap);
    }
  } catch (e) {
    benchmarkGrid.innerHTML = `<div class="skeleton-card">Couldn't load market data: ${e.message}</div>`;
  }

  loadSuggestions();
  loadDiscovery();
  loadTickerTape();
}

function initDashboard() {
  document.getElementById("dashboardQuickAddForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("dashboardQuickAddInput");
    const raw = input.value.trim();
    if (!raw) return;
    if (!/^[A-Za-z^.]{1,6}$/.test(raw)) {
      showToast("Enter a plain ticker symbol, e.g. AAPL.", "error");
      return;
    }
    try {
      await apiPost(`/watchlist/${raw.toUpperCase()}`);
      input.value = "";
      showToast(`Added ${raw.toUpperCase()} to your watchlist.`, "success");
      loadDashboard();
    } catch (err) {
      showToast(`Couldn't add ${raw.toUpperCase()}: ${err.message}`, "error");
    }
  });

  document.getElementById("refreshSuggestionsBtn").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.textContent = "Refreshing…";
    try {
      const res = await apiPost("/suggestions/refresh");
      showToast(`Refreshed ${res.refreshed.length} ticker(s)${res.failed.length ? `, ${res.failed.length} failed` : ""}.`, res.failed.length ? "error" : "success");
    } catch (err) {
      showToast(`Refresh failed: ${err.message}`, "error");
    }
    btn.textContent = "Refresh";
    loadSuggestions();
  });

  document.getElementById("triggerDiscoverySweepBtn").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.textContent = "Sweeping…";
    try {
      const res = await apiPost("/discovery/sweep");
      showToast(`Scanned ${res.refreshed.length} new ticker(s)${res.failed.length ? `, ${res.failed.length} failed` : ""}.`, res.failed.length ? "error" : "success");
    } catch (err) {
      showToast(`Sweep failed: ${err.message}`, "error");
    }
    btn.textContent = "Sweep now";
    loadDiscovery();
  });
}

let currentDiscoveryMode = "ranked";

async function loadDiscovery() {
  const coverageBar = document.getElementById("discoveryCoverageBar");
  const wrap = document.getElementById("discoveryResults");
  try {
    const coverage = await apiGet("/discovery/coverage");
    coverageBar.innerHTML = coverage.total > 0 ? `
      <div class="progress-label-row">
        <span class="progress-label-row__title">Universe coverage</span>
        <span class="progress-label-row__value">${coverage.covered} / ${coverage.total} tickers</span>
      </div>
      <div class="progress-bar"><div class="progress-bar__fill progress-bar__fill--accent" style="width:${coverage.pct}%;"></div></div>` : "";

    if (currentDiscoveryMode === "diversified") {
      await renderDiversifiedDiscovery(wrap, coverage);
    } else {
      await renderRankedDiscovery(wrap, coverage);
    }
  } catch (e) {
    wrap.innerHTML = `<p class="empty-state">Couldn't load discovery: ${e.message}</p>`;
  }
}

async function renderRankedDiscovery(wrap, coverage) {
  const res = await apiGet("/discovery?limit=5");
  let html = "";
  if (res.bullish.length > 0) {
    html += `<div class="sidebar__group-label" style="padding-left:0;">Bullish ideas</div>`;
    html += res.bullish.map((s) => renderSuggestionCard(s, false)).join("");
  }
  if (res.risk_flags.length > 0) {
    html += `<div class="sidebar__group-label" style="padding-left:0; margin-top:14px;">Risk flags</div>`;
    html += res.risk_flags.map((s) => renderSuggestionCard(s, true)).join("");
  }
  if (res.bullish.length === 0 && res.risk_flags.length === 0) {
    html += coverage.covered === 0
      ? `<p class="empty-state">No coverage yet — click "Sweep now" to scan a few tickers right away, or wait for the background job (runs automatically every few hours).</p>`
      : `<p class="empty-state">Nothing strongly bullish or risky in the covered portion of the universe yet.</p>`;
  }
  wrap.innerHTML = html;
  wireSuggestionCardClicks(wrap);
}

async function renderDiversifiedDiscovery(wrap, coverage) {
  const res = await apiGet("/discovery/diversified?limit=5");
  if (res.picks.length === 0) {
    wrap.innerHTML = coverage.covered === 0
      ? `<p class="empty-state">No coverage yet — click "Sweep now" first.</p>`
      : `<p class="empty-state">Not enough bullish candidates yet to build a diversified set.</p>`;
    return;
  }
  if (!res.correlation_data_available) {
    wrap.innerHTML = `<p class="empty-state" style="margin-bottom:10px;">Couldn't fetch enough price history to compute real correlations — showing plain top-ranked picks instead.</p>`;
  } else {
    wrap.innerHTML = "";
  }
  const html = res.picks.map((s) => {
    const card = renderSuggestionCard(s, false);
    if (s.avg_correlation_with_selected === null) {
      return card.replace('<div class="suggestion-card__meta">', '<div class="suggestion-card__meta">Anchor pick · ');
    }
    return card.replace('<div class="suggestion-card__meta">', `<div class="suggestion-card__meta">Avg. correlation with picks above: ${s.avg_correlation_with_selected.toFixed(2)} · `);
  }).join("");
  wrap.innerHTML += html;
  wireSuggestionCardClicks(wrap);
}

function initDiscoveryModeTabs() {
  document.getElementById("discoveryModeTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    document.querySelectorAll("#discoveryModeTabs .tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentDiscoveryMode = btn.dataset.mode;
    document.getElementById("discoveryDiversifiedHint").style.display = currentDiscoveryMode === "diversified" ? "block" : "none";
    loadDiscovery();
  });
}

function renderSuggestionCard(s, isRisk) {
  return `
    <div class="suggestion-card" data-ticker="${s.ticker}">
      <div class="suggestion-card__left">
        <span class="signal-badge ${SIGNAL_DISPLAY[s.signal]?.cls || "signal-badge--neutral"}" style="font-size:10px; padding:3px 8px;">${SIGNAL_DISPLAY[s.signal]?.label || s.signal}</span>
        <div>
          <div class="suggestion-card__ticker">${s.ticker}</div>
          <div class="suggestion-card__meta">${s.horizon_days}D horizon · updated ${s.age_hours < 1 ? "just now" : s.age_hours.toFixed(0) + "h ago"}</div>
        </div>
      </div>
      <div class="suggestion-card__right">
        <div class="suggestion-card__return ${isRisk ? "pct-down" : "pct-up"}">${s.expected_return_pct > 0 ? "+" : ""}${s.expected_return_pct}%</div>
        <div class="suggestion-card__confidence">${(s.confidence * 100).toFixed(0)}% confidence</div>
      </div>
    </div>`;
}

function wireSuggestionCardClicks(wrap) {
  wrap.querySelectorAll(".suggestion-card").forEach((card) => {
    card.addEventListener("click", () => {
      switchView("predictions");
      document.getElementById("predictTickerInput").value = card.dataset.ticker;
    });
  });
}

async function loadSuggestions() {
  const wrap = document.getElementById("suggestionsResults");
  try {
    const res = await apiGet("/suggestions?limit=5");

    if (res.note) {
      wrap.innerHTML = `<p class="empty-state">${res.note}</p>`;
      return;
    }

    let html = "";
    if (res.bullish.length > 0) {
      html += `<div class="sidebar__group-label" style="padding-left:0;">Bullish ideas</div>`;
      html += res.bullish.map((s) => renderSuggestionCard(s, false)).join("");
    }
    if (res.risk_flags.length > 0) {
      html += `<div class="sidebar__group-label" style="padding-left:0; margin-top:14px;">Risk flags</div>`;
      html += res.risk_flags.map((s) => renderSuggestionCard(s, true)).join("");
    }
    if (res.bullish.length === 0 && res.risk_flags.length === 0) {
      html += `<p class="empty-state">No strong signals right now — everything's reading neutral.</p>`;
    }
    if (res.stale_or_missing.length > 0) {
      html += `<p class="field-hint" style="margin-top:14px;">${res.stale_or_missing.length} ticker(s) need a fresh prediction: ${res.stale_or_missing.join(", ")}. Click Refresh above.</p>`;
    }

    wrap.innerHTML = html;
    wireSuggestionCardClicks(wrap);
  } catch (e) {
    wrap.innerHTML = `<p class="empty-state">Couldn't load suggestions: ${e.message}</p>`;
  }
}

function renderQuoteTable(items) {
  const rows = items.map((item) => {
    if (!item.quote) {
      return `<tr><td class="ticker-cell">${item.ticker}</td><td colspan="4" class="empty-state">No data — ${item.meta.error || "provider unavailable"}</td></tr>`;
    }
    const q = item.quote;
    return `
      <tr>
        <td class="ticker-cell" data-ticker="${item.ticker}" style="cursor:pointer;">${item.ticker}</td>
        <td>${fmtPrice(q.price)}</td>
        <td>${renderStatTrend(item.change_pct)}</td>
        <td>${fmtVolume(q.volume)}</td>
        <td><span class="data-quality-badge ${qualityBadgeClass(item.meta.quality)}">${item.meta.timeliness.replace('_',' ')}</span></td>
      </tr>`;
  }).join("");

  return `
    <table class="data-table">
      <thead><tr><th>Ticker</th><th>Price</th><th>Change</th><th>Volume</th><th>Data</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function attachAnalyzeHandlers(scope) {
  scope.querySelectorAll("[data-ticker]").forEach((cell) => {
    cell.addEventListener("click", () => {
      switchView("analyzer");
      document.getElementById("analyzerTickerInput").value = cell.dataset.ticker;
      analyzeTicker(cell.dataset.ticker);
    });
  });
}

// ----------------------------------------------------------- watchlist view
async function loadWatchlistView() {
  const wrap = document.getElementById("watchlistTableWrap");
  wrap.innerHTML = `<p class="empty-state">Loading…</p>`;
  try {
    const { watchlist } = await apiGet("/watchlist");
    if (watchlist.length === 0) {
      wrap.innerHTML = `<p class="empty-state">No tickers yet. Add one above.</p>`;
      return;
    }
    const quotes = await Promise.all(watchlist.map(async (w) => {
      try {
        const [q, sparkCloses] = await Promise.all([
          apiGet(`/stock/${w.ticker}/quote`),
          fetchSparklineCloses(w.ticker),
        ]);
        const changePct = q.quote && q.quote.previous_close
          ? (q.quote.price - q.quote.previous_close) / q.quote.previous_close * 100
          : null;
        return { ticker: w.ticker, quote: q.quote, change_pct: changePct, meta: q.meta, sparkCloses };
      } catch {
        return { ticker: w.ticker, quote: null, meta: { error: "fetch failed", quality: "ERROR", timeliness: "n/a" }, sparkCloses: null };
      }
    }));

    const rows = quotes.map((item) => {
      const priceCells = item.quote
        ? `<td>${fmtPrice(item.quote.price)}</td><td>${renderStatTrend(item.change_pct)}</td><td>${renderSparkline(item.sparkCloses)}</td>`
        : `<td colspan="3" class="empty-state">No data — ${item.meta.error || "provider unavailable"}</td>`;
      return `
        <tr>
          <td class="ticker-cell" data-ticker="${item.ticker}" style="cursor:pointer;">${item.ticker}</td>
          ${priceCells}
          <td class="row-actions">
            <button class="row-action-btn" data-predict="${item.ticker}" title="Predict">◇</button>
            <button class="row-action-btn" data-portfolio-add="${item.ticker}" title="Add to portfolio">◫</button>
            <button class="remove-btn" data-remove="${item.ticker}">Remove</button>
          </td>
        </tr>`;
    }).join("");

    wrap.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Ticker</th><th>Price</th><th>Change</th><th>Last 30 Days</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;

    attachAnalyzeHandlers(wrap);
    wrap.querySelectorAll("[data-remove]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await apiDelete(`/watchlist/${btn.dataset.remove}`);
        loadWatchlistView();
      });
    });
    wrap.querySelectorAll("[data-predict]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        switchView("predictions");
        document.getElementById("predictTickerInput").value = btn.dataset.predict;
      });
    });
    wrap.querySelectorAll("[data-portfolio-add]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        switchView("portfolio");
        document.getElementById("portfolioTickerInput").value = btn.dataset.portfolioAdd;
        document.getElementById("portfolioTickerInput").dispatchEvent(new Event("blur"));
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="empty-state">Couldn't load watchlist: ${e.message}</p>`;
  }
}

function initWatchlistForm() {
  const form = document.getElementById("watchlistAddForm");
  const input = document.getElementById("watchlistTickerInput");
  const results = document.getElementById("watchlistSearchResults");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = input.value.trim();
    if (!raw) return;

    // If it looks like a plain ticker, add it directly; otherwise search.
    if (/^[A-Za-z^.]{1,6}$/.test(raw)) {
      try {
        await apiPost(`/watchlist/${raw.toUpperCase()}`);
        input.value = "";
        results.innerHTML = "";
        showToast(`Added ${raw.toUpperCase()} to your watchlist.`, "success");
        loadWatchlistView();
      } catch (err) {
        showToast(`Couldn't add ${raw.toUpperCase()}: ${err.message}`, "error");
      }
      return;
    }

    try {
      const { results: matches } = await apiGet(`/search?q=${encodeURIComponent(raw)}`);
      if (matches.length === 0) {
        results.innerHTML = `<p class="empty-state">No matches for "${raw}".</p>`;
        return;
      }
      results.innerHTML = matches.slice(0, 8).map((m) => `
        <div class="search-result-item">
          <span><strong>${m.ticker}</strong> — ${m.name || "—"} <span class="empty-state">(${m.exchange || ""})</span></span>
          <button class="btn" data-add="${m.ticker}">Add</button>
        </div>`).join("");
      results.querySelectorAll("[data-add]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            await apiPost(`/watchlist/${btn.dataset.add}`);
            results.innerHTML = "";
            input.value = "";
            showToast(`Added ${btn.dataset.add} to your watchlist.`, "success");
            loadWatchlistView();
          } catch (err) {
            showToast(`Couldn't add ${btn.dataset.add}: ${err.message}`, "error");
          }
        });
      });
    } catch (e) {
      results.innerHTML = `<p class="empty-state">Search failed: ${e.message}</p>`;
    }
  });
}

// ----------------------------------------------------------- stock analyzer
function initAnalyzer() {
  const form = document.getElementById("analyzerSearchForm");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const ticker = document.getElementById("analyzerTickerInput").value.trim().toUpperCase();
    if (ticker) analyzeTicker(ticker);
  });

  document.getElementById("periodToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-period]");
    if (!btn) return;
    document.querySelectorAll("#periodToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentAnalyzerPeriod = btn.dataset.period;
    if (currentAnalyzerTicker) analyzeTicker(currentAnalyzerTicker);
  });
}

// Market-data source comparison panel — shows exactly why the winning
// provider was chosen (freshness/completeness/coverage scores), so the
// selection is never a black box the way a fixed "always try yfinance
// first" order would be.
function renderProviderComparison(comparison) {
  const panel = document.getElementById("providerComparisonPanel");
  if (!panel) return;
  if (!comparison || comparison.length === 0) {
    panel.innerHTML = "";
    return;
  }
  const rows = comparison.map((c, i) => `
    <tr>
      <td class="ticker-cell">${c.source}${i === 0 ? " 🏆" : ""}</td>
      <td>${c.score}</td>
      <td class="match-reasons">${c.reasons.join("; ")}</td>
    </tr>`).join("");

  panel.innerHTML = `
    <details class="advanced-filters" style="margin-top:14px;">
      <summary>Data source comparison (${comparison[0].source} won)</summary>
      <table class="data-table" style="margin-top:10px;">
        <thead><tr><th>Source</th><th>Score</th><th>Why</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </details>`;
}

async function analyzeTicker(ticker) {
  currentAnalyzerTicker = ticker;
  document.getElementById("analyzerEmptyState").style.display = "none";
  const results = document.getElementById("analyzerResults");
  results.style.display = "block";
  document.getElementById("stockHeader").innerHTML = `<p class="empty-state">Loading ${ticker}…</p>`;
  document.getElementById("candlestickChart").innerHTML = "";
  document.getElementById("interpretationText").textContent = "";
  document.getElementById("indicatorGrid").innerHTML = "";
  document.getElementById("structureTags").innerHTML = "";

  try {
    const [quoteRes, indicatorRes] = await Promise.all([
      apiGet(`/stock/${ticker}/quote`),
      apiGet(`/stock/${ticker}/indicators?period=${currentAnalyzerPeriod}`),
    ]);

    renderStockHeader(ticker, quoteRes, indicatorRes);
    renderCandlestick(ticker, indicatorRes.bars);
    renderInterpretation(indicatorRes);
    renderIndicatorGrid(indicatorRes.latest);

    const badge = document.getElementById("dataQualityBadge");
    badge.textContent = `${indicatorRes.meta.source} · ${indicatorRes.meta.timeliness.replace("_", " ")}`;
    badge.className = `data-quality-badge ${qualityBadgeClass(indicatorRes.meta.quality)}`;

    renderProviderComparison(indicatorRes.provider_comparison);
  } catch (e) {
    document.getElementById("stockHeader").innerHTML = `<p class="empty-state">Couldn't load ${ticker}: ${e.message}</p>`;
  }

  loadFundamentalsPanel(ticker);
  loadSecPanel(ticker);
  loadNewsPanel(ticker);
  loadTradingViewChart(ticker);
}

// ----------------------------------------------------------- TradingView live chart
let _tradingViewScriptLoading = null;

function _loadTradingViewScript() {
  if (window.TradingView) return Promise.resolve();
  if (_tradingViewScriptLoading) return _tradingViewScriptLoading;
  _tradingViewScriptLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/tv.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("Could not load TradingView's widget script — check for ad-blockers."));
    document.head.appendChild(script);
  });
  return _tradingViewScriptLoading;
}

async function loadTradingViewChart(ticker) {
  const container = document.getElementById("tradingViewChart");
  container.innerHTML = `<p class="empty-state">Loading live chart…</p>`;

  try {
    await _loadTradingViewScript();
  } catch (e) {
    container.innerHTML = `<p class="empty-state">${e.message}</p>`;
    return;
  }

  // Unique container id per render so re-analyzing a ticker (or
  // switching tickers) doesn't collide with a previous widget instance.
  const containerId = `tv_widget_${ticker}_${Date.now()}`;
  container.innerHTML = `<div id="${containerId}" class="tradingview-widget-container__widget"></div>`;

  try {
    new window.TradingView.widget({
      autosize: true,
      symbol: ticker, // TradingView resolves bare US tickers to their primary listing automatically
      interval: "D",
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      toolbar_bg: "#12161D",
      enable_publishing: false,
      allow_symbol_change: true,
      hide_side_toolbar: false,
      container_id: containerId,
    });
  } catch (e) {
    container.innerHTML = `<p class="empty-state">Couldn't initialize the live chart widget.</p>`;
  }
}

// ----------------------------------------------------------- SEC filings/financials
async function loadSecPanel(ticker) {
  const financialsEl = document.getElementById("secFinancialsContent");
  const filingsEl = document.getElementById("secFilingsContent");
  const badge = document.getElementById("secQualityBadge");
  financialsEl.innerHTML = `<p class="empty-state">Loading SEC financial data…</p>`;
  filingsEl.innerHTML = `<p class="empty-state">Loading recent filings…</p>`;
  badge.textContent = "";
  badge.className = "data-quality-badge";

  try {
    const res = await apiGet(`/stock/${ticker}/sec/financials`);
    if (!res.trend || !res.trend.latest_period) {
      financialsEl.innerHTML = `<p class="empty-state">${res.warning || (res.trend && res.trend.note) || "SEC financial data unavailable for this ticker."}</p>`;
    } else {
      badge.textContent = `SEC EDGAR · as of ${res.trend.latest_period}`;
      badge.className = "data-quality-badge data-quality-badge--good";
      const narrative = res.trend.narrative.map((line) => `<li>${line}</li>`).join("");
      financialsEl.innerHTML = `
        <ul class="sec-narrative-list">${narrative || "<li>No notable period-over-period changes detected.</li>"}</ul>
        <p class="field-hint">Generated directly from SEC XBRL data (the figures companies tag in their own filings) — not an estimate.</p>`;
    }
  } catch (e) {
    financialsEl.innerHTML = `<p class="empty-state">Couldn't load SEC financial trend: ${e.message}</p>`;
  }

  try {
    const res = await apiGet(`/stock/${ticker}/sec/filings`);
    if (!res.filings || res.filings.length === 0) {
      filingsEl.innerHTML = `<p class="empty-state">${res.warning || "No recent SEC filings found for this ticker."}</p>`;
      return;
    }
    const rows = res.filings.slice(0, 12).map((f) => `
      <tr>
        <td><span class="tag">${f.form}</span></td>
        <td>${f.filed_at}</td>
        <td>${f.report_date || "—"}</td>
        <td><a href="${f.document_url}" target="_blank" rel="noopener" class="btn btn--ghost" style="padding:2px 0;">View filing →</a></td>
      </tr>`).join("");
    filingsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Form</th><th>Filed</th><th>Period</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (e) {
    filingsEl.innerHTML = `<p class="empty-state">Couldn't load SEC filings: ${e.message}</p>`;
  }
}

// ----------------------------------------------------------- fundamentals
async function loadFundamentalsPanel(ticker) {
  const content = document.getElementById("fundamentalsContent");
  const badge = document.getElementById("fundamentalsQualityBadge");
  content.innerHTML = `<p class="empty-state">Loading fundamentals…</p>`;
  badge.textContent = "";
  badge.className = "data-quality-badge";

  try {
    const res = await apiGet(`/stock/${ticker}/fundamentals`);
    badge.textContent = `${res.meta.source} · ${res.meta.timeliness.replace("_", " ")}`;
    badge.className = `data-quality-badge ${qualityBadgeClass(res.meta.quality)}`;

    if (!res.fundamentals || res.score.score === null) {
      content.innerHTML = `<p class="empty-state">${res.warning || res.score?.explanation || "Fundamentals unavailable for this ticker."}</p>`;
      return;
    }

    const f = res.fundamentals;
    const s = res.score;
    const tier = s.score >= 70 ? "strong" : s.score >= 40 ? "middling" : "weak";

    const metrics = [
      ["Revenue Growth", f.revenue_growth != null ? fmtPct(f.revenue_growth * 100) : null],
      ["Earnings Growth", f.earnings_growth != null ? fmtPct(f.earnings_growth * 100) : null],
      ["Net Margin", f.net_margin != null ? fmtPct(f.net_margin * 100) : null],
      ["Return on Equity", f.return_on_equity != null ? fmtPct(f.return_on_equity * 100) : null],
      ["Trailing P/E", f.trailing_pe != null ? f.trailing_pe.toFixed(1) : null],
      ["Forward P/E", f.forward_pe != null ? f.forward_pe.toFixed(1) : null],
      ["Price/Sales", f.price_to_sales != null ? f.price_to_sales.toFixed(1) : null],
      ["Price/Book", f.price_to_book != null ? f.price_to_book.toFixed(1) : null],
      ["Debt/Equity", f.debt_to_equity != null ? f.debt_to_equity.toFixed(1) : null],
      ["Dividend Yield", f.dividend_yield != null ? fmtPct(f.dividend_yield * 100) : null],
      ["Beta", f.beta != null ? f.beta.toFixed(2) : null],
      ["Sector", f.sector || null],
    ];

    content.innerHTML = `
      <div class="fundamentals-layout">
        <div class="score-dial score-dial--${tier}">
          <div class="score-dial__value">${s.score}</div>
          <div class="score-dial__label">/ 100 · ${s.coverage}</div>
        </div>
        <div class="fundamentals-detail">
          <p class="fundamentals-explanation">${s.explanation}</p>
          <div class="fundamentals-metric-grid">
            ${metrics.filter(([, v]) => v !== null).map(([label, value]) => `
              <div class="indicator-cell">
                <div class="indicator-cell__label">${label}</div>
                <div class="indicator-cell__value">${value}</div>
              </div>`).join("")}
          </div>
        </div>
      </div>`;
  } catch (e) {
    content.innerHTML = `<p class="empty-state">Couldn't load fundamentals: ${e.message}</p>`;
  }
}

// ----------------------------------------------------------- news rendering
function renderNewsList(items) {
  if (!items || items.length === 0) {
    return `<p class="empty-state">No news available right now.</p>`;
  }
  return `<div class="news-list">${items.map((item) => {
    const sentimentClass = item.sentiment.label.includes("positive") ? "signal-badge--bullish"
      : item.sentiment.label.includes("negative") ? "signal-badge--bearish" : "signal-badge--neutral";
    const dateStr = item.published_at ? new Date(item.published_at).toLocaleString() : "";
    const tierLabel = item.source_tier === 1 ? "Primary source" : item.source_tier === 2 ? "Major wire/press" : null;
    const alsoReported = item.also_reported_by && item.also_reported_by.length > 0
      ? `<span class="tag">Also: ${item.also_reported_by.join(", ")}</span>` : "";
    return `
      <div class="news-item">
        <div class="news-item__top">
          <div class="news-item__headline">
            ${item.link ? `<a href="${item.link}" target="_blank" rel="noopener">${item.headline}</a>` : item.headline}
          </div>
          <span class="signal-badge ${sentimentClass}">${item.impact_score > 0 ? "+" : ""}${item.impact_score}</span>
        </div>
        <div class="news-item__meta">
          ${item.ticker ? `<span class="news-item__ticker-tag">${item.ticker}</span>` : ""}
          <span class="news-item__source">${item.source || "Unknown"}${dateStr ? " · " + dateStr : ""}</span>
          ${tierLabel ? `<span class="tag tag--tier">${tierLabel}</span>` : ""}
          <span class="tag">${item.category.replaceAll("_", " ")}</span>
          <span class="tag">${item.horizon.replaceAll("_", " ")}</span>
          ${alsoReported}
        </div>
        <div class="news-item__explanation">${item.explanation}</div>
      </div>`;
  }).join("")}</div>`;
}

// News-source debug panel — shows exactly what happened at each
// source (status, HTTP code, entry counts), per spec section 3. This
// is never hidden behind a "developer mode" toggle since the whole
// point is to make fallback behavior visible by default.
function renderNewsDebugPanel(diagnostics, fallbackUsed) {
  if (!diagnostics || diagnostics.length === 0) return "";

  const statusClass = (status) => {
    if (status === "SUCCESS") return "pct-up";
    if (["RATE_LIMITED", "FORBIDDEN", "HTTP_ERROR", "NETWORK_ERROR", "PARSE_ERROR"].includes(status)) return "pct-down";
    return "pct-flat";
  };

  const rows = diagnostics.map((d) => {
    const detail = d.status === "SUCCESS"
      ? `${d.valid_articles} results${d.http_status ? ` · HTTP ${d.http_status}` : ""}${d.response_size_bytes ? ` · ${(d.response_size_bytes / 1024).toFixed(1)}KB` : ""}`
      : `${d.error || "no results"}`;
    return `
      <tr>
        <td class="ticker-cell">${d.name}</td>
        <td class="${statusClass(d.status)}">${d.status}</td>
        <td class="match-reasons">${detail}</td>
      </tr>`;
  }).join("");

  return `
    <details class="advanced-filters" style="margin-top:14px;">
      <summary>News source diagnostics${fallbackUsed ? " (Yahoo fallback was used)" : ""}</summary>
      <table class="data-table" style="margin-top:10px;">
        <thead><tr><th>Source</th><th>Status</th><th>Detail</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </details>`;
}

async function loadNewsPanel(ticker) {
  const content = document.getElementById("newsContent");
  const badge = document.getElementById("newsQualityBadge");
  content.innerHTML = `<p class="empty-state">Loading news…</p>`;
  badge.textContent = "";
  badge.className = "data-quality-badge";

  try {
    const res = await apiGet(`/stock/${ticker}/news?limit=10`);
    badge.textContent = `${res.meta.source} · ${res.meta.timeliness.replace("_", " ")}`;
    badge.className = `data-quality-badge ${qualityBadgeClass(res.meta.quality)}`;
    content.innerHTML = renderNewsList(res.items) + renderNewsDebugPanel(res.source_diagnostics, res.fallback_used);
  } catch (e) {
    content.innerHTML = `<p class="empty-state">Couldn't load news: ${e.message}</p>`;
  }
}

// ----------------------------------------------------------- market view
async function loadMarketView() {
  const regimeEl = document.getElementById("regimeContent");
  const sectorsEl = document.getElementById("sectorsContent");
  regimeEl.innerHTML = `<p class="empty-state">Loading…</p>`;
  sectorsEl.innerHTML = `<p class="empty-state">Loading…</p>`;

  try {
    const regime = await apiGet("/market/regime");
    const regimeClass = regime.regime.includes("BULL") ? "regime-value--bull"
      : regime.regime.includes("BEAR") ? "regime-value--bear" : "regime-value--neutral";
    regimeEl.innerHTML = `
      <div class="regime-banner">
        <span class="regime-value ${regimeClass}">${regime.regime.replaceAll("_", " ")}</span>
        <span class="tag">Confidence: ${regime.confidence}</span>
        ${regime.vix !== null ? `<span class="tag">VIX ${regime.vix}</span>` : ""}
      </div>
      <p class="regime-explanation">${regime.explanation}</p>
      <div class="regime-signal-grid">
        ${regime.signals.map((s) => `
          <div class="indicator-cell">
            <div class="indicator-cell__label">${s.ticker}</div>
            <div class="indicator-cell__value">${fmtPrice(s.last)}</div>
            <div class="${pctClass(s.momentum_1m_pct)}" style="font-size:11px;margin-top:4px;">${fmtPct(s.momentum_1m_pct)} (1M)</div>
          </div>`).join("")}
      </div>`;
  } catch (e) {
    regimeEl.innerHTML = `<p class="empty-state">Couldn't load market regime: ${e.message}</p>`;
  }

  try {
    const sectors = await apiGet("/market/sectors");
    const rotationTag = (r) => {
      if (r.rotation === "accelerating") return `<span class="tag tag--accel">accelerating</span>`;
      if (r.rotation === "decelerating") return `<span class="tag tag--decel">decelerating</span>`;
      return `<span class="tag">steady</span>`;
    };
    const rows = sectors.sectors.map((s) => `
      <tr>
        <td class="ticker-cell">${s.sector} <span class="ticker-cell-name">${s.etf}</span></td>
        <td class="${pctClass(s.return_1m_pct)}">${fmtPct(s.return_1m_pct)}</td>
        <td class="${pctClass(s.return_3m_pct)}">${fmtPct(s.return_3m_pct)}</td>
        <td>${s.volatility_ann_pct !== null ? s.volatility_ann_pct + "%" : "—"}</td>
        <td>${rotationTag(s)}</td>
      </tr>`).join("");
    const rotationNote = [
      sectors.accelerating_sectors?.length ? `Accelerating: ${sectors.accelerating_sectors.join(", ")}` : null,
      sectors.decelerating_sectors?.length ? `Decelerating: ${sectors.decelerating_sectors.join(", ")}` : null,
    ].filter(Boolean).join(" · ");
    sectorsEl.innerHTML = `
      <p class="empty-state" style="margin-bottom:4px;">
        Top: ${sectors.top_sectors.join(", ") || "—"} &nbsp;·&nbsp; Weakest: ${sectors.weakest_sectors.join(", ") || "—"}
      </p>
      ${rotationNote ? `<p class="empty-state" style="margin-bottom:10px;">${rotationNote}</p>` : ""}
      <table class="data-table">
        <thead><tr><th>Sector</th><th>1M Return</th><th>3M Return</th><th>Ann. Volatility</th><th>Momentum</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (e) {
    sectorsEl.innerHTML = `<p class="empty-state">Couldn't load sector rankings: ${e.message}</p>`;
  }
}

// ----------------------------------------------------------- news view
async function loadNewsAccuracy() {
  const wrap = document.getElementById("newsAccuracyResults");
  try {
    const res = await apiGet("/news/sentiment-accuracy");
    if (res.n_evaluated === 0) {
      wrap.innerHTML = `<p class="empty-state">${res.note}</p>`;
      return;
    }
    const pct = (res.accuracy * 100).toFixed(1);
    wrap.innerHTML = `
      <div class="prediction-metric-grid">
        <div class="indicator-cell">
          <div class="indicator-cell__label">Directional Accuracy</div>
          <div class="indicator-cell__value ${res.accuracy >= 0.5 ? "pct-up" : "pct-down"}">${pct}%</div>
          <div class="progress-bar" style="margin-top:6px;"><div class="progress-bar__fill progress-bar__fill--${res.accuracy >= 0.5 ? "bullish" : "bearish"}" style="width:${pct}%;"></div></div>
        </div>
        <div class="indicator-cell"><div class="indicator-cell__label">Reads Evaluated</div><div class="indicator-cell__value">${res.n_evaluated}</div></div>
      </div>`;
  } catch (e) {
    wrap.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }
}

async function loadNewsView(ticker) {
  loadNewsAccuracy();
  const content = document.getElementById("newsPageContent");
  content.innerHTML = `<p class="empty-state">Loading news…</p>`;

  try {
    let tickers = [];
    if (ticker) {
      tickers = [ticker];
    } else {
      const { watchlist } = await apiGet("/watchlist");
      tickers = watchlist.map((w) => w.ticker);
      if (tickers.length === 0) {
        content.innerHTML = `<p class="empty-state">Your watchlist is empty — add tickers, or search a specific ticker above.</p>`;
        return;
      }
    }

    const results = await Promise.all(tickers.map(async (t) => {
      try {
        const res = await apiGet(`/stock/${t}/news?limit=8`);
        return {
          items: (res.items || []).map((item) => ({ ...item, ticker: t })),
          diagnostics: (res.source_diagnostics || []).map((d) => ({ ...d, name: `${t} — ${d.name}` })),
          fallbackUsed: res.fallback_used,
        };
      } catch {
        return { items: [], diagnostics: [], fallbackUsed: false };
      }
    }));

    const merged = results.flatMap((r) => r.items).sort((a, b) => {
      if (!a.published_at) return 1;
      if (!b.published_at) return -1;
      return new Date(b.published_at) - new Date(a.published_at);
    });
    const allDiagnostics = results.flatMap((r) => r.diagnostics);
    const anyFallback = results.some((r) => r.fallbackUsed);

    content.innerHTML = renderNewsList(merged) + renderNewsDebugPanel(allDiagnostics, anyFallback);
  } catch (e) {
    content.innerHTML = `<p class="empty-state">Couldn't load news: ${e.message}</p>`;
  }
}

function initNewsForm() {
  const form = document.getElementById("newsSearchForm");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const ticker = document.getElementById("newsTickerInput").value.trim().toUpperCase();
    loadNewsView(ticker || null);
  });
}

// ----------------------------------------------------------- scanner
const SCANNER_PRESETS = {
  bullish_momentum: { above_sma50: "true", above_sma200: "true", min_return_1m: "5", min_rsi: "50", max_rsi: "75" },
  oversold: { max_rsi: "35", min_relative_volume: "1.2" },
  high_volume: { min_relative_volume: "2" },
  new_highs: { min_return_3m: "15", above_sma50: "true" },
  quality_uptrend: { above_sma50: "true", above_sma200: "true", min_rsi: "45", max_rsi: "65" },
  pullback_in_uptrend: { above_sma200: "true", max_rsi: "45" },
};

async function runScan(paramsObj) {
  const results = document.getElementById("scannerResults");
  results.innerHTML = `<p class="empty-state">Scanning ~150 liquid US stocks — this can take a little while…</p>`;

  const params = new URLSearchParams(paramsObj);

  try {
    const res = await apiGet(`/scanner?${params.toString()}`);
    if (res.results.length === 0) {
      results.innerHTML = `<p class="empty-state">No matches out of ${res.scanned} scanned (universe: ${res.universe_size}). Try a broader preset or looser filters.</p>`;
      return;
    }
    const rows = res.results.map((r) => `
      <tr>
        <td class="ticker-cell" data-ticker="${r.ticker}" style="cursor:pointer;">${r.ticker}</td>
        <td>${fmtPrice(r.price)}</td>
        <td class="${pctClass(r.return_1d_pct)}">${fmtPct(r.return_1d_pct)}</td>
        <td class="${pctClass(r.return_1m_pct)}">${fmtPct(r.return_1m_pct)}</td>
        <td class="${pctClass(r.return_3m_pct)}">${fmtPct(r.return_3m_pct)}</td>
        <td>${r.rsi_14 ?? "—"}</td>
        <td>${r.relative_volume ? r.relative_volume + "x" : "—"}</td>
        <td>${fmtVolume(r.volume)}</td>
        <td class="match-reasons">${(r.match_reasons || []).join(", ")}</td>
      </tr>`).join("");
    results.innerHTML = `
      <p class="empty-state" style="margin-bottom:10px;">${res.matched} matches out of ${res.scanned} scanned (universe: ${res.universe_size}).${res.note ? " " + res.note : ""}</p>
      <div class="panel">
        <table class="data-table">
          <thead><tr><th>Ticker</th><th>Price</th><th>1D</th><th>1M</th><th>3M</th><th>RSI</th><th>Rel Vol</th><th>Volume</th><th>Why it matched</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    attachAnalyzeHandlers(results);
  } catch (e) {
    results.innerHTML = `<p class="empty-state">Scan failed: ${e.message}</p>`;
  }
}

function initScannerPresets() {
  document.getElementById("scannerPresets").addEventListener("click", (e) => {
    const btn = e.target.closest(".preset-card");
    if (!btn) return;
    document.querySelectorAll(".preset-card").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    runScan(SCANNER_PRESETS[btn.dataset.preset]);
  });
}

function initScannerForm() {
  const form = document.getElementById("scannerForm");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    document.querySelectorAll(".preset-card").forEach((c) => c.classList.remove("active"));

    const paramsObj = {};
    const addIfSet = (id, key) => {
      const val = document.getElementById(id).value;
      if (val !== "") paramsObj[key] = val;
    };
    addIfSet("scanMinRsi", "min_rsi");
    addIfSet("scanMaxRsi", "max_rsi");
    addIfSet("scanMinRelVol", "min_relative_volume");
    addIfSet("scanMinPrice", "min_price");
    addIfSet("scanMinReturn1m", "min_return_1m");
    addIfSet("scanMinReturn3m", "min_return_3m");
    if (document.getElementById("scanAboveSma50").checked) paramsObj.above_sma50 = "true";
    if (document.getElementById("scanAboveSma200").checked) paramsObj.above_sma200 = "true";

    runScan(paramsObj);
  });
}

function renderStockHeader(ticker, quoteRes, indicatorRes) {
  const q = quoteRes.quote;
  const latest = indicatorRes.latest;
  const changePct = latest.daily_return_pct;

  const priceBlock = q
    ? `<div class="stock-header__price ${pctClass(changePct)}">${fmtPrice(q.price)} <span style="font-size:14px;">${fmtPct(changePct)}</span></div>`
    : `<div class="stock-header__price">${fmtPrice(latest.close)} <span style="font-size:13px;" class="empty-state">(last close, live quote unavailable)</span></div>`;

  document.getElementById("stockHeader").innerHTML = `
    <div class="stock-header__ticker">${ticker}</div>
    ${priceBlock}
    <div class="stock-header__meta">
      <div class="stock-header__meta-item"><span class="stock-header__meta-label">Volume</span><span class="stock-header__meta-value">${fmtVolume(latest.volume)}</span></div>
      <div class="stock-header__meta-item"><span class="stock-header__meta-label">Rel. Volume</span><span class="stock-header__meta-value">${latest.relative_volume ? latest.relative_volume.toFixed(2) + "x" : "—"}</span></div>
      <div class="stock-header__meta-item"><span class="stock-header__meta-label">ATR%</span><span class="stock-header__meta-value">${latest.atr_pct_14 ? latest.atr_pct_14.toFixed(2) + "%" : "—"}</span></div>
      <div class="stock-header__meta-item"><span class="stock-header__meta-label">As of</span><span class="stock-header__meta-value">${latest.date || "—"}</span></div>
    </div>`;
}

function renderCandlestick(ticker, bars) {
  const dates = bars.map((b) => b.date);
  const candle = {
    x: dates, open: bars.map((b) => b.open), high: bars.map((b) => b.high),
    low: bars.map((b) => b.low), close: bars.map((b) => b.close),
    type: "candlestick", name: ticker,
    increasing: { line: { color: "#29D398" } },
    decreasing: { line: { color: "#FF5D5D" } },
    xaxis: "x", yaxis: "y",
  };
  const sma50 = { x: dates, y: bars.map((b) => b.sma_50), type: "scatter", mode: "lines", name: "SMA 50", line: { color: "#5B8DEF", width: 1.3 } };
  const sma200 = { x: dates, y: bars.map((b) => b.sma_200), type: "scatter", mode: "lines", name: "SMA 200", line: { color: "#F5A623", width: 1.3 } };
  const bbUpper = { x: dates, y: bars.map((b) => b.bb_upper), type: "scatter", mode: "lines", name: "BB Upper", line: { color: "#3A4150", width: 1, dash: "dot" } };
  const bbLower = { x: dates, y: bars.map((b) => b.bb_lower), type: "scatter", mode: "lines", name: "BB Lower", line: { color: "#3A4150", width: 1, dash: "dot" }, fill: "tonexty", fillcolor: "rgba(58,65,80,0.08)" };
  const volume = {
    x: dates, y: bars.map((b) => b.volume), type: "bar", name: "Volume",
    marker: { color: bars.map((b) => (b.close >= b.open ? "rgba(41,211,152,0.5)" : "rgba(255,93,93,0.5)")) },
    xaxis: "x", yaxis: "y2",
  };

  const layout = {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "#9AA4B2", family: "IBM Plex Mono, monospace", size: 11 },
    margin: { l: 50, r: 20, t: 10, b: 30 },
    showlegend: true,
    legend: { orientation: "h", y: 1.05, font: { size: 10 } },
    xaxis: { rangeslider: { visible: false }, gridcolor: "#1A2029", showspikes: false },
    yaxis: { domain: [0.28, 1], gridcolor: "#1A2029", title: "" },
    yaxis2: { domain: [0, 0.2], gridcolor: "#1A2029", title: "" },
    dragmode: "pan",
  };

  Plotly.newPlot("candlestickChart", [candle, sma50, sma200, bbUpper, bbLower, volume], layout, { responsive: true, displayModeBar: false });
}

function renderInterpretation(indicatorRes) {
  document.getElementById("interpretationText").textContent = indicatorRes.interpretation;
  const s = indicatorRes.structure;
  const tags = [];
  if (s.support) tags.push(`Support ≈ ${fmtPrice(s.support)}`);
  if (s.resistance) tags.push(`Resistance ≈ ${fmtPrice(s.resistance)}`);
  if (s.breakout) tags.push("Breakout");
  if (s.breakdown) tags.push("Breakdown");
  if (s.structure) tags.push(s.structure.replaceAll("_", " "));
  document.getElementById("structureTags").innerHTML = tags.map((t) => `<span class="tag">${t}</span>`).join("");
}

function renderIndicatorGrid(latest) {
  const cells = [
    ["RSI (14)", latest.rsi_14?.toFixed(1)],
    ["MACD Hist", latest.macd_hist?.toFixed(2)],
    ["Stoch %K", latest.stoch_k?.toFixed(1)],
    ["ADX", latest.adx?.toFixed(1)],
    ["ATR (14)", latest.atr_14?.toFixed(2)],
    ["Hist. Vol (20d, ann.)", latest.hist_vol_20 ? latest.hist_vol_20.toFixed(1) + "%" : null],
    ["SMA 50 / 200", (latest.sma_50 && latest.sma_200) ? `${latest.sma_50.toFixed(2)} / ${latest.sma_200.toFixed(2)}` : null],
    ["Drawdown from peak", latest.drawdown_pct ? latest.drawdown_pct.toFixed(1) + "%" : null],
  ];
  document.getElementById("indicatorGrid").innerHTML = cells.map(([label, value]) => `
    <div class="indicator-cell">
      <div class="indicator-cell__label">${label}</div>
      <div class="indicator-cell__value">${value ?? "—"}</div>
    </div>`).join("");
}

// ----------------------------------------------------------- predictions
const SIGNAL_DISPLAY = {
  STRONG_BULLISH_SETUP: { label: "STRONG BULLISH SETUP", cls: "signal-badge--strong-bullish" },
  BULLISH_WATCH: { label: "BULLISH WATCH", cls: "signal-badge--bullish" },
  NEUTRAL: { label: "NEUTRAL", cls: "signal-badge--neutral" },
  BEARISH_WATCH: { label: "BEARISH WATCH", cls: "signal-badge--bearish" },
  HIGH_RISK_POSSIBLE_EXIT: { label: "HIGH RISK / POSSIBLE EXIT", cls: "signal-badge--strong-bearish" },
};

// Descriptive, not imperative — deliberately never says "Buy"/"Sell",
// consistent with the rest of the app (the Exit-Risk engine's
// strongest wording is "review position," never "sell"). Position is
// a 0-100 location on the conviction gauge (10/30/50/70/90 = the
// center of each of the 5 equal zones).
const HEADLINE_DISPLAY = {
  STRONG_BULLISH_SETUP: { label: "STRONG BULLISH", cls: "headline-label--bullish", position: 90 },
  BULLISH_WATCH: { label: "BULLISH", cls: "headline-label--bullish", position: 70 },
  NEUTRAL: { label: "NEUTRAL", cls: "headline-label--neutral", position: 50 },
  BEARISH_WATCH: { label: "BEARISH", cls: "headline-label--bearish", position: 30 },
  HIGH_RISK_POSSIBLE_EXIT: { label: "STRONG BEARISH", cls: "headline-label--bearish", position: 10 },
};

function renderAgreementChip(label, state) {
  // state: true (agrees), false (disagrees), or null/undefined (not available/not meaningful)
  const cls = state === true ? "agree" : state === false ? "disagree" : "na";
  const icon = state === true ? "✓" : state === false ? "✗" : "—";
  return `<span class="agreement-chip agreement-chip--${cls}"><span class="agreement-chip__icon">${icon}</span>${label}</span>`;
}

function renderHeadlineSignal(res) {
  const h = HEADLINE_DISPLAY[res.signal.signal] || HEADLINE_DISPLAY.NEUTRAL;
  const modelsAgreeRatio = res.ensemble.model_agreement || "";
  const [agreeCount, totalCount] = modelsAgreeRatio.split("/").map(Number);
  const modelsState = totalCount ? (agreeCount / totalCount >= 0.6 ? true : agreeCount / totalCount <= 0.4 ? false : null) : null;

  return `
    <div class="panel headline-panel">
      <div class="headline-label ${h.cls}">${h.label}</div>
      <div class="headline-sub">${res.ticker || ""} · ${res.horizon_days}D horizon · ${(res.ensemble.confidence * 100).toFixed(0)}% confidence</div>
      <div class="conviction-gauge"><div class="conviction-gauge__marker" style="left:${h.position}%;"></div></div>
      <div class="conviction-gauge__labels">
        <span>Strong Bearish</span><span>Bearish</span><span>Neutral</span><span>Bullish</span><span>Strong Bullish</span>
      </div>
      <div class="agreement-chips">
        ${renderAgreementChip(`Models ${modelsAgreeRatio || "—"}`, modelsState)}
        ${renderAgreementChip("Technical", res.technical_agrees)}
        ${renderAgreementChip("News", res.news_context && res.news_context.available ? res.news_context.agrees_with_model : null)}
      </div>
    </div>`;
}

let currentPredictionHorizon = 5;
let currentRiskProfile = "moderate";

function initPredictionsPage() {
  const form = document.getElementById("predictForm");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const ticker = document.getElementById("predictTickerInput").value.trim().toUpperCase();
    if (ticker) runPrediction(ticker, currentPredictionHorizon, false);
  });

  document.getElementById("horizonToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-horizon]");
    if (!btn) return;
    document.querySelectorAll("#horizonToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentPredictionHorizon = parseInt(btn.dataset.horizon, 10);
  });

  document.getElementById("riskProfileToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-risk]");
    if (!btn) return;
    document.querySelectorAll("#riskProfileToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentRiskProfile = btn.dataset.risk;
  });

  document.getElementById("retrainBtn").addEventListener("click", () => {
    const ticker = document.getElementById("predictTickerInput").value.trim().toUpperCase();
    if (ticker) runPrediction(ticker, currentPredictionHorizon, true);
  });
}

async function runPrediction(ticker, horizon, forceRetrain) {
  const results = document.getElementById("predictionResults");
  results.innerHTML = `<p class="empty-state">${forceRetrain ? "Retraining" : "Training/predicting"} for ${ticker} (${horizon}D horizon)… this can take anywhere from under a minute to several minutes the first time, depending on your machine. If it's still running after 5+ minutes, check Activity Monitor for a "python3" process actively using CPU — that means it's still working, not stuck.</p>`;

  try {
    const res = await apiGet(`/stock/${ticker}/predict?horizon=${horizon}&risk_profile=${currentRiskProfile}${forceRetrain ? "&force_retrain=true" : ""}`);
    renderPredictionResults(ticker, res);
  } catch (e) {
    results.innerHTML = `<p class="empty-state">Prediction failed: ${e.message}</p>`;
  }
}

function renderPredictionResults(ticker, res) {
  window.lastPredictionContext = { type: "prediction", ticker, ...res };
  const results = document.getElementById("predictionResults");
  const signalInfo = SIGNAL_DISPLAY[res.signal.signal] || { label: res.signal.signal, cls: "signal-badge--neutral" };
  const e = res.ensemble;

  const disagreementBanner = e.low_confidence_disagreement
    ? `<div class="disagreement-banner">⚠ Models disagree on direction — confidence intentionally reduced rather than forcing a call.</div>`
    : "";

  const oodBanner = (res.out_of_distribution && res.out_of_distribution.is_out_of_distribution)
    ? `<div class="disagreement-banner">⚠ ${res.out_of_distribution.warning}</div>`
    : "";

  const newsBanner = (() => {
    const nc = res.news_context;
    if (!nc || !nc.available) return "";
    if (nc.agrees_with_model === false) {
      return `<div class="disagreement-banner">📰 ${nc.summary}</div>`;
    }
    return `<p class="field-hint">📰 ${nc.summary} <em>(informational only — never fed into the model's training, this is a live cross-check)</em></p>`;
  })();

  const voteRows = e.votes.map((v) => `
    <tr>
      <td class="ticker-cell">${v.model}</td>
      <td class="vote-${v.direction}">${v.direction}</td>
      <td>${v.predicted_return_pct > 0 ? "+" : ""}${v.predicted_return_pct}%</td>
      <td>${v.validated_accuracy !== null ? (v.validated_accuracy * 100).toFixed(1) + "%" : "—"}</td>
      <td>${(v.weight * 100).toFixed(0)}%</td>
    </tr>`).join("");

  const perfRows = Object.values(res.model_performance).map((p) => `
    <tr>
      <td class="ticker-cell">${p.model_name}</td>
      <td>${p.direction_accuracy !== null && p.direction_accuracy !== undefined ? (p.direction_accuracy * 100).toFixed(1) + "%" : "—"}</td>
      <td>${p.win_rate !== null && p.win_rate !== undefined ? (p.win_rate * 100).toFixed(0) + "%" : "—"}</td>
      <td>${p.n_trades ?? "—"}</td>
      <td>${p.beats_naive_baseline === true ? '<span class="vote-bullish">✓ yes</span>' : p.beats_naive_baseline === false ? '<span class="vote-bearish">✗ no</span>' : "—"}</td>
    </tr>`).join("");

  const importanceRows = Object.values(res.feature_importance || {}).flat().slice(0, 8).map((f) => `
    <tr><td>${f.feature}</td><td>${f.importance_pct}%</td></tr>`).join("");

  results.innerHTML = `
    ${renderHeadlineSignal(res)}

    <div class="panel panel--summary">
      <div class="panel__header"><h2>What this means</h2></div>
      <p class="plain-summary-text">${res.plain_summary || res.signal.reason}</p>
    </div>

    <div class="panel">
      <div class="prediction-header">
        <span class="signal-badge ${signalInfo.cls} signal-badge--large">${signalInfo.label}</span>
        <span class="tag">${ticker} · ${res.horizon_days}D horizon · as of ${res.as_of_date}</span>
        ${res.from_cache ? '<span class="tag">using cached model (≤24h old)</span>' : '<span class="tag">freshly trained</span>'}
        ${res.relaxed_mode ? `<span class="tag tag--decel">relaxed mode — only ${res.available_trading_days} days of history</span>` : ""}
      </div>
      <p class="interpretation-text">${res.signal.reason}</p>
      ${disagreementBanner}
      ${oodBanner}
      ${newsBanner}
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">Expected Return</div><div class="indicator-cell__value ${pctClass(e.expected_return_pct)}">${e.expected_return_pct > 0 ? "+" : ""}${e.expected_return_pct}%</div></div>
        <div class="indicator-cell">
          <div class="indicator-cell__label">${e.conformal_interval_pct ? `${(e.conformal_confidence * 100).toFixed(0)}% Interval` : "Range"}</div>
          <div class="indicator-cell__value" style="font-size:13px;">${e.conformal_interval_pct ? `${e.conformal_interval_pct[0]}% to ${e.conformal_interval_pct[1]}%` : `${e.prediction_range_pct[0]}% to ${e.prediction_range_pct[1]}%`}</div>
        </div>
        <div class="indicator-cell">
          <div class="indicator-cell__label">Confidence</div>
          <div class="indicator-cell__value">${(e.confidence * 100).toFixed(0)}%</div>
          <div class="progress-bar" style="margin-top:6px;"><div class="progress-bar__fill progress-bar__fill--${e.confidence >= 0.65 ? "bullish" : e.confidence >= 0.4 ? "watch" : "bearish"}" style="width:${(e.confidence * 100).toFixed(0)}%;"></div></div>
        </div>
        <div class="indicator-cell"><div class="indicator-cell__label">Model Agreement</div><div class="indicator-cell__value">${e.model_agreement}</div></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel__header"><h2>Per-model breakdown</h2></div>
      <table class="data-table vote-table">
        <thead><tr><th>Model</th><th>Direction</th><th>Predicted Return</th><th>Validated Accuracy</th><th>Ensemble Weight</th></tr></thead>
        <tbody>${voteRows}</tbody>
      </table>
    </div>

    <div class="panel-grid panel-grid--two">
      <div class="panel">
        <div class="panel__header"><h2>Walk-forward validated performance</h2></div>
        <table class="data-table">
          <thead><tr><th>Model</th><th>Direction Acc.</th><th>Win Rate</th><th>Trades</th><th>Beats Naive?</th></tr></thead>
          <tbody>${perfRows}</tbody>
        </table>
        <p class="field-hint">All figures are genuine out-of-sample results from walk-forward validation — never fabricated. "Beats Naive?" checks whether the model actually outperforms simply predicting no change at all.</p>
      </div>
      <div class="panel">
        <div class="panel__header"><h2>Risk sizing</h2></div>
        <p class="interpretation-text"><strong>Position sizing:</strong> ${res.position_sizing.suggested_position_pct !== null ? res.position_sizing.suggested_position_pct + "% of capital" : "No suggestion"}</p>
        <p class="field-hint">${res.position_sizing.explanation}</p>
        <p class="interpretation-text" style="margin-top:10px;"><strong>ATR stop:</strong> ${res.atr_stop.stop_price !== null ? "$" + res.atr_stop.stop_price : "N/A"}</p>
        <p class="field-hint">${res.atr_stop.explanation}</p>
      </div>
    </div>

    ${importanceRows ? `
    <div class="panel">
      <div class="panel__header"><h2>Feature importance (XGBoost)</h2></div>
      <table class="data-table"><tbody>${importanceRows}</tbody></table>
    </div>` : ""}

    ${res.notes && res.notes.length ? `<p class="field-hint">${res.notes.join(" · ")}</p>` : ""}
    <p class="disclaimer" style="margin-top:14px;">This is a probabilistic research estimate, not financial advice. Past validation performance does not guarantee future results.</p>
  `;
}

// ----------------------------------------------------------- models page
async function loadModelsPage() {
  const availEl = document.getElementById("modelAvailability");
  const accEl = document.getElementById("accuracyTracking");

  try {
    const avail = await apiGet("/models/availability");
    availEl.innerHTML = `
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">Baseline (sklearn)</div><div class="indicator-cell__value ${avail.sklearn_baseline ? "pct-up" : "pct-down"}">${avail.sklearn_baseline ? "Available" : "Unavailable"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">XGBoost</div><div class="indicator-cell__value ${avail.xgboost ? "pct-up" : "pct-down"}">${avail.xgboost ? "Available" : "Unavailable"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">LSTM (PyTorch)</div><div class="indicator-cell__value ${avail.lstm_pytorch ? "pct-up" : "pct-down"}">${avail.lstm_pytorch ? "Available" : "Unavailable"}</div></div>
      </div>
      ${avail.notes.length ? `<p class="field-hint">${avail.notes.join(" · ")}</p>` : ""}
    `;
  } catch (e) {
    availEl.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }

  const schedEl = document.getElementById("schedulerStatus");
  try {
    const sched = await apiGet("/scheduler/status");
    if (!sched.available) {
      schedEl.innerHTML = `<p class="empty-state">Not running — apscheduler isn't installed. Predictions still work; you'll need to click "Evaluate matured predictions" manually below. Run: pip install apscheduler</p>`;
    } else {
      schedEl.innerHTML = `
        <div class="prediction-metric-grid">
          <div class="indicator-cell"><div class="indicator-cell__label">Status</div><div class="indicator-cell__value ${sched.running ? "pct-up" : "pct-down"}">${sched.running ? "Running" : "Stopped"}</div></div>
          <div class="indicator-cell"><div class="indicator-cell__label">Checks Run</div><div class="indicator-cell__value">${sched.run_count}</div></div>
          <div class="indicator-cell"><div class="indicator-cell__label">Last Check</div><div class="indicator-cell__value" style="font-size:12px;">${sched.last_run_at ? new Date(sched.last_run_at).toLocaleTimeString() : "—"}</div></div>
        </div>
        <p class="field-hint">Automatically checks for matured predictions every 60 minutes and scores them against real outcomes — no manual clicking needed. This is also what feeds the adaptive ensemble weighting (models that have been more accurate in real, tracked predictions get more say in future ones).</p>`;
    }
  } catch (e) {
    schedEl.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }

  try {
    const acc = await apiGet("/predictions/accuracy");
    const entries = Object.entries(acc.accuracy_by_horizon);
    if (entries.length === 0) {
      accEl.innerHTML = `<p class="empty-state">No predictions have matured and been evaluated yet. Make a prediction, then check back after its horizon has passed.</p>`;
    } else {
      const rows = entries.map(([horizon, stats]) => `
        <tr><td>${horizon}D</td><td>${stats.n_evaluated}</td><td>${stats.accuracy !== null ? (stats.accuracy * 100).toFixed(1) + "%" : "—"}</td></tr>
      `).join("");
      accEl.innerHTML = `
        <table class="data-table">
          <thead><tr><th>Horizon</th><th>Predictions Evaluated</th><th>Direction Accuracy</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    }
  } catch (e) {
    accEl.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }
}

function initModelsPage() {
  document.getElementById("evaluatePredictionsBtn").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.textContent = "Evaluating…";
    try {
      const res = await apiPost("/predictions/evaluate");
      btn.textContent = `Evaluated ${res.evaluated} (${res.skipped_not_yet_matured_or_no_data} not yet ready)`;
      setTimeout(() => { btn.textContent = "Evaluate matured predictions"; }, 3000);
      loadModelsPage();
    } catch (err) {
      btn.textContent = "Evaluate matured predictions";
    }
  });

  document.getElementById("modelVersionsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = document.getElementById("modelVersionsTickerInput").value.trim().toUpperCase();
    const container = document.getElementById("modelVersionsResults");
    if (!ticker) return;
    container.innerHTML = `<p class="empty-state">Loading…</p>`;
    try {
      const res = await apiGet(`/stock/${ticker}/models`);
      if (res.model_versions.length === 0) {
        container.innerHTML = `<p class="empty-state">No trained models for ${ticker} yet — make a prediction for it first.</p>`;
        return;
      }
      const rows = res.model_versions.map((v) => `
        <tr>
          <td class="ticker-cell">${v.model_type}</td>
          <td>${v.horizon_days}D</td>
          <td>${new Date(v.trained_at).toLocaleString()}</td>
          <td>${v.validation_metrics.direction_accuracy !== undefined && v.validation_metrics.direction_accuracy !== null ? (v.validation_metrics.direction_accuracy * 100).toFixed(1) + "%" : "—"}</td>
          <td>${v.trading_stats.win_rate !== undefined && v.trading_stats.win_rate !== null ? (v.trading_stats.win_rate * 100).toFixed(0) + "%" : "—"}</td>
        </tr>`).join("");
      container.innerHTML = `
        <table class="data-table">
          <thead><tr><th>Model</th><th>Horizon</th><th>Trained At</th><th>Direction Acc.</th><th>Win Rate</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    } catch (err) {
      container.innerHTML = `<p class="empty-state">Couldn't load: ${err.message}</p>`;
    }
  });
}

// ----------------------------------------------------------- portfolio
function initPortfolioForm() {
  const form = document.getElementById("portfolioAddForm");
  const tickerInput = document.getElementById("portfolioTickerInput");
  const entryPriceInput = document.getElementById("portfolioEntryPriceInput");
  const entryPriceHint = document.getElementById("portfolioEntryPriceHint");

  // Auto-fill entry price with the current live quote when you tab out
  // of the ticker field — most adds are "I'm entering this position
  // now," so this saves typing a price from memory. Never overwrites
  // a price you've already typed yourself.
  tickerInput.addEventListener("blur", async () => {
    const ticker = tickerInput.value.trim().toUpperCase();
    if (!ticker || entryPriceInput.value !== "") return;
    entryPriceHint.textContent = "Fetching current price…";
    try {
      const res = await apiGet(`/stock/${ticker}/quote`);
      if (res.quote && res.quote.price) {
        entryPriceInput.value = res.quote.price;
        entryPriceHint.textContent = `Auto-filled with ${ticker}'s current price — edit if this is a past purchase.`;
      } else {
        entryPriceHint.textContent = "Couldn't fetch a live price — enter it manually.";
      }
    } catch {
      entryPriceHint.textContent = "Couldn't fetch a live price — enter it manually.";
    }
  });

  // Clear the auto-fill hint and allow re-fetching if the ticker changes.
  tickerInput.addEventListener("input", () => {
    entryPriceHint.textContent = "";
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = tickerInput.value.trim().toUpperCase();
    const shares = parseFloat(document.getElementById("portfolioSharesInput").value);
    const entryPrice = parseFloat(entryPriceInput.value);
    if (!ticker || !shares || !entryPrice || shares <= 0 || entryPrice <= 0) {
      showToast("Enter a ticker, a positive share count, and a positive entry price.", "error");
      return;
    }
    try {
      await apiPost(`/portfolio?ticker=${ticker}&shares=${shares}&entry_price=${entryPrice}`);
      tickerInput.value = "";
      document.getElementById("portfolioSharesInput").value = "";
      entryPriceInput.value = "";
      entryPriceHint.textContent = "";
      showToast(`Added ${ticker} to your portfolio.`, "success");
      loadPortfolioView();
    } catch (err) {
      showToast(`Couldn't add holding: ${err.message}`, "error");
    }
  });
}

async function loadPortfolioView() {
  const results = document.getElementById("portfolioResults");
  results.innerHTML = `<p class="empty-state">Loading…</p>`;
  try {
    const summary = await apiGet("/portfolio");
    if (summary.holdings.length === 0) {
      results.innerHTML = `<p class="empty-state">No holdings yet — add one above.</p>`;
      return;
    }
    const rows = summary.holdings.map((h) => {
      if (!h.price_available) {
        return `
          <tr>
            <td class="ticker-cell" data-ticker="${h.ticker}" style="cursor:pointer;">${h.ticker}</td>
            <td colspan="6" class="empty-state">Live price unavailable — ${h.price_error || "unknown error"}</td>
            <td><button class="remove-btn" data-remove-holding="${h.id}">Remove</button></td>
          </tr>`;
      }
      const plClass = h.unrealized_pl >= 0 ? "pl-positive" : "pl-negative";
      return `
        <tr>
          <td class="ticker-cell" data-ticker="${h.ticker}" style="cursor:pointer;">${h.ticker}</td>
          <td>${h.shares}</td>
          <td>${fmtPrice(h.entry_price)}</td>
          <td>${fmtPrice(h.current_price)}</td>
          <td>${fmtPrice(h.current_value)}</td>
          <td class="${plClass}">${h.unrealized_pl >= 0 ? "+" : ""}${fmtPrice(h.unrealized_pl)} (${fmtPct(h.unrealized_pl_pct)})</td>
          <td style="min-width:110px;">${h.allocation_pct !== null ? `<div class="progress-bar"><div class="progress-bar__fill progress-bar__fill--accent" style="width:${h.allocation_pct}%;"></div></div><span style="font-size:11px; color:var(--text-muted);">${h.allocation_pct}%</span>` : "—"}</td>
          <td><button class="remove-btn" data-remove-holding="${h.id}">Remove</button></td>
        </tr>`;
    }).join("");

    const totalPlClass = summary.total_unrealized_pl !== null && summary.total_unrealized_pl >= 0 ? "pl-positive" : "pl-negative";
    results.innerHTML = `
      <div class="prediction-metric-grid" style="margin-bottom:16px;">
        <div class="indicator-cell"><div class="indicator-cell__label">Total Value</div><div class="indicator-cell__value">${summary.total_value !== null ? fmtPrice(summary.total_value) : "—"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Cost Basis</div><div class="indicator-cell__value">${fmtPrice(summary.total_cost_basis)}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Unrealized P&L</div><div class="indicator-cell__value ${totalPlClass}">${summary.total_unrealized_pl !== null ? fmtPrice(summary.total_unrealized_pl) : "—"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Return</div><div class="indicator-cell__value ${totalPlClass}">${summary.total_unrealized_pl_pct !== null ? fmtPct(summary.total_unrealized_pl_pct) : "—"}</div></div>
      </div>
      ${summary.note ? `<p class="field-hint" style="margin-bottom:10px;">${summary.note}</p>` : ""}
      <table class="data-table">
        <thead><tr><th>Ticker</th><th>Shares</th><th>Entry</th><th>Current</th><th>Value</th><th>P&L</th><th>Allocation</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;

    attachAnalyzeHandlers(results);
    results.querySelectorAll("[data-remove-holding]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await apiDelete(`/portfolio/${btn.dataset.removeHolding}`);
        loadPortfolioView();
      });
    });
  } catch (e) {
    results.innerHTML = `<p class="empty-state">Couldn't load portfolio: ${e.message}</p>`;
  }
}

// ----------------------------------------------------------- alerts
async function loadAlertsView() {
  const results = document.getElementById("alertsResults");
  results.innerHTML = `<p class="empty-state">Loading…</p>`;
  try {
    const res = await apiGet("/alerts");
    updateAlertBadge(res.unread_count);
    if (res.alerts.length === 0) {
      results.innerHTML = `<p class="empty-state">No alerts yet — they'll appear here when something material changes (a signal flip, a portfolio risk escalation).</p>`;
      return;
    }
    results.innerHTML = res.alerts.map((a) => `
      <div class="alert-item ${a.read ? "" : "alert-item--unread"}">
        <div class="alert-item__top">
          <span class="alert-item__title">${a.title}</span>
          <span class="alert-item__time">${new Date(a.created_at).toLocaleString()}</span>
        </div>
        ${a.reasons && a.reasons.length ? `<ul class="alert-item__reasons">${a.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>` : ""}
      </div>
    `).join("");
  } catch (e) {
    results.innerHTML = `<p class="empty-state">Couldn't load alerts: ${e.message}</p>`;
  }
}

function updateAlertBadge(count) {
  ["alertBadge", "topbarAlertBadge"].forEach((id) => {
    const badge = document.getElementById(id);
    if (!badge) return;
    if (count > 0) {
      badge.textContent = count;
      badge.style.display = "inline-block";
    } else {
      badge.style.display = "none";
    }
  });
}

function initAlertsPage() {
  document.getElementById("checkAlertsNowBtn").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.textContent = "Checking…";
    try {
      const res = await apiPost("/alerts/check-now");
      btn.textContent = `Checked (${res.technical_alerts_fired + res.exit_risk_alerts_fired} new)`;
    } catch {
      btn.textContent = "Check now";
    }
    setTimeout(() => { btn.textContent = "Check now"; }, 2500);
    loadAlertsView();
  });

  document.getElementById("markAllReadBtn").addEventListener("click", async () => {
    await apiPost("/alerts/read-all");
    loadAlertsView();
  });
}

async function refreshAlertBadge() {
  try {
    const res = await apiGet("/alerts?unread_only=true");
    updateAlertBadge(res.unread_count);
  } catch {
    // silent — the badge just won't update this cycle, not worth surfacing an error for
  }
}

// ----------------------------------------------------------- backtesting
let currentBacktestHorizon = 5;

let currentTCNHorizon = 5;

let currentVolatilityRiskTolerance = "moderate";

function initVolatilityForm() {
  const form = document.getElementById("volatilityForm");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = document.getElementById("volatilityTickerInput").value.trim().toUpperCase();
    if (!ticker) return;
    await runVolatilitySurface(ticker);
  });

  document.getElementById("volatilityRiskToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-risk]");
    if (!btn) return;
    document.querySelectorAll("#volatilityRiskToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentVolatilityRiskTolerance = btn.dataset.risk;
    if (window.lastVolatilityResult) {
      renderVolatilityResults(window.lastVolatilityTicker, window.lastVolatilityResult);
    }
  });
}

function buildVolatilityBottomLine(ticker, res, riskTolerance) {
  const atmPct = res.atm_iv_30d !== null ? res.atm_iv_30d * 100 : null;
  const skewPct = res.put_call_skew_30d !== null ? res.put_call_skew_30d * 100 : null;
  const rank = res.iv_rank;

  if (atmPct === null) {
    return { level: "unknown", text: "Not enough data to read this ticker's current volatility level." };
  }

  let level, levelLabel;
  if (rank.available) {
    level = rank.interpretation === "historically elevated" ? "elevated" : rank.interpretation === "historically low" ? "low" : "typical";
  } else {
    level = atmPct >= 50 ? "elevated" : atmPct <= 20 ? "low" : "typical";
  }
  levelLabel = level === "elevated" ? "Elevated" : level === "low" ? "Calm" : "Typical";

  const skewNote = skewPct !== null && skewPct >= 3 ? " Downside hedging demand is notably higher than usual." :
                    skewPct !== null && skewPct <= -3 ? " Upside speculation is notably higher than usual." : "";

  const byRisk = {
    elevated: {
      conservative: `bigger price swings are being priced in than usual for ${ticker} — a reasonable moment to size smaller or wait for the catalyst to pass.`,
      moderate: `bigger price swings are being priced in both directions — the market expects more movement, not a direction.`,
      aggressive: `bigger expected swings — more potential upside and more potential downside than usual, in equal measure.`,
    },
    low: {
      conservative: `the options market expects a relatively calm period for ${ticker} right now.`,
      moderate: `a relatively calm reading — smaller expected price swings than this stock's own recent norm.`,
      aggressive: `options are relatively cheap right now — less movement priced in, for whatever that's worth to your strategy.`,
    },
    typical: {
      conservative: `nothing unusual — ${ticker}'s expected volatility is sitting in its normal range.`,
      moderate: `nothing unusual here — volatility is in its typical range for this stock.`,
      aggressive: `no unusual volatility signal either way right now.`,
    },
  };

  const text = `<strong>${levelLabel} volatility.</strong> ${byRisk[level][riskTolerance]}${skewNote}`;
  return { level, text };
}

async function runVolatilitySurface(ticker) {
  const results = document.getElementById("volatilityResults");
  results.innerHTML = `<div class="panel"><p class="empty-state">Fetching live options chains for ${ticker} and solving for implied volatility across every expiry…</p></div>`;
  try {
    const res = await apiGet(`/stock/${ticker}/iv-surface`);
    window.lastVolatilityTicker = ticker;
    window.lastVolatilityResult = res;
    renderVolatilityResults(ticker, res);
  } catch (e) {
    results.innerHTML = `<div class="panel"><p class="empty-state">Couldn't build a surface: ${e.message}</p></div>`;
  }
}

function renderVolatilityResults(ticker, res) {
  const rank = res.iv_rank;
  const rankDisplay = rank.available
    ? `<div class="indicator-cell"><div class="indicator-cell__label">IV Rank (${rank.n_readings} readings)</div><div class="indicator-cell__value">${rank.percentile}<span style="font-size:11px;"> — ${rank.interpretation}</span></div></div>`
    : `<div class="indicator-cell"><div class="indicator-cell__label">IV Rank</div><div class="indicator-cell__value" style="font-size:12px;">${rank.reason}</div></div>`;

  const dataQualityHtml = (res.data_quality_notes || []).length > 0
    ? `<div class="disagreement-banner" style="margin-top:10px;">${res.data_quality_notes.join(" ")}</div>`
    : "";

  const atmPct = res.atm_iv_30d !== null ? res.atm_iv_30d * 100 : null;
  const skewPct = res.put_call_skew_30d !== null ? res.put_call_skew_30d * 100 : null;
  const monthlyMovePct = atmPct !== null ? (atmPct / Math.sqrt(12)).toFixed(1) : null;

  const bottomLine = buildVolatilityBottomLine(ticker, res, currentVolatilityRiskTolerance);
  const bottomLineCls = bottomLine.level === "elevated" ? "bottom-line--elevated" : bottomLine.level === "low" ? "bottom-line--low" : "bottom-line--typical";

  document.getElementById("volatilityResults").innerHTML = `
    <div class="panel bottom-line-callout ${bottomLineCls}">
      <p class="bottom-line-callout__text">${bottomLine.text}</p>
      <p class="field-hint" style="margin:6px 0 0 0;">This describes expected price <em>movement</em>, not whether ${ticker} is a good business — it can't tell you to buy or not, only how much the market expects the price to swing. Use the toggle above to see this from a different risk angle.</p>
    </div>

    <div class="panel">
      <div class="panel__header"><h2>${ticker} — implied volatility surface</h2></div>
      <p class="field-hint" style="margin-top:-4px; margin-bottom:12px;">
        ${res.n_contracts_used} contracts survived quality filtering across ${res.expiries_processed.length} expiries.
        Spot price: ${fmtPrice(res.spot_price)}.
      </p>
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">ATM IV (~30D)</div><div class="indicator-cell__value">${atmPct !== null ? atmPct.toFixed(1) + "%" : "—"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Put/Call Skew (~30D)</div><div class="indicator-cell__value ${res.put_call_skew_30d > 0 ? "pct-down" : "pct-up"}">${skewPct !== null ? (skewPct > 0 ? "+" : "") + skewPct.toFixed(1) + "%" : "—"}</div></div>
        ${rankDisplay}
      </div>
      ${dataQualityHtml}
    </div>

    <div class="panel">
      <div class="panel__header"><h2>Interactive surface</h2></div>
      <div id="volatilitySurfaceChart" style="height:480px;"></div>
    </div>

    <details class="panel volatility-details">
      <summary>Explain this in full — what an IV surface is, and why</summary>
      <div class="volatility-details__body">
        <p><strong>What an IV surface is, and why it exists.</strong> Implied volatility is the market's own estimate of how much a stock's price is likely to swing — up or down — reverse-engineered from what traders are actually paying for options on ${ticker} right now. It's a surface, not one number, because that expectation genuinely differs by strike distance and time to expiry — real markets price large downside moves as more likely than simple models assume.</p>

        ${atmPct !== null ? `<p><strong>ATM IV of ${atmPct.toFixed(1)}%</strong> implies roughly a <strong>${monthlyMovePct}%</strong> expected move, either direction, over about a month. It says nothing about which direction.</p>` : ""}

        ${skewPct !== null ? `<p><strong>Skew of ${skewPct > 0 ? "+" : ""}${skewPct.toFixed(1)}%</strong> means ${skewPct > 0 ? "downside puts are pricing in more fear than upside calls — the normal state for most stocks, more pronounced when the market is bracing for a specific downside event." : "upside calls are pricing in more than downside puts — less common, often speculative rally demand."}</p>` : ""}

        ${rank.available ? `<p><strong>IV Rank of ${rank.percentile}</strong> compares today's IV to ${ticker}'s own recent history, not to other stocks — different companies have completely different normal baselines.</p>` : ""}

        <p><strong>Why this can't tell you to buy or not:</strong> it describes expected price movement magnitude and hedging sentiment — nothing about whether the business itself is worth owning. A calm stock can be a bad investment; a wildly volatile one around a single event can be a great one. For business quality, use this app's Fundamentals and Predictions pages instead — this is one input, not a verdict.</p>
      </div>
    </details>

    <p class="disclaimer" style="margin-top:14px;">Real Black-Scholes implied volatility solved from live market prices via Brent's method — not a prediction, a mathematical read of what the options market is currently pricing in. Informational only, not financial advice.</p>
  `;

  const viz = res.visualization;
  if (viz.iv_surface) {
    const zPercent = viz.iv_surface.map((row) => row.map((v) => (v !== null ? v * 100 : null)));
    Plotly.newPlot("volatilitySurfaceChart", [{
      type: "surface",
      x: viz.tenor_grid_days,
      y: viz.moneyness_grid,
      z: zPercent,
      colorscale: "Viridis",
      colorbar: { title: { text: "IV %", font: { color: "#8A93A6" } }, tickfont: { color: "#8A93A6" } },
    }], {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      margin: { l: 0, r: 0, t: 10, b: 0 },
      scene: {
        xaxis: { title: { text: "Days to Expiry", font: { color: "#C9CDD6" } }, color: "#8A93A6", gridcolor: "#232838", tickfont: { color: "#8A93A6" } },
        yaxis: { title: { text: "Moneyness (K/S)", font: { color: "#C9CDD6" } }, color: "#8A93A6", gridcolor: "#232838", tickfont: { color: "#8A93A6" } },
        zaxis: { title: { text: "Implied Vol (%)", font: { color: "#C9CDD6" } }, color: "#8A93A6", gridcolor: "#232838", tickfont: { color: "#8A93A6" } },
      },
      font: { family: "IBM Plex Mono, monospace", size: 10, color: "#8A93A6" },
    }, { responsive: true, displayModeBar: false });
  } else {
    document.getElementById("volatilitySurfaceChart").innerHTML = `<p class="empty-state">Not enough data to render a full surface.</p>`;
  }
}

function initTCNResearchForm() {
  const form = document.getElementById("tcnForm");
  document.getElementById("tcnHorizonToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-horizon]");
    if (!btn) return;
    document.querySelectorAll("#tcnHorizonToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentTCNHorizon = parseInt(btn.dataset.horizon, 10);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = document.getElementById("tcnTickerInput").value.trim().toUpperCase();
    if (!ticker) return;
    await runTCNComparison(ticker, currentTCNHorizon);
    await loadTCNBestConfig(ticker, currentTCNHorizon);
    await loadTCNTrialHistory(ticker, currentTCNHorizon);
  });

  document.getElementById("tcnTriggerSearchBtn").addEventListener("click", async () => {
    const ticker = document.getElementById("tcnTickerInput").value.trim().toUpperCase();
    if (!ticker) {
      showToast("Enter a ticker first.", "error");
      return;
    }
    const btn = document.getElementById("tcnTriggerSearchBtn");
    btn.textContent = "Searching… (this can take a few minutes)";
    try {
      const res = await apiPostJson(`/tcn/${ticker}/search?horizon=${currentTCNHorizon}`, {});
      showToast(`Tried ${res.candidates_tried} new config(s), ${res.evaluated} evaluated successfully.`, "success");
      await loadTCNBestConfig(ticker, currentTCNHorizon);
      await loadTCNTrialHistory(ticker, currentTCNHorizon);
    } catch (err) {
      showToast(`Search failed: ${err.message}`, "error");
    }
    btn.textContent = "Search for a better config";
  });

  apiGet("/tcn/status").then((res) => {
    document.getElementById("tcnNotAvailable").style.display = res.available ? "none" : "block";
    document.getElementById("tcnInterface").style.display = res.available ? "block" : "none";
  }).catch(() => {});
}

async function runTCNComparison(ticker, horizon) {
  const results = document.getElementById("tcnComparisonResults");
  results.innerHTML = `<div class="panel"><p class="empty-state">Running the 5-way comparison for ${ticker} (${horizon}D)… this retrains a TCN across many walk-forward windows and can take a few minutes.</p></div>`;
  try {
    const res = await apiGet(`/tcn/${ticker}/comparison?horizon=${horizon}`);
    renderTCNComparisonResults(ticker, res);
  } catch (e) {
    results.innerHTML = `<div class="panel"><p class="empty-state">Comparison failed: ${e.message}</p></div>`;
  }
}

const TCN_VARIANT_LABELS = {
  buy_and_hold: "Buy & Hold",
  raw_model_signal: "Raw Model Signal",
  model_plus_dead_zone: "+ Neutral Zone",
  model_plus_vol_scaling: "+ Volatility Scaling",
  model_plus_vol_scaling_and_cap: "+ Exposure Cap",
};

function renderTCNComparisonResults(ticker, res) {
  const rows = Object.entries(res.comparison).map(([key, v]) => `
    <tr>
      <td class="ticker-cell">${TCN_VARIANT_LABELS[key] || key}</td>
      <td class="${v.total_return_pct >= 0 ? "pct-up" : "pct-down"}">${v.total_return_pct >= 0 ? "+" : ""}${v.total_return_pct}%</td>
      <td class="pct-down">${v.max_drawdown_pct !== null ? v.max_drawdown_pct + "%" : "—"}</td>
      <td>${v.sharpe_ratio ?? "—"}</td>
      <td>${v.n_trades ?? "—"}</td>
      <td>${v.win_rate !== null && v.win_rate !== undefined ? (v.win_rate * 100).toFixed(0) + "%" : "—"}</td>
      <td>${v.max_abs_exposure_pct}%</td>
    </tr>`).join("");

  document.getElementById("tcnComparisonResults").innerHTML = `
    <div class="panel">
      <div class="panel__header"><h2>${ticker} — ${res.horizon_days}D 5-way comparison</h2></div>
      <p class="field-hint" style="margin-top:-4px; margin-bottom:12px;">${res.n_splits} walk-forward windows, ${res.n_predictions} out-of-sample predictions. Every variant after Buy &amp; Hold uses the exact same underlying model predictions — only the risk-management stages applied differ between them.</p>
      <table class="data-table">
        <thead><tr><th>Variant</th><th>Return</th><th>Max Drawdown</th><th>Sharpe</th><th>Trades</th><th>Win Rate</th><th>Max Exposure</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="disclaimer" style="margin-top:14px;">Simulated performance on historical data, including a 0.10% round-trip transaction cost assumption. A research and paper-trading feature — not a promise of profitable live trading.</p>
    </div>`;
}

async function loadTCNBestConfig(ticker, horizon) {
  const wrap = document.getElementById("tcnBestConfigResults");
  try {
    const res = await apiGet(`/tcn/${ticker}/best-config?horizon=${horizon}`);
    if (!res.found) {
      wrap.innerHTML = `<p class="empty-state">${res.note}</p>`;
      return;
    }
    const c = res.config;
    const gapWarning = (res.holdout_score !== null && res.holdout_score !== undefined && res.search_score - res.holdout_score > 0.1)
      ? `<div class="disagreement-banner">⚠ The search-period score is notably higher than the holdout score — a sign this configuration may be overfit to the search process, not a genuine edge.</div>`
      : "";
    wrap.innerHTML = `
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">Search Score</div><div class="indicator-cell__value">${res.search_score.toFixed(3)}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Holdout Score</div><div class="indicator-cell__value">${res.holdout_score !== null && res.holdout_score !== undefined ? res.holdout_score.toFixed(3) : "not yet checked"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Layers / Kernel</div><div class="indicator-cell__value">${c.num_layers} / ${c.kernel_size}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Dead Zone</div><div class="indicator-cell__value">${c.dead_zone_threshold}</div></div>
      </div>
      ${gapWarning}
      <p class="field-hint" style="margin-top:10px;">Found from ${res.n_search_splits} walk-forward splits, ${res.n_search_trades} validated trades. Never evaluated on the same data used to compare it against other configs.</p>`;
  } catch (e) {
    wrap.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }
}

async function loadTCNTrialHistory(ticker, horizon) {
  const wrap = document.getElementById("tcnTrialHistoryResults");
  try {
    const res = await apiGet(`/tcn/${ticker}/trial-history?horizon=${horizon}`);
    if (res.trials.length === 0) {
      wrap.innerHTML = `<p class="empty-state">No trials yet for this ticker/horizon.</p>`;
      return;
    }
    const rows = res.trials.map((t) => `
      <tr>
        <td>${new Date(t.created_at).toLocaleString()}</td>
        <td>${t.config.num_layers}L / k${t.config.kernel_size} / dz${t.config.dead_zone_threshold}</td>
        <td>${t.search_score.toFixed(3)}</td>
        <td>${t.n_search_splits}</td>
        <td>${t.n_search_trades}</td>
      </tr>`).join("");
    wrap.innerHTML = `
      <table class="data-table">
        <thead><tr><th>When</th><th>Config</th><th>Score</th><th>Splits</th><th>Trades</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch (e) {
    wrap.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }
}

function initBacktestForm() {
  const form = document.getElementById("backtestForm");
  document.getElementById("backtestHorizonToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-horizon]");
    if (!btn) return;
    document.querySelectorAll("#backtestHorizonToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentBacktestHorizon = parseInt(btn.dataset.horizon, 10);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = document.getElementById("backtestTickerInput").value.trim().toUpperCase();
    if (!ticker) return;
    await runBacktest(ticker, currentBacktestHorizon);
  });
}

async function runBacktest(ticker, horizon) {
  const results = document.getElementById("backtestResults");
  results.innerHTML = `<p class="empty-state">Running backtest for ${ticker} (${horizon}D horizon)… this retrains models across many historical windows and can take a couple minutes.</p>`;
  try {
    const res = await apiGet(`/stock/${ticker}/backtest?horizon=${horizon}`);
    renderBacktestResults(ticker, res);
  } catch (e) {
    results.innerHTML = `<p class="empty-state">Backtest failed: ${e.message}</p>`;
  }
}

function renderBacktestResults(ticker, res) {
  window.lastBacktestContext = { type: "backtest", ticker, ...res };
  const results = document.getElementById("backtestResults");
  const s = res.stats;
  const stratClass = s.total_return_pct >= 0 ? "pct-up" : "pct-down";
  const bhClass = s.buy_and_hold_return_pct >= 0 ? "pct-up" : "pct-down";
  const beatBuyHold = s.total_return_pct > s.buy_and_hold_return_pct;

  const tradeRows = res.trade_log.slice(-15).reverse().map((t) => `
    <tr>
      <td>${t.date}</td>
      <td class="vote-${t.direction === "long" ? "bullish" : "bearish"}">${t.direction}</td>
      <td>${t.position_pct}%</td>
      <td class="${t.actual_return_pct >= 0 ? "pct-up" : "pct-down"}">${t.actual_return_pct >= 0 ? "+" : ""}${t.actual_return_pct}%</td>
      <td class="${t.trade_pl_pct >= 0 ? "pct-up" : "pct-down"}">${t.trade_pl_pct >= 0 ? "+" : ""}${t.trade_pl_pct}%</td>
      <td>${t.correct ? "✓" : "✗"}</td>
    </tr>`).join("");

  results.innerHTML = `
    <div class="panel">
      <div class="panel__header"><h2>${ticker} — ${res.horizon_days}D horizon backtest</h2></div>
      <p class="interpretation-text">
        ${beatBuyHold
          ? `This strategy outperformed simply buying and holding ${ticker} over the same period.`
          : `This strategy underperformed simply buying and holding ${ticker} over the same period — a common, honest finding for short-horizon trading signals during a strong trend.`}
      </p>
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">Strategy Return</div><div class="indicator-cell__value ${stratClass}">${s.total_return_pct >= 0 ? "+" : ""}${s.total_return_pct}%</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Buy & Hold Return</div><div class="indicator-cell__value ${bhClass}">${s.buy_and_hold_return_pct >= 0 ? "+" : ""}${s.buy_and_hold_return_pct}%</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Max Drawdown</div><div class="indicator-cell__value pct-down">${s.max_drawdown_pct}%</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Win Rate</div><div class="indicator-cell__value">${s.win_rate !== null ? (s.win_rate * 100).toFixed(0) + "%" : "—"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Sharpe (approx.)</div><div class="indicator-cell__value">${s.sharpe_ratio ?? "—"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Trades</div><div class="indicator-cell__value">${s.n_trades}</div></div>
      </div>
      <p class="field-hint">Starting capital: $${res.starting_capital.toLocaleString()} · Final: $${s.final_equity.toLocaleString()} · ${res.n_splits} walk-forward windows · Models: ${res.models_used.join(", ")}</p>
    </div>

    <div class="panel">
      <div class="panel__header"><h2>Equity curve</h2></div>
      <div id="backtestEquityChart" style="height:320px;"></div>
    </div>

    <div class="panel">
      <div class="panel__header"><h2>Recent trades</h2></div>
      <table class="data-table">
        <thead><tr><th>Date</th><th>Direction</th><th>Size</th><th>Actual Move</th><th>Trade P&L</th><th>Correct?</th></tr></thead>
        <tbody>${tradeRows}</tbody>
      </table>
    </div>

    <p class="disclaimer" style="margin-top:14px;">Simulated performance on historical data, including a 0.10% round-trip transaction cost assumption per trade — a reasonable estimate for a liquid US stock, not a live, ticker-specific model. Real trading still involves behavior (slippage on illiquid names, your own timing) this simulation can't fully capture — this is a research tool, not a promise of future results.</p>
  `;

  const dates = res.equity_curve.map((p) => p.date);
  const equity = res.equity_curve.map((p) => p.equity);
  Plotly.newPlot("backtestEquityChart", [{
    x: dates, y: equity, type: "scatter", mode: "lines", line: { color: "#6384FF", width: 2 },
    fill: "tozeroy", fillcolor: "rgba(99, 132, 255, 0.08)",
  }], {
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    margin: { l: 50, r: 20, t: 10, b: 30 },
    xaxis: { color: "#8A93A6", gridcolor: "#232838" },
    yaxis: { color: "#8A93A6", gridcolor: "#232838", title: "Equity ($)" },
    font: { family: "IBM Plex Mono, monospace", size: 11 },
  }, { responsive: true, displayModeBar: false });
}

// ----------------------------------------------------------- settings
async function loadSettingsView() {
  try {
    const settingsData = await apiGet("/settings");
    document.querySelectorAll("#settingsRiskProfileToggle button").forEach((b) => {
      b.classList.toggle("active", b.dataset.risk === settingsData.default_risk_profile);
    });
  } catch { /* keep the default UI state if this fails */ }

  const cacheEl = document.getElementById("cacheStatsResults");
  try {
    const stats = await apiGet("/settings/cache-stats");
    cacheEl.innerHTML = `
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">Cached Tickers</div><div class="indicator-cell__value">${stats.cached_tickers}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Cached Price Rows</div><div class="indicator-cell__value">${stats.cached_price_rows.toLocaleString()}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Cached Fundamentals</div><div class="indicator-cell__value">${stats.cached_fundamentals}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">Cached SEC Filings</div><div class="indicator-cell__value">${stats.cached_sec_filings}</div></div>
      </div>`;
  } catch (e) {
    cacheEl.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }

  const availEl = document.getElementById("settingsModelAvailability");
  try {
    const avail = await apiGet("/models/availability");
    availEl.innerHTML = `
      <div class="prediction-metric-grid">
        <div class="indicator-cell"><div class="indicator-cell__label">Baseline (sklearn)</div><div class="indicator-cell__value ${avail.sklearn_baseline ? "pct-up" : "pct-down"}">${avail.sklearn_baseline ? "Available" : "Unavailable"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">XGBoost</div><div class="indicator-cell__value ${avail.xgboost ? "pct-up" : "pct-down"}">${avail.xgboost ? "Available" : "Unavailable"}</div></div>
        <div class="indicator-cell"><div class="indicator-cell__label">LSTM (PyTorch)</div><div class="indicator-cell__value ${avail.lstm_pytorch ? "pct-up" : "pct-down"}">${avail.lstm_pytorch ? "Available" : "Unavailable"}</div></div>
      </div>
      ${avail.notes.length ? `<p class="field-hint" style="margin-top:8px;">${avail.notes.join(" · ")}</p>` : ""}`;
  } catch (e) {
    availEl.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }

  const schedEl = document.getElementById("settingsSchedulerStatus");
  try {
    const sched = await apiGet("/scheduler/status");
    schedEl.innerHTML = sched.available
      ? `<div class="prediction-metric-grid">
          <div class="indicator-cell"><div class="indicator-cell__label">Status</div><div class="indicator-cell__value ${sched.running ? "pct-up" : "pct-down"}">${sched.running ? "Running" : "Stopped"}</div></div>
          <div class="indicator-cell"><div class="indicator-cell__label">Prediction Checks</div><div class="indicator-cell__value">${sched.run_count}</div></div>
          <div class="indicator-cell"><div class="indicator-cell__label">Alert Checks</div><div class="indicator-cell__value">${sched.alerts.run_count}</div></div>
        </div>`
      : `<p class="empty-state">apscheduler isn't installed — background checks are disabled. Predictions and alerts still work, just require manual "check now" clicks.</p>`;
  } catch (e) {
    schedEl.innerHTML = `<p class="empty-state">Couldn't load: ${e.message}</p>`;
  }

  updateNotificationStatusText();
}

function updateNotificationStatusText() {
  const el = document.getElementById("notificationStatusText");
  const toggle = document.getElementById("notificationsToggle");
  if (!("Notification" in window)) {
    el.textContent = "Your browser doesn't support notifications.";
    toggle.disabled = true;
    return;
  }
  if (Notification.permission === "granted") {
    el.textContent = "Notifications are enabled.";
    toggle.checked = true;
  } else if (Notification.permission === "denied") {
    el.textContent = "Notifications are blocked — enable them in your browser's site settings to turn this on.";
    toggle.checked = false;
    toggle.disabled = true;
  } else {
    el.textContent = "Notifications are off.";
    toggle.checked = false;
  }
}

function initSettingsPage() {
  document.getElementById("settingsRiskProfileToggle").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-risk]");
    if (!btn) return;
    document.querySelectorAll("#settingsRiskProfileToggle button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    try {
      await apiPost(`/settings?key=default_risk_profile&value=${btn.dataset.risk}`);
    } catch { /* the button state already reflects the choice even if the save silently fails */ }
  });

  document.getElementById("clearCacheBtn").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.textContent = "Clearing…";
    try {
      const res = await apiPost("/settings/clear-cache");
      btn.textContent = `Cleared ${res.cleared_rows} rows`;
    } catch {
      btn.textContent = "Clear cached price data";
    }
    setTimeout(() => { btn.textContent = "Clear cached price data"; }, 2500);
    loadSettingsView();
  });

  document.getElementById("notificationsToggle").addEventListener("change", async (e) => {
    if (!("Notification" in window)) return;
    if (e.target.checked) {
      await Notification.requestPermission();
    }
    updateNotificationStatusText();
  });
}

// ----------------------------------------------------------- AI assistant chat
let chatHistory = [];

function initChatPage() {
  const form = document.getElementById("chatForm");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("chatInput");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    await sendChatMessage(message);
  });
}

async function loadChatView() {
  try {
    const status = await apiGet("/chat/status");
    document.getElementById("chatNotConfigured").style.display = status.configured ? "none" : "block";
    document.getElementById("chatInterface").style.display = status.configured ? "block" : "none";
  } catch {
    // if the status check itself fails, just let the form attempt work normally
  }
}

function appendChatBubble(role, text) {
  const container = document.getElementById("chatMessages");
  if (container.querySelector(".empty-state")) container.innerHTML = "";
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble chat-bubble--${role}`;
  bubble.textContent = text;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

async function sendChatMessage(message) {
  appendChatBubble("user", message);
  chatHistory.push({ role: "user", content: message });
  const thinkingBubble = appendChatBubble("assistant", "Thinking…");

  // Attach whichever is more recent — a prediction or a backtest — as
  // context, so questions like "why is this neutral" get a specific
  // answer instead of a generic one. Never sent unless the person has
  // actually generated one of these in this session.
  const context = window.lastPredictionContext || window.lastBacktestContext || null;

  try {
    const data = await apiPostJson("/chat", { messages: chatHistory, context });
    thinkingBubble.textContent = data.reply;
    chatHistory.push({ role: "assistant", content: data.reply });
  } catch (e) {
    thinkingBubble.className = "chat-bubble chat-bubble--error";
    thinkingBubble.textContent = `Couldn't get a response: ${e.message}`;
    chatHistory.pop(); // don't keep a failed exchange in the conversation history sent to the API
  }
}

function initThemeToggle() {
  const btn = document.getElementById("themeToggleBtn");
  const icon = document.getElementById("themeToggleIcon");

  const applyIcon = () => {
    const current = document.documentElement.dataset.theme;
    icon.textContent = current === "light" ? "☀️" : "🌙";
  };
  applyIcon();

  btn.addEventListener("click", () => {
    const current = document.documentElement.dataset.theme;
    const next = current === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (e) {
      // localStorage unavailable (private browsing, etc.) — theme still
      // applies for this session, just won't persist across reloads.
    }
    applyIcon();
  });
}

// ----------------------------------------------------------- boot
document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initThemeToggle();
  initDashboard();
  initDiscoveryModeTabs();
  initSiteMenu();
  initGlobalSearch();
  initCommandPalette();
  initWatchlistForm();
  initAnalyzer();
  initNewsForm();
  initScannerForm();
  initScannerPresets();
  initPredictionsPage();
  initModelsPage();
  initPortfolioForm();
  initAlertsPage();
  initBacktestForm();
  initTCNResearchForm();
  initVolatilityForm();
  initSettingsPage();
  initChatPage();
  loadDashboard();
  refreshAlertBadge();

  // Load the saved default risk profile so Predictions opens with the
  // user's actual preference instead of always defaulting to Moderate.
  apiGet("/settings").then((s) => {
    currentRiskProfile = s.default_risk_profile;
    document.querySelectorAll("#riskProfileToggle button").forEach((b) => {
      b.classList.toggle("active", b.dataset.risk === s.default_risk_profile);
    });
  }).catch(() => { /* keep the hardcoded default if this fails */ });
});
