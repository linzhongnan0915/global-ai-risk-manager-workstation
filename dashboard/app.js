const tabs = [
  "Portfolio Command Center",
  "Strategy Monitor",
  "Daily Performance",
  "Trade Log",
  "Correlation & Diversification",
  "Backtesting & Research Lab",
];

const tabCompactLabels = [
  "Command Center",
  "Strategies",
  "Daily Performance",
  "Trade Log",
  "Correlation",
  "Strategy Detail",
];

const NAV_SECTIONS = [
  { group: "Portfolio", tab: "Portfolio Command Center", label: "Command Center", icon: "portfolio" },
  { group: "Strategies", tab: "Strategy Monitor", label: "Strategies", icon: "line" },
  { group: "Portfolio", tab: "Daily Performance", label: "Daily Performance", icon: "activity" },
  { group: "Operations", tab: "Trade Log", label: "Trade Log", icon: "target" },
  { group: "Risk", tab: "Correlation & Diversification", label: "Correlation", icon: "layers" },
  { group: "Research", tab: "Backtesting & Research Lab", label: "Strategy Detail", icon: "shield" },
];

const fallbackArtifact = {
  as_of_date: "2026-06-04",
  initial_capital: 1000000,
  strategy_count: 0,
  risk_summary: {
    portfolio_sharpe: 0,
    portfolio_volatility: 0,
    portfolio_var_99: 0,
    portfolio_expected_shortfall_95: 0,
    portfolio_max_drawdown: 0,
  },
  portfolio_series: { dates: [], returns: [], cumulative_return: [], drawdown: [] },
  allocation: {
    current_weights: {},
    proposed_weights: {},
    estimated_transaction_cost: 0,
    approval_required: true,
    rationale: "Pending generated artifact.",
  },
  market_monitor: [],
  news_risk: { watch_level: "normal", news_risk_score: 0, items: [] },
  recommendations: [],
  literature_modules: [],
  replication_clone: {},
  literature_strategy_backtests: {},
  strategies: [],
};

function money(value) {
  return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function pct(value, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function num(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : "0.00";
}

function humanize(value, fallback = "Not available") {
  return value ? String(value).replaceAll("_", " ") : fallback;
}

function humanizeFactor(factor, artifact = activeArtifact) {
  const labels = artifact?.factors?.factor_display_labels || {};
  if (labels[factor]) return labels[factor];
  return humanizeMetricLabel(factor, artifact);
}

function operatingMetric(artifact, key) {
  return artifact?.operating_period_risk?.metrics?.[key] || null;
}

function operatingPnlMetric(artifact, key) {
  return artifact?.operating_period_risk?.pnl?.[key] || null;
}

function formatOperatingMetric(metric, { asPct = false, digits = 2 } = {}) {
  if (!metric) return "N/A";
  if (!metric.available || metric.value == null) {
    return `N/A (${metric.observations || 0}/${metric.minimum_observations || "?"} obs)`;
  }
  return asPct ? pct(metric.value, digits) : num(metric.value, digits);
}

function metricNumeric(metric) {
  if (!metric || !metric.available || metric.value == null) return null;
  return Number(metric.value);
}

function canonicalRiskHeadline(artifact = activeArtifact) {
  return artifact?.risk_status_summary?.headline || {};
}

function scopeSummary(artifact, scopeName) {
  return artifact?.risk_status_summary?.scopes?.[scopeName]?.summary || { ok: 0, watch: 0, warning: 0, breach: 0 };
}

function renderTruthDisclosure(artifact = activeArtifact) {
  const disclosure = hasFactoryResearch()
    ? "US-Equity Research Backtest - Research Only - Not live allocation or fills"
    : (artifact?.data_classification?.disclosure
      || "Prototype model portfolio - ETF proxy research data - Not live positions or fills");
  const node = document.getElementById("truthDisclosure");
  if (node) node.textContent = disclosure;
  const build = document.getElementById("buildTrace");
  if (build && artifact?.build_metadata) {
    build.textContent = `Build ${artifact.build_metadata.build_id || "n/a"} - Market as of ${artifact.build_metadata.market_as_of || "n/a"}`;
  }
}

function investmentStart(artifact = activeArtifact) {
  return artifact?.investment_context?.start_date || "2026-06-04";
}

function portfolioSeriesForDisplay(artifact = activeArtifact) {
  const live = artifact?.portfolio_series_live;
  if (live?.dates?.length) return live;
  return artifact?.portfolio_series || {};
}

function riskSummaryForDisplay(artifact = activeArtifact) {
  const operating = artifact?.operating_period_risk?.metrics || {};
  return {
    portfolio_sharpe: metricNumeric(operating.portfolio_sharpe),
    portfolio_volatility: metricNumeric(operating.portfolio_volatility),
    portfolio_var_99: metricNumeric(operating.portfolio_var_99),
    portfolio_expected_shortfall_95: metricNumeric(operating.portfolio_expected_shortfall_95),
    portfolio_max_drawdown: metricNumeric(operating.portfolio_max_drawdown),
  };
}

function historicalResearchRiskSummary(artifact = activeArtifact) {
  return artifact?.historical_research_risk_summary || artifact?.risk_summary || {};
}

function renderFactorExposureBars(containerId, exposure = {}, artifact = activeArtifact) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const entries = Object.entries(exposure || {})
    .map(([factor, value]) => [factor, Number(value)])
    .filter(([, value]) => Number.isFinite(value))
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 8);
  if (!entries.length) {
    el.innerHTML = "<p class='empty-state'>No factor exposure data.</p>";
    return;
  }
  const maxAbs = Math.max(...entries.map(([, value]) => Math.abs(value)), 0.05);
  el.innerHTML = entries.map(([factor, value]) => {
    const width = Math.min(100, Math.abs(value) / maxAbs * 100);
    const title = factor === "cash" ? (artifact?.investment_context?.factor_cash_note || "") : "";
    return `<div class="factor-bar-row" title="${title}">
      <span class="factor-bar-label">${humanizeFactor(factor, artifact)}</span>
      <div class="factor-bar-track"><span class="factor-bar-fill ${value < 0 ? "neg" : ""}" style="width:${width}%"></span></div>
      <strong>${num(value, 3)}</strong>
    </div>`;
  }).join("");
}

function renderFactorNotes(artifact = activeArtifact) {
  const cash = artifact?.factors?.cash_semantics || {};
  const text = [
    cash.note,
    `Treasury-bill / liquidity proxy exposure: ${num(cash.treasury_bill_proxy_exposure, 3)}.`,
    `${cash.residual_cash_display_label || "Unallocated residual cash"}: ${pct(cash.portfolio_residual_cash_weight ?? artifact?.investment_context?.residual_cash_weight ?? 0, 1)}.`,
  ].filter(Boolean).join(" ");
  ["portfolioFactorNote", "riskFactorNote"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  });
}

function redrawAllCharts(artifact = activeArtifact) {
  if (!artifact) return;
  const series = portfolioSeriesForDisplay(artifact);
  const start = investmentStart(artifact);
  const caption = document.getElementById("pnlChartCaption");
  if (caption) caption.textContent = `Operating period since ${start} - Historical research context in Research Lab`;
  drawOperatingPeriodCharts(series);
  renderFactorExposureBars("portfolioFactorBars", artifact.factors?.portfolio_factor_exposure_current, artifact);
  renderFactorExposureBars("riskFactorBars", artifact.factors?.portfolio_factor_exposure_current, artifact);
  renderFactorNotes(artifact);
  if (selectedLiteratureItem?.backtest) {
    if (hasFactoryResearch()) {
      const item = selectedLiteratureItem.strategy_id
        ? selectedLiteratureItem
        : ResearchUniverse.itemById(selectedFactoryResearchId || ResearchUniverse.COMPOSITE_ID);
      if (item) renderFactoryResearchLabPanels(item);
    } else {
      renderResearchLabPanels(selectedLiteratureItem);
    }
  }
  document.querySelectorAll("[data-spark]").forEach((canvas) => {
    if (canvas.__sparkValues) drawSparkline(canvas, canvas.__sparkValues, canvas.__sparkColor || "#1ac8ff");
  });
}

function installChartObservers(artifact) {
  const targets = ["pnlCanvas", "drawdownCanvas", "backtestCanvas"];
  if (typeof ResizeObserver === "undefined") return;
  const observer = new ResizeObserver(debounce(() => redrawAllCharts(artifact), 120));
  targets.forEach((id) => {
    const node = document.getElementById(id);
    if (node) observer.observe(node);
  });
}

function cls(value) {
  return value < 0 ? "negative" : "positive";
}

function icon(name) {
  const paths = {
    portfolio: '<path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 15l3-4 3 2 4-7"/>',
    line: '<path d="M3 17l5-5 4 3 7-9"/><path d="M3 21h18"/>',
    risk: '<path d="M12 3l9 16H3L12 3z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    dollar: '<path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7H14a3.5 3.5 0 0 1 0 7H6"/>',
    shield: '<path d="M12 22s7-4 7-10V5l-7-3-7 3v7c0 6 7 10 7 10z"/>',
    activity: '<path d="M3 12h4l3 7 4-14 3 7h4"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3"/><path d="M12 19v3"/><path d="M2 12h3"/><path d="M19 12h3"/>',
    layers: '<path d="M12 2l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/>',
  };
  return `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.activity}</svg>`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function debounce(fn, waitMs = 300) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), waitMs);
  };
}

async function loadLiveOverlay() {
  const candidates = ["/api/live-summary", "/output/live_overlay.json", "../output/live_overlay.json"];
  for (const path of candidates) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) continue;
      const payload = await response.json();
      if (payload.ok === false) continue;
      return payload;
    } catch {
      continue;
    }
  }
  return null;
}

async function loadShadowLiveBundle() {
  for (const path of ["/dashboard/data/shadow_live_bundle.json", "data/shadow_live_bundle.json"]) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (response.ok) return await response.json();
    } catch {
      continue;
    }
  }
  return null;
}

async function renderShadowStrategyRegistry(status = "ALL") {
  const table = document.getElementById("shadowStrategyTable");
  const heading = table?.closest(".strategy-monitor-panel")?.querySelector(".panel-title");
  if (heading && hasFactoryResearch()) {
    heading.textContent = "US-Equity Research Backtest - Research Only";
  } else if (heading) {
    heading.textContent = "Retained Research / Shadow Registry";
  }
  if (!table) return;
  const shadowRows = activeArtifact?.shadow_live?.strategy_summary || [];
  if (shadowRows.length) {
    const rows = shadowRows.filter((row) => status === "ALL" || status === "RESEARCH_COMPOSITE_MEMBER");
    table.innerHTML = `<tr><th>ID</th><th>Name</th><th>Status</th><th>Sleeve Weight</th><th>Daily PnL</th><th>Cumulative PnL</th><th>Cumulative Return</th><th>Drawdown</th><th>Turnover</th><th>Daily Cost</th><th>Gross / Net Exposure</th><th>Long / Short</th><th>Last Rebalance</th><th>Data</th><th>Action</th></tr>` +
      rows.map((row) => `<tr data-factory-strategy="${escapeHtml(row.strategy_id)}"><td>${escapeHtml(row.strategy_id)}</td><td>${escapeHtml(row.strategy_name)}</td><td>${statusBadge("PROVISIONAL")}</td><td>${pct(row.sleeve_weight, 2)}</td><td class="${cls(row.daily_pnl)}">${money(row.daily_pnl)}</td><td class="${cls(row.cumulative_pnl)}">${money(row.cumulative_pnl)}</td><td>${pct(row.cumulative_return, 2)}</td><td class="negative">${pct(row.current_drawdown, 2)}</td><td>${num(row.turnover, 3)}</td><td>${money(row.transaction_cost)}</td><td>${num(row.gross_exposure, 2)} / ${num(row.net_exposure, 2)}</td><td>${row.long_count} / ${row.short_count}</td><td>${escapeHtml(row.last_rebalance_date || "n/a")}</td><td>${statusBadge(row.data_status)}</td><td><button type="button" class="table-link view-details-link" data-factory-strategy="${escapeHtml(row.strategy_id)}">View Details</button></td></tr>`).join("");
    table.querySelectorAll("[data-factory-strategy]").forEach((row) => row.addEventListener("click", () => openFactoryResearchStrategy(row.dataset.factoryStrategy)));
    return;
  }
  if (hasFactoryResearch()) {
    const rows = ResearchUniverse.strategyRows().filter((row) => {
      if (status === "ALL") return true;
      if (status === "RESEARCH_COMPOSITE" || status === "RESEARCH_COMPOSITE_MEMBER") {
        return row.strategy_id === ResearchUniverse.COMPOSITE_ID || row.research_composite_eligible;
      }
      if (status === "RESEARCH_CANDIDATE") return row.research_group === "REFERENCE";
      return true;
    });
    const renderSection = (label, subset) => {
      if (!subset.length) return "";
      return `<tr class="section-row"><td colspan="14"><strong>${escapeHtml(label)} (${subset.length})</strong></td></tr>` +
        subset.map((row) => `<tr class="factory-research-row${row.strategy_id === selectedFactoryResearchId ? " selected" : ""}" data-factory-strategy="${escapeHtml(row.strategy_id)}" tabindex="0" role="link" aria-label="View details for ${escapeHtml(row.strategy_id)}">
          <td>${escapeHtml(row.strategy_id)}</td>
          <td>${escapeHtml(row.name)}</td>
          <td>${statusBadge(row.membership || row.research_group)}</td>
          <td>${row.research_composite_eligible ? "YES" : row.strategy_id === ResearchUniverse.COMPOSITE_ID ? "COMPOSITE" : "NO"}</td>
          <td>${row.live_allocation_approved ? "YES" : "NO"}</td>
          <td>${pct(row.net_return || 0, 1)}</td>
          <td>${row.sharpe == null ? "N/A" : num(row.sharpe, 3)}</td>
          <td>${pct(row.max_drawdown || 0, 1)}</td>
          <td>${row.turnover == null ? "N/A" : `${num(row.turnover, 3)} avg daily`}</td>
          <td>${row.ic == null ? "N/A" : num(row.ic, 4)}</td>
          <td>${row.decile_spread == null ? "N/A" : num(row.decile_spread, 5)}</td>
          <td class="wrap-cell">${escapeHtml(row.status_reason || "")}</td>
          <td>${escapeHtml(row.latest_data_date || "n/a")}</td>
          <td><button type="button" class="table-link view-details-link" data-factory-strategy="${escapeHtml(row.strategy_id)}">View Details</button></td>
        </tr>`).join("");
    };
    const activeRows = rows.filter((row) => row.research_group === "ACTIVE");
    const repairRows = rows.filter((row) => row.research_group === "REPAIR");
    const dataInsufficientRows = rows.filter((row) => row.research_group === "DATA_INSUFFICIENT");
    const candidateRows = rows.filter((row) => row.research_group === "RESEARCH_CANDIDATE");
    const referenceRows = rows.filter((row) => row.research_group === "REFERENCE");
    const compositeRows = rows.filter((row) => row.strategy_id === ResearchUniverse.COMPOSITE_ID);
    table.innerHTML = `<tr><th>ID</th><th>Name</th><th>Status</th><th>Research Composite</th><th>Live Allocation</th><th>Net Return</th><th>Sharpe</th><th>Max DD</th><th>Turnover (avg daily)</th><th>IC</th><th>Decile Spread</th><th>Reason</th><th>Latest Data</th><th>Action</th></tr>` +
      renderSection("ACTIVE US-Equity Research", activeRows) +
      renderSection("REPAIR", repairRows) +
      renderSection("DATA INSUFFICIENT", dataInsufficientRows) +
      renderSection("RESEARCH CANDIDATE", candidateRows) +
      renderSection("REFERENCE ONLY / ARCHIVED", referenceRows) +
      renderSection("Combined Portfolio", compositeRows);
    table.querySelectorAll("tr[data-factory-strategy]").forEach((row) => {
      const strategyId = row.dataset.factoryStrategy;
      if (!strategyId) return;
      const open = () => openFactoryResearchStrategy(strategyId);
      row.addEventListener("click", (event) => {
        if (event.target.closest("button.view-details-link")) {
          event.preventDefault();
        }
        open();
      });
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
    return;
  }
  try {
    const response = await fetch(`/api/strategy-shadow?status=${encodeURIComponent(status)}`, { cache: "no-store" });
    const payload = await response.json();
    const rows = payload.strategies || [];
    table.innerHTML = `<tr><th>ID</th><th>Name</th><th>Status</th><th>Allocation Eligible</th><th>Net Return</th><th>Sharpe</th><th>Max DD</th><th>Turnover</th><th>IC</th><th>Decile Spread</th><th>Reason</th><th>Latest Data</th></tr>` +
      rows.map((row) => `<tr><td>${escapeHtml(row.strategy_id)}</td><td>${escapeHtml(row.name)}</td><td>${statusBadge(row.status)}</td><td>${row.allocation_eligible ? "YES" : "NO"}</td><td>${pct(row.net_return || 0, 1)}</td><td>${row.sharpe == null ? "N/A" : num(row.sharpe, 3)}</td><td>${pct(row.max_drawdown || 0, 1)}</td><td>${row.turnover == null ? "N/A" : num(row.turnover, 3)}</td><td>${row.ic == null ? "N/A" : num(row.ic, 4)}</td><td>${row.decile_spread == null ? "N/A" : num(row.decile_spread, 5)}</td><td class="wrap-cell">${escapeHtml(row.status_reason)}</td><td>${escapeHtml(row.latest_data_date)}</td></tr>`).join("");
  } catch (error) {
    table.innerHTML = "<tr><td>Shadow registry unavailable.</td></tr>";
  }
}

function mergeLiveOverlay(artifact, overlay) {
  if (!overlay) return artifact;
  artifact.live_data_mode = overlay.data_mode || artifact.live_data_mode || "artifact_static";
  artifact.market_monitor = overlay.market_monitor || artifact.market_monitor;
  artifact.news_risk = overlay.news_risk || artifact.news_risk;
  artifact.recommendations = overlay.recommendations || artifact.recommendations;
  artifact.live_refreshed_at = overlay.refreshed_at;
  artifact.live_market_as_of = overlay.market_as_of;
  artifact.intraday_snapshot_id = overlay.snapshot_id || artifact.intraday_snapshot_id;
  if (overlay.intraday_marks) mergeIntradayMarks(artifact, overlay.intraday_marks);
  if (overlay.factor_exposure_current) {
    artifact.factors = artifact.factors || {};
    artifact.factors.portfolio_factor_exposure_current = overlay.factor_exposure_current;
  }
  return artifact;
}

function mergeShadowLiveBundle(artifact, shadow) {
  if (!shadow) return artifact;
  artifact.portfolio_series_live = shadow.portfolio_series_live;
  artifact.operating_period_risk = shadow.operating_period_risk;
  artifact.initial_capital = shadow.initial_capital;
  artifact.as_of_date = shadow.market_as_of;
  artifact.live_market_as_of = shadow.market_as_of;
  artifact.live_refreshed_at = shadow.refreshed_at;
  artifact.shadow_live = shadow.shadow_live;
  artifact.data_classification = artifact.data_classification || {};
  artifact.data_classification.disclosure = "SHADOW LIVE / PAPER PORTFOLIO - RESEARCH ONLY - LIVE CAPITAL 0% - EXECUTION DISABLED - NO LIVE FILL";
  return artifact;
}

function renderShadowOperationalPanels(artifact) {
  const shadow = artifact?.shadow_live;
  if (!shadow) return;
  const status = document.getElementById("shadowPipelineStatus");
  if (status) {
    const reconciliation = shadow.reconciliation || {};
    const latest = (shadow.portfolio_ledger || []).at(-1);
    const cumulativeCost = (shadow.portfolio_ledger || []).reduce((total, row) => total + (row.transaction_cost || 0), 0);
    const cumulativeGross = (shadow.portfolio_ledger || []).reduce((total, row) => total + (row.gross_pnl || 0), 0);
    const costPctGross = cumulativeGross ? cumulativeCost / Math.abs(cumulativeGross) : null;
    const segments = shadow.segments || {};
    const rawStatus = shadow.runner_mode === "RAW DATA SIGNAL RUNNER"
      ? `<p><strong>RAW DATA SIGNAL RUNNER</strong><br>Configured ${shadow.configured_strategy_count || 16} | success ${shadow.successful_strategy_count || 0} | partial ${shadow.partial_strategy_count || 0} | unavailable ${shadow.unavailable_strategy_count || 0} | latest target ${escapeHtml(shadow.latest_valid_target_position_date || "n/a")} | latest execution ${escapeHtml(shadow.latest_simulated_execution_date || "pending")} | Trade Log rows ${shadow.trade_log_row_count || 0}</p>
        <p><strong>Universes:</strong> entry eligibility ${shadow.entry_eligibility_universe_size || 0} | operational pricing ${shadow.operational_pricing_universe_size || 0} | latest raw data ${escapeHtml(shadow.latest_raw_data_timestamp || "n/a")}</p>
        <p><strong>Segments:</strong> ${escapeHtml(segments.retrospective?.label || "RETROSPECTIVE_PAPER_BACKFILL")} ${escapeHtml(segments.retrospective?.start || "n/a")} to ${escapeHtml(segments.retrospective?.end || "n/a")} | ${escapeHtml(segments.forward_raw?.label || "FORWARD_RAW_SHADOW_LIVE")} ${escapeHtml(segments.forward_raw?.start || "pending")} to ${escapeHtml(segments.forward_raw?.end || "pending")} | transition NAV ${money(segments.transition_nav)}</p>
        <p><strong>Membership timeline:</strong> completed history N=${shadow.previous_active_count || 16} at ${pct(shadow.previous_equal_weight, 2)} | WQ_ALPHA_018 effective ${escapeHtml(shadow.membership_effective_date || "pending")} | approved forward N=${shadow.current_active_count || 17} at ${pct(shadow.current_equal_weight, 2)}</p>`
      : "<p><strong>RETROSPECTIVE_PAPER_BACKFILL</strong> | accepted-series historical reference only.</p>";
    const portfolioSummary = latest
      ? `<p><strong>Portfolio:</strong> continuous NAV ${money(latest.ending_nav)} | gross P&amp;L ${money(cumulativeGross)} | transaction costs ${money(cumulativeCost)} | net P&amp;L ${money(latest.cumulative_pnl)} | cost/gross ${costPctGross == null ? "n/a" : pct(costPctGross, 2)}<br><strong>Allocation:</strong> ACTIVE ${latest.active_count} | equal sleeve ${pct(latest.equal_strategy_weight, 2)} | gross/net exposure ${num(latest.gross_exposure, 2)} / ${num(latest.net_exposure, 2)}</p>`
      : "";
    status.innerHTML = `<p><strong>SHADOW LIVE / PAPER PORTFOLIO</strong><br>Latest completed interval: ${escapeHtml(artifact.live_market_as_of || "n/a")} - last successful run: ${escapeHtml(shadow.last_successful_run || "n/a")} - live capital 0% - execution disabled</p>
      <p><strong>Reconciliation:</strong> ${Object.entries(reconciliation).filter(([, value]) => value === false).length ? "ALERT" : "PASS"} - pending: ${(shadow.pending_intervals || []).join(", ") || "none"}</p>
      ${rawStatus}
      ${portfolioSummary}
      ${(shadow.alerts || []).map((alert) => `<p><strong>${escapeHtml(alert.code)}</strong>: ${escapeHtml(alert.detail)}</p>`).join("")}`;
  }
  const correlation = shadow.correlation || {};
  const correlationStatus = document.getElementById("shadowCorrelationStatus");
  if (correlationStatus) correlationStatus.innerHTML = `<p><strong>${escapeHtml(correlation.status || "NOT ENOUGH LIVE HISTORY")}</strong><br>Observations: ${correlation.observations || 0} - minimum required: ${correlation.minimum_observations || 20}. Research and shadow-live returns are not mixed.</p>`;
  const warningTable = document.getElementById("shadowCorrelationWarnings");
  if (warningTable) warningTable.innerHTML = `<tr><th>Left</th><th>Right</th><th>Correlation</th></tr>${(correlation.warnings || []).map((row) => `<tr><td>${escapeHtml(row.left)}</td><td>${escapeHtml(row.right)}</td><td>${num(row.correlation, 3)}</td></tr>`).join("") || "<tr><td colspan='3'>NOT ENOUGH LIVE HISTORY</td></tr>"}`;
  renderShadowTradeLog();
}

function renderShadowTradeLog() {
  const table = document.getElementById("shadowTradeLogTable");
  if (!table) return;
  const dateFrom = document.getElementById("shadowTradeDateFromFilter")?.value || "";
  const dateTo = document.getElementById("shadowTradeDateToFilter")?.value || "";
  const strategy = (document.getElementById("shadowTradeStrategyFilter")?.value || "").toLowerCase();
  const ticker = (document.getElementById("shadowTradeTickerFilter")?.value || "").toLowerCase();
  const action = document.getElementById("shadowTradeActionFilter")?.value || "";
  const rows = (activeArtifact?.shadow_live?.trades || []).filter((row) => (!dateFrom || row.execution_date >= dateFrom) && (!dateTo || row.execution_date <= dateTo) && (!strategy || row.strategy_id.toLowerCase().includes(strategy)) && (!ticker || row.ticker.toLowerCase().includes(ticker)) && (!action || row.action === action));
  table.innerHTML = `<tr><th>Date</th><th>Strategy</th><th>Ticker</th><th>Action</th><th>Previous</th><th>Target</th><th>Delta</th><th>Quantity / Notional</th><th>Execution Price</th><th>Cost</th><th>Reason</th><th>Fill</th></tr>${rows.map((row) => `<tr><td>${escapeHtml(row.execution_date)}</td><td>${escapeHtml(row.strategy_id)}</td><td>${escapeHtml(row.ticker)}</td><td>${escapeHtml(row.action)}</td><td>${pct(row.previous_weight, 2)}</td><td>${pct(row.target_weight, 2)}</td><td>${pct(row.delta_weight, 2)}</td><td>${num(row.simulated_quantity, 2)} / ${money(row.simulated_notional)}</td><td>${money(row.simulated_execution_price)}</td><td>${money(row.transaction_cost_amount)}</td><td>${escapeHtml(row.trade_reason)}</td><td>NO LIVE FILL</td></tr>`).join("") || "<tr><td colspan='12'>No simulated weight changes in the completed shadow-live interval.</td></tr>"}`;
}

function renderResearchLabShadowDetail(strategyId) {
  const detail = document.getElementById("researchLabShadowDetail");
  if (!detail) return;
  const shadow = activeArtifact?.shadow_live;
  if (!shadow) {
    detail.innerHTML = "<p>Shadow-live operations bundle unavailable.</p>";
    return;
  }
  if (strategyId === ResearchUniverse.COMPOSITE_ID) {
    const latest = (shadow.portfolio_ledger || []).at(-1);
    detail.innerHTML = latest
      ? `<div class="research-summary-strip"><span>Latest NAV <strong>${money(latest.ending_nav)}</strong></span><span>Cumulative P&amp;L <strong>${money(latest.cumulative_pnl)}</strong></span><span>Current DD <strong>${pct(latest.current_drawdown, 2)}</strong></span><span>Completed intervals <strong>${shadow.portfolio_ledger.length}</strong></span></div><p>SHADOW LIVE / PAPER PORTFOLIO - ACTIVE sleeves only - live capital 0% - execution disabled - NO LIVE FILL.</p>`
      : "<p>No completed shadow-live portfolio intervals.</p>";
    return;
  }
  const summary = (shadow.strategy_summary || []).find((row) => row.strategy_id === strategyId);
  const details = shadow.strategy_details?.[strategyId];
  if (!summary) {
    detail.innerHTML = details
      ? `<p><strong>${escapeHtml(details.name)}</strong> | ACTIVE effective ${escapeHtml(details.membership_effective_date)} | RESEARCH ONLY | PROVISIONAL | NO LIVE FILL.</p>
        <p><strong>Formula:</strong> ${escapeHtml(details.formula)}<br><strong>Rationale:</strong> ${escapeHtml(details.rationale)}<br><strong>Limitations:</strong> ${escapeHtml(details.limitations)}</p>
        <p>Historical research: net Sharpe ${num(details.research_metrics?.net_sharpe, 3)} | net return ${pct(details.research_metrics?.net_cumulative_return, 2)} | OOS return ${pct(details.research_metrics?.preliminary_oos_net_return, 2)}. Shadow-live execution remains pending until the effective-date open is available.</p>`
      : "<p>No shadow-live sleeve exists for this non-ACTIVE research strategy.</p>";
    return;
  }
  const holdings = (shadow.holdings || []).filter((row) => row.strategy_id === strategyId);
  const trades = (shadow.trades || []).filter((row) => row.strategy_id === strategyId);
  detail.innerHTML = `<div class="research-summary-strip"><span>Sleeve NAV <strong>${money(summary.ending_sleeve_nav)}</strong></span><span>Cumulative P&amp;L <strong>${money(summary.cumulative_pnl)}</strong></span><span>Current DD <strong>${pct(summary.current_drawdown, 2)}</strong></span><span>Weight <strong>${pct(summary.sleeve_weight, 2)}</strong></span></div>
    <p>Shadow returns only through ${escapeHtml(summary.date)} - ${escapeHtml(summary.record_label)} - live capital 0% - execution disabled - NO LIVE FILL.</p>
    <p>Latest accepted holdings: ${holdings.length}. Simulated weight-change trades: ${trades.length}. Historical holdings reconstruction is not available from the committed bundle.</p>`;
}

function mergeIntradayMarks(artifact, marks) {
  if (!marks) return artifact;
  artifact.intraday_marks = marks;
  artifact.intraday_snapshot_id = marks.snapshot_id || artifact.intraday_snapshot_id;
  artifact.intraday_refresh_status = {
    data_freshness: marks.data_quality?.freshness,
    latest_observation: marks.data_quality?.latest_observation_ts_et,
    refreshed_at: marks.refreshed_at,
    evaluation_metadata: marks.evaluation_metadata,
  };
  if (marks.market_monitor) artifact.market_monitor = marks.market_monitor;
  if (marks.news_risk) artifact.news_risk = marks.news_risk;
  if (marks.recommendations) artifact.recommendations = marks.recommendations;
  if (marks.data_quality) {
    artifact.data_quality = { ...(artifact.data_quality || {}), intraday: marks.data_quality };
  }
  return artifact;
}

function mergeIntradaySnapshot(artifact, snapshot) {
  if (!snapshot?.marks) return artifact;
  mergeIntradayMarks(artifact, snapshot.marks);
  artifact.intraday_snapshot_id = snapshot.snapshot_id;
  artifact.intraday_refresh_status = {
    ...(artifact.intraday_refresh_status || {}),
    snapshot_id: snapshot.snapshot_id,
    refresh_completed_at: snapshot.refresh_completed_at,
    latest_observation: snapshot.latest_observation_ts_et,
    market_status: snapshot.market_session_status,
    refresh_status: snapshot.refresh_status,
    ticker_count_requested: snapshot.ticker_count_requested,
    ticker_count_successful: snapshot.ticker_count_successful,
    failed_ticker_count: (snapshot.missing_tickers || []).length,
    missing_tickers: snapshot.missing_tickers || [],
    shadow_intraday: snapshot.shadow_intraday,
    intraday_data_label: snapshot.intraday_data_label,
  };
  return artifact;
}

function renderLiveDataState(artifact) {
  renderIntradayRefreshStrip(artifact);
  renderTruthDisclosure(artifact);
}

function renderIntradayRefreshStrip(artifact) {
  const strip = document.getElementById("intradayRefreshStrip");
  if (!strip) return;
  const monitoring = formatMonitoringState(artifact);
  const status = artifact.intraday_refresh_status || {};
  const meta = artifact.build_metadata || {};
  const marketAsOf = meta.market_as_of || artifact.as_of_date;
  const cadence = status.selected_cadence_minutes || status.refresh_cadence_minutes || selectedIntradayCadence || 5;
  const lastRefresh = status.last_successful_refresh_at || status.refresh_completed_at || artifact.live_refreshed_at;
  const latestBar = status.latest_completed_market_bar_at || status.latest_market_observation_at || status.latest_observation || artifact.live_market_as_of;
  const nextRefresh = status.next_scheduled_refresh_at;
  const schedulerState = status.scheduler_state || status.refresh_state || monitoring.schedulerLabel || "idle";
  const freshness = status.data_freshness || status.canonical_data_state || monitoring.stripDataState;
  const schedulerDisplay = status.scheduler_display || status.scheduler_label || monitoring.schedulerLabel || schedulerState;
  const requested = status.ticker_count_requested;
  const successful = status.ticker_count_successful;
  const failed = status.failed_ticker_count ?? ((status.missing_tickers || []).length);
  const shadowRows = status.shadow_intraday?.strategies || artifact.intraday_marks?.shadow_intraday?.strategies || [];
  const compositeShadow = shadowRows.find((row) => row.strategy_id === "STRATEGY_21_RESEARCH_COMPOSITE_V1");
  const incomplete = shadowRows.filter((row) => row.available === false);
  const coverageWarning = incomplete.length
    ? `<span class="negative">Incomplete <strong>${incomplete.map((row) => `${escapeHtml(row.strategy_id)}: ${(row.missing_tickers || []).join(", ") || "no valid marks"}; uncovered ${pct(row.uncovered_gross_weight || 0, 2)}`).join(" | ")}</strong></span>`
    : "";
  const warning = status.last_error ? `<span class="negative">Refresh warning <strong>${escapeHtml(status.last_error)}</strong></span>` : "";
  strip.innerHTML = `
    <span>Market <strong>${monitoring.headerMarket}</strong></span>
    <span>Monitoring <strong class="${monitoring.tone || ""}">${monitoring.stripMonitoring}</strong></span>
    <span>Cadence <strong>${cadence}m</strong></span>
    <span>Scheduler <strong>${escapeHtml(String(schedulerDisplay))}</strong></span>
    <span>Freshness <strong class="${monitoring.tone || ""}">${escapeHtml(String(freshness))}</strong></span>
    <span>Last refresh <strong>${formatTimestamp(lastRefresh)}</strong></span>
    <span>Latest bar <strong>${formatTimestamp(latestBar)}</strong></span>
    <span>Next refresh <strong>${formatTimestamp(nextRefresh)}</strong></span>
    <span>Coverage <strong>${successful ?? "n/a"}/${requested ?? "n/a"}</strong></span>
    <span>Failed <strong>${failed ?? "n/a"}</strong></span>
    <span>Shadow PnL <strong>${compositeShadow?.estimated_pnl == null ? "n/a" : money(compositeShadow.estimated_pnl)}</strong></span>
    <span>Label <strong>INTRADAY_SHADOW_ESTIMATE - delayed/best-effort</strong></span>
    ${warning}
    ${coverageWarning}
    <span class="muted-copy">${monitoring.detail} - Snapshot ${artifact.intraday_snapshot_id || status.snapshot_id || "daily artifact"} - Proxy as-of ${marketAsOf}</span>`;
}

function formatTimestamp(value) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", month: "short", day: "numeric" });
}

function renderNewsRiskSummary(newsRisk = {}) {
  const el = document.getElementById("newsRiskSummary");
  if (!el) return;
  const items = newsRisk.items || [];
  const material = items.filter((item) => item.human_review || ["high", "medium"].includes(String(item.severity || "").toLowerCase()));
  const urgent = material.length > 0 && material.some((item) => item.portfolio_mapped || item.affected_strategies?.length);
  const watch = urgent ? "urgent review" : items.length ? "monitor" : "normal";
  const sourceLabel = newsRisk.source?.includes("fallback") || newsRisk.source?.includes("proxy")
    ? "Sample / proxy headline feed"
    : (newsRisk.source || "yfinance / market-move proxy");
  el.innerHTML = `
    <p>${statusBadge(watch)} News risk score <strong>${newsRisk.news_risk_score || 0}</strong> - ${items.length} headline(s) - ${escapeHtml(sourceLabel)}</p>
    ${items.slice(0, 3).map((item) => `<p><strong>${escapeHtml(item.headline)}</strong><br><span class="muted-copy">${escapeHtml(item.risk_interpretation || item.topic || "")}</span></p>`).join("") || "<p class='empty-state'>No live news items loaded.</p>"}`;
}

function renderRecommendationPanels(recs = [], artifact = activeArtifact) {
  const recHtml = recs.map((rec) => `<p>${statusBadge(rec.priority)} <strong>${escapeHtml(humanizeUserFacingText(rec.action, artifact))}</strong><br>${escapeHtml(humanizeUserFacingText(rec.rationale, artifact))}</p>`).join("") || emptyState("No recommendations.");
  const list = document.getElementById("recommendationList");
  if (list) list.innerHTML = recHtml;
  const reportList = document.getElementById("reportRecommendationList");
  if (reportList) reportList.innerHTML = recHtml;
}

async function refreshLiveDataFromServer(artifact) {
  const button = document.getElementById("refreshLiveData");
  if (button) {
    button.disabled = true;
    button.textContent = "Refreshing proxy data…";
  }
  renderIntradayRefreshStrip({ ...artifact, intraday_refresh_status: { ...(artifact.intraday_refresh_status || {}), refresh_state: "refreshing", in_progress: true, scheduler_state: "refreshing" } });
  try {
    const response = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval_minutes: selectedIntradayCadence }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "refresh failed");
    mergeLiveOverlay(artifact, payload);
    if (payload.snapshot_id) artifact.intraday_snapshot_id = payload.snapshot_id;
    applyIntradayUiRefresh(artifact);
    if (button) button.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    if (button) button.textContent = "Refresh failed";
    const strip = document.getElementById("intradayRefreshStrip");
    if (strip) strip.insertAdjacentHTML("beforeend", `<span class="negative">Error: ${escapeHtml(error.message)}</span>`);
  } finally {
    if (button) button.disabled = false;
  }
}

function applyIntradayUiRefresh(artifact) {
  renderTopHeader(artifact);
  renderLiveDataState(artifact);
  renderNewsRiskSummary(artifact.news_risk);
  renderRecommendationPanels(artifact.recommendations);
  renderKpis(artifact);
  renderStaticTables(artifact);
  redrawAllCharts(artifact);
}

let intradayPollTimer = null;
let lastSeenSnapshotId = null;
let selectedIntradayCadence = 5;

function syncCadenceSelector(minutes) {
  selectedIntradayCadence = Number(minutes) || 5;
  const select = document.getElementById("intradayCadenceSelect");
  if (select && String(select.value) !== String(selectedIntradayCadence)) {
    select.value = String(selectedIntradayCadence);
  }
}

async function setIntradayCadence(minutes, artifact) {
  syncCadenceSelector(minutes);
  try {
    const response = await fetch("/api/refresh/cadence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval_minutes: selectedIntradayCadence }),
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "cadence update failed");
    artifact.intraday_refresh_status = { ...(artifact.intraday_refresh_status || {}), ...payload };
    renderIntradayRefreshStrip(artifact);
    renderTopHeader(artifact);
  } catch (error) {
    const strip = document.getElementById("intradayRefreshStrip");
    if (strip) strip.insertAdjacentHTML("beforeend", `<span class="negative">Cadence error: ${escapeHtml(error.message)}</span>`);
  }
}

async function pollIntradayRefreshStatus(artifact) {
  try {
    const response = await fetch(`/api/refresh/status?interval_minutes=${selectedIntradayCadence}`, { cache: "no-store" });
    if (!response.ok) throw new Error("status unavailable");
    const status = await response.json();
    intradayMonitoringOffline = false;
    setWorkstationMonitoring(true, false);
    syncCadenceSelector(status.selected_cadence_minutes || status.refresh_cadence_minutes || selectedIntradayCadence);
    artifact.intraday_refresh_status = { ...(artifact.intraday_refresh_status || {}), ...status, monitoring_offline: false, ok: true };
    renderIntradayRefreshStrip(artifact);
    renderTopHeader(artifact);
    const snapshotId = status.snapshot_id;
    if (snapshotId && snapshotId !== lastSeenSnapshotId) {
      const snapResponse = await fetch("/api/snapshot/latest", { cache: "no-store" });
      if (snapResponse.ok) {
        const snapshot = await snapResponse.json();
        if (snapshot.ok !== false) {
          mergeIntradaySnapshot(artifact, snapshot);
          lastSeenSnapshotId = snapshotId;
          applyIntradayUiRefresh(artifact);
        }
      }
    }
  } catch {
    intradayMonitoringOffline = true;
    setWorkstationMonitoring(false, false);
    artifact.intraday_refresh_status = {
      ...(artifact.intraday_refresh_status || {}),
      monitoring_offline: true,
      ok: false,
    };
    renderIntradayRefreshStrip(artifact);
    renderTopHeader(artifact);
  }
}

function installIntradayPolling(artifact) {
  if (intradayPollTimer) clearInterval(intradayPollTimer);
  lastSeenSnapshotId = artifact.intraday_snapshot_id || null;
  syncCadenceSelector(artifact.intraday_refresh_status?.selected_cadence_minutes || artifact.intraday_refresh_status?.refresh_cadence_minutes || 5);
  pollIntradayRefreshStatus(artifact);
  intradayPollTimer = setInterval(() => pollIntradayRefreshStatus(artifact), 45_000);
}

function installLiveControls(artifact) {
  const button = document.getElementById("refreshLiveData");
  const cadenceSelect = document.getElementById("intradayCadenceSelect");
  if (cadenceSelect) {
    cadenceSelect.addEventListener("change", () => setIntradayCadence(cadenceSelect.value, artifact));
  }
  if (!button) return;
  button.addEventListener("click", () => refreshLiveDataFromServer(artifact));
}

let riskActionFilter = "current_model";
let reportFrozenAt = null;
let intradayMonitoringOffline = false;
let activeArtifact = null;
let activeDrawerView = "overview";
const proposalSession = {
  weights: {},
  simulation: null,
  source: "current",
};

function initProposalSession(artifact) {
  proposalSession.weights = Object.fromEntries(
    (artifact.strategies || []).map((strategy) => [strategy.strategy_id, strategy.current_weight || 0]),
  );
  proposalSession.simulation = null;
  proposalSession.source = "current";
}

function loadSystemProposalSession(artifact) {
  proposalSession.weights = Object.fromEntries(
    (artifact.strategies || []).map((strategy) => [strategy.strategy_id, strategy.proposed_weight || 0]),
  );
  proposalSession.simulation = null;
  proposalSession.source = "system";
}

function invalidateProposalSimulation() {
  proposalSession.simulation = null;
}

function sessionProposedWeight(strategyId, fallback = 0) {
  return proposalSession.weights[strategyId] ?? fallback;
}

function refreshProposalStatusViews(artifact) {
  renderAllocationEditor(artifact);
  renderSimulationResult(artifact);
  renderAllocationBeforeAfterStrip(artifact);
  renderApprovalStatusBar(artifact);
  renderAllocationAnalysisPanels(artifact);
  renderAllocationPersistentChecks(artifact);
  renderDecisionStatusLines(artifact);
  renderRebalancePreview(artifact);
  renderDailyReport(artifact);
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  const statusEl = document.getElementById("decisionAuthorityStatus");
  if (statusEl) {
    if (proposal.status === "No rebalance proposed") {
      statusEl.textContent = "No allocation change from current weights. Simulation not required.";
    } else if (proposal.status === "Simulation required") {
      statusEl.textContent = "Proposed weights differ from current allocation. Run simulation before recording a decision.";
    } else if (!proposalSession.simulation) {
      statusEl.textContent = "Human approval does not authorize execution. Simulate proposal before recording a decision.";
    }
  }
}

async function probeWorkstationApi() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    setWorkstationMonitoring(response.ok, false);
    return response.ok;
  } catch {
    setWorkstationMonitoring(false, true);
    return false;
  }
}

let localDecisionEvents = [];
let monitorSort = { key: "daily_pnl", direction: "desc" };
let simulationApiAvailable = null;
let selectedLiteratureItem = null;
let correlationUniverse = "allocated";

const strategyCandidateShelf = [
  ["WQ Multi-Alpha ETF Basket", "101 Alphas", "SPY/QQQ/IWM/QUAL/VLUE/MTUM/USMV", "Ranked price-volume alpha blend", "Crowding, turnover, style reversal", "Prototype running"],
  ["Hedge Fund Factor Clone", "Replication", "SPY/IEF/HYG/UUP/DBC/VIX", "Rolling factor regression", "Clone gap, beta concentration", "Prototype running"],
  ["Business Cycle Allocation", "Macro Regime", "SPY/HYG/IEF/BIL/DBC/UUP", "Growth and inflation phase map", "Regime lag, whipsaw", "Prototype running"],
  ["High-Vol Defensive Switch", "Markov Regime", "SPY/USMV/IEF/BIL/HYG", "Volatility and drawdown stress state", "Late de-risking, false stress", "Prototype running"],
  ["Managed Futures Trend Proxy", "Replication/CTA", "SPY/TLT/GLD/DBC/UUP/DBMF", "Cross-asset 63D trend", "Whipsaw, trend reversal", "Prototype running"],
  ["Credit Carry With Stress Gate", "Replication/Macro", "HYG/LQD/BIL/IEF", "Carry when credit regime supportive", "Spread widening, liquidity shock", "Next build"],
  ["Rates Duration Regime", "Business Cycle", "SHY/IEF/TLT/TIP/BIL", "Duration tilt by growth and inflation", "Inflation shock, curve bear steepening", "Next build"],
  ["USD Macro Pressure Sleeve", "JPM Regime", "UUP/FXE/FXY/GLD/BIL", "USD trend and risk-off pressure", "FX policy shock", "Candidate"],
  ["Commodity Inflation Shock", "Business Cycle", "DBC/USO/GLD/UUP/BIL", "Inflation acceleration proxy", "Roll drag, supply reversal", "Candidate"],
  ["Merger Arb Proxy", "Replication/Event", "MNA/BIL/SPY", "Deal-risk ETF proxy with beta filter", "Deal break, event beta", "Candidate"],
  ["Convertible Arb Proxy", "Replication", "CWB/HYG/IEF/SPY", "Credit-equity-vol proxy basket", "Credit stress, vol shock", "Candidate"],
  ["Tail Hedge Crisis Sleeve", "Markov Regime", "VIX/TLT/GLD/BIL", "High-vol activation", "Premium bleed, timing error", "Candidate"],
  ["Quality Value Momentum Rotation", "101 Alphas/Factors", "QUAL/VLUE/MTUM/USMV/SPY", "Style factor rotation", "Factor crash, crowding", "Candidate"],
  ["Risk Parity ETF Overlay", "Regime Allocation", "SPY/TLT/GLD/DBC/BIL", "Vol-scaled cross-asset allocation", "Correlation breakdown", "Candidate"],
];

async function loadArtifact() {
  const candidates = [
    "/api/artifact/bootstrap",
    "/output/dashboard_artifact.json",
    "../output/dashboard_artifact.json",
  ];
  for (const path of candidates) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) continue;
      return await response.json();
    } catch {
      continue;
    }
  }
  return fallbackArtifact;
}

let researchExtensionPromise = null;
let factoryResearchBundle = null;
let selectedFactoryResearchId = null;

async function loadUsEquityResearchBundle() {
  const candidates = [
    "data/us_equity_research_bundle.json",
    "/dashboard/data/us_equity_research_bundle.json",
    "../dashboard/data/us_equity_research_bundle.json",
  ];
  for (const path of candidates) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) continue;
      const payload = await response.json();
      if (payload?.factory_strategy_research?.results?.length) return payload;
    } catch {
      continue;
    }
  }
  return null;
}

function hasFactoryResearch() {
  return Boolean(factoryResearchBundle?.factory_strategy_research?.results?.length);
}

function hydrateFactoryResearch(artifact) {
  if (!hasFactoryResearch()) return artifact;
  ResearchUniverse.hydrate(factoryResearchBundle.factory_strategy_research, artifact);
  artifact.factory_strategy_research = factoryResearchBundle.factory_strategy_research;
  artifact.us_equity_research = ResearchUniverse.architecture();
  return artifact;
}

function factoryResearchCatalogItems() {
  return factoryResearchBundle?.factory_strategy_research?.results || [];
}

function renderFactoryResearchArchitectureBanner() {
  if (!hasFactoryResearch()) return;
  const arch = ResearchUniverse.architecture();
  const counts = ResearchUniverse.counts();
  const composite = compositeDynamicSummary();
  const el = document.getElementById("historicalResearchContext");
  if (el) {
    el.innerHTML = `
      <div class="research-context-banner">
        <strong>US-Equity Research Platform - Dynamic Combined Portfolio</strong>
        <span>${escapeHtml(composite.headline)}</span>
        <span>Current eligible ACTIVE strategies: <strong>${arch.eligible_active_count}</strong> - Combined Portfolio constituents: <strong>${arch.composite_constituent_count}</strong> - Equal-weight baseline: <strong>${arch.equal_weight_formula}</strong> - Current weight per strategy: <strong>${composite.weightPct}%</strong></span>
        <span class="status-muted">${escapeHtml(composite.expansionNote)} Legacy ETF proxy references are retained for comparison only.</span>
      </div>`;
  }
  const summary = document.getElementById("monitorSummary");
  if (summary) {
    summary.innerHTML = `
      <span><strong>${counts.active}</strong> ACTIVE</span>
      <span><strong>${counts.repair}</strong> REPAIR</span>
      <span><strong>${counts.data_insufficient}</strong> DATA_INSUFFICIENT</span>
      <span><strong>${counts.research_candidate}</strong> RESEARCH_CANDIDATE</span>
      <span><strong>${counts.reference}</strong> REFERENCE_ONLY / ARCHIVED</span>
      <span><strong>${counts.composite}</strong> Combined Portfolio</span>
      <span>${arch.composite_constituent_count} × ${composite.weightPct}% - Dynamic membership: ${composite.dynamicMembership ? "Enabled" : "Disabled"}</span>`;
  }
}

function scrollResearchLabToTop() {
  const anchor = document.getElementById("researchLabDetailAnchor")
    || document.getElementById("researchLabOverview")
    || document.querySelector('[data-tab-panel="Backtesting & Research Lab"]');
  anchor?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function setResearchNotice(elementId, message) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (message) {
    el.textContent = message;
    el.hidden = false;
  } else {
    el.textContent = "";
    el.hidden = true;
  }
}

function factoryResearchStatusLabel(backtest = {}, strategyId = "") {
  if (strategyId === ResearchUniverse.COMPOSITE_ID) return "COMPOSITE";
  const membership = backtest.factory_research?.membership;
  if (membership === "ACTIVE") return "ACTIVE";
  if (membership === "REFERENCE_ONLY") return "REFERENCE_ONLY";
  return membership || backtest.lifecycle_status || "REFERENCE_ONLY";
}

function compositeConstituentIds(backtest = {}) {
  const meta = backtest.factory_research?.combined_portfolio || {};
  const fromMeta = meta.eligible_member_ids || meta.constituent_ids;
  if (fromMeta?.length) return [...fromMeta].sort();
  const fromRows = (meta.current_constituents || meta.members || []).map((row) => row.strategy_id).filter(Boolean);
  if (fromRows.length) return fromRows.sort();
  return ResearchUniverse.activeUnderlyingIds();
}

function compositeDynamicSummary() {
  return ResearchUniverse.compositeMembershipSummary();
}

function buildUnderlyingOverviewFields(item) {
  const backtest = item.backtest || {};
  const logic = factoryResearchLogicFields(backtest);
  const factory = backtest.factory_research || {};
  return [
    ["Strategy ID", item.strategy_id],
    ["Strategy Name", backtest.name],
    ["Status", factoryResearchStatusLabel(backtest, item.strategy_id)],
    ["Economic Hypothesis", logic.economicHypothesis, true],
    ["Signal Definition", logic.signalDefinition, true],
    ["Long Rule", logic.longRule],
    ["Short Rule", logic.shortRule],
    ["Rebalance Frequency", logic.rebalanceFrequency],
    ["Execution Timing", logic.executionTiming],
    ["Universe", logic.universe, true],
    ["Backtest Period", factoryResearchBacktestDates(item), true],
    ["Limitations", (factory.limitations || []).join("; ") || "See research evidence.", true],
    ["Regime Diagnostic", factory.regime_disclosure || "Not available.", true],
  ];
}

function buildCompositeOverviewFields(item) {
  const backtest = item.backtest || {};
  const arch = ResearchUniverse.architecture();
  const composite = compositeDynamicSummary();
  const turnover = backtest.turnover || {};
  const ids = compositeConstituentIds(backtest);
  return [
    ["Strategy ID", item.strategy_id],
    ["Strategy Name", backtest.name],
    ["Status", "COMPOSITE"],
    ["Membership Rule", composite.headline, true],
    ["Current Eligible ACTIVE Strategies", String(arch.eligible_active_count)],
    ["Combined Portfolio Constituents", String(arch.composite_constituent_count)],
    ["Equal-Weight Formula", arch.equal_weight_formula],
    ["Current Weight per Strategy", `${composite.weightPct}%`],
    ["Dynamic Membership", composite.dynamicMembership ? "Enabled" : "Disabled"],
    ["Research Status", "Research only - not allocation approved", true],
    ["Gross Return", formatMetricNa(backtest.gross_metrics?.cumulative_return, (v) => pct(v, 1))],
    ["Net Return", formatMetricNa(backtest.net_metrics?.cumulative_return, (v) => pct(v, 1))],
    ["Sharpe", formatMetricNa(backtest.net_metrics?.sharpe, (v) => num(v, 3))],
    ["Max Drawdown", formatMetricNa(backtest.net_metrics?.max_drawdown, (v) => pct(v, 1))],
    ["Cost Drag", formatCostDragRatio(turnover.total_cost_drag)],
    ["Backtest Period", factoryResearchBacktestDates(item), true],
    ["Constituent IDs", ids.join(", ") || "Bundle field combined_portfolio.eligible_member_ids not populated.", true],
    ["Expansion Note", composite.expansionNote, true],
  ];
}

function renderOverviewFields(fields) {
  return fields.map(([label, value, span]) => renderOverviewField(label, value, Boolean(span))).join("");
}

function openFactoryResearchStrategy(strategyId) {
  if (!hasFactoryResearch()) return;
  selectedFactoryResearchId = strategyId;
  const item = ResearchUniverse.itemById(strategyId);
  if (!item) return;
  setActiveTab("Backtesting & Research Lab");
  renderFactoryResearchLabPanels(item);
  renderShadowStrategyRegistry(document.getElementById("shadowStrategyStatusFilter")?.value || "ALL");
  requestAnimationFrame(() => {
    scrollResearchLabToTop();
    redrawAllCharts(activeArtifact);
  });
}

function formatMetricNa(value, formatter) {
  if (value == null || !Number.isFinite(Number(value))) return "N/A";
  return formatter(Number(value));
}

function formatDailyTurnover(value) {
  return formatMetricNa(value, (v) => `${num(v, 3)} avg daily`);
}

function formatAnnualizedTurnover(value) {
  return formatMetricNa(value, (v) => `${num(v, 1)}x annualized`);
}

function formatCostDragRatio(value) {
  return formatMetricNa(value, (v) => pct(v, 2));
}

function factoryResearchSharedDates() {
  return factoryResearchBundle?.shared_dates || [];
}

function resolveFactoryResearchSeries(item) {
  const backtest = item?.backtest || {};
  const series = backtest.return_series || {};
  const gross = series.gross_returns || [];
  const net = series.net_returns || [];
  const sharedDates = factoryResearchSharedDates();
  const dates = series.dates?.length ? series.dates : sharedDates;
  const length = Math.min(gross.length, net.length, dates.length || gross.length || net.length);
  const missingFields = [];
  if (!gross.length) missingFields.push("return_series.gross_returns");
  if (!net.length) missingFields.push("return_series.net_returns");
  if (!series.dates?.length && !sharedDates.length && (gross.length || net.length)) {
    missingFields.push("shared_dates");
  }
  if (!length) {
    return {
      dates: [],
      gross: [],
      net: [],
      start: backtest.test_period_start || backtest.latest_data_date,
      end: backtest.test_period_end || backtest.latest_data_date,
      missingMessage: missingFields.length
        ? `Bundle field for gross/net series not mapped yet: ${missingFields.join(", ")}.`
        : "Bundle field for gross/net series not mapped yet: return_series.",
    };
  }
  return {
    dates: (dates.length ? dates : sharedDates).slice(0, length),
    gross: gross.slice(0, length),
    net: net.slice(0, length),
    start: backtest.test_period_start || backtest.latest_data_date,
    end: backtest.test_period_end || backtest.latest_data_date,
    missingMessage: "",
  };
}

function factoryResearchBacktestDates(item) {
  const resolved = resolveFactoryResearchSeries(item);
  if (resolved.start && resolved.end) return `${resolved.start} to ${resolved.end}`;
  if (resolved.dates.length) return `${resolved.dates[0]} to ${resolved.dates.at(-1)}`;
  return "N/A";
}

function factoryResearchMembershipLabel(backtest = {}) {
  return backtest.factory_research?.membership || backtest.lifecycle_status || "REFERENCE_ONLY";
}

function factoryResearchLogicFields(backtest = {}) {
  const logic = backtest.factory_research?.logic || {};
  return {
    economicHypothesis: logic.economic_hypothesis || backtest.hypothesis || "N/A",
    signalDefinition: backtest.signal_summary || logic.expected_return_driver || logic.signal_inputs || "N/A",
    longRule: logic.long_leg || "N/A",
    shortRule: logic.short_leg || "N/A",
    rebalanceFrequency: backtest.rebalance || logic.rebalance_frequency || "N/A",
    executionTiming: logic.execution_timing || "N/A",
    universe: backtest.universe || "N/A",
  };
}

function renderOverviewField(label, value, span = false) {
  return `<p class="research-overview-item${span ? " research-overview-span" : ""}"><strong>${escapeHtml(label)}</strong>${escapeHtml(value || "N/A")}</p>`;
}

function renderFactoryResearchOverview(item) {
  const overview = document.getElementById("researchLabOverview");
  if (!overview || !item?.backtest) return;
  const isComposite = item.strategy_id === ResearchUniverse.COMPOSITE_ID;
  overview.innerHTML = renderOverviewFields(
    isComposite ? buildCompositeOverviewFields(item) : buildUnderlyingOverviewFields(item),
  );
}

function renderFactoryResearchMainPanel(item, resolved) {
  const chartSection = document.getElementById("researchLabChartSection");
  const mainDetail = document.getElementById("researchLabMainDetail");
  const hasSeries = Boolean(resolved.gross.length && resolved.net.length);
  if (hasSeries) {
    if (chartSection) chartSection.hidden = false;
    if (mainDetail) {
      mainDetail.hidden = true;
      mainDetail.innerHTML = "";
    }
    setResearchNotice(
      "researchLabChartNotice",
      "",
    );
    return;
  }
  if (chartSection) chartSection.hidden = true;
  if (mainDetail) {
    mainDetail.hidden = false;
    const isComposite = item.strategy_id === ResearchUniverse.COMPOSITE_ID;
    mainDetail.innerHTML = `
      <div class="panel-title sub">Structured Strategy Overview</div>
      <div class="research-overview-grid">
        ${renderOverviewFields(isComposite ? buildCompositeOverviewFields(item) : buildUnderlyingOverviewFields(item))}
      </div>`;
  }
  const missing = resolved.missingMessage
    || "Bundle field for gross/net series not mapped yet: return_series.gross_returns, return_series.net_returns.";
  setResearchNotice(
    "researchLabChartNotice",
    `${missing} This strategy currently has summary/risk data only; holdings and risk charts are shown below.`,
  );
}

function renderHoldingsTable(title, rows) {
  if (!rows.length) {
    return `<div><div class="panel-title sub">${escapeHtml(title)}</div><p class="status-muted">No ${escapeHtml(title.toLowerCase())} available in bundle.</p></div>`;
  }
  return `
    <div>
      <div class="panel-title sub">${escapeHtml(title)}</div>
      <div class="table-viewport short"><div class="table-scroll">
        <table class="data-table dense research-holdings-table">
          <tr><th>Ticker</th><th>Side</th><th>Weight</th></tr>
          ${rows.map((row) => `<tr>
            <td>${escapeHtml(row.ticker || "N/A")}</td>
            <td>${escapeHtml(row.side || "N/A")}</td>
            <td>${row.weight == null ? "N/A" : `${(Number(row.weight) * 100).toFixed(2)}%`}</td>
          </tr>`).join("")}
        </table>
      </div></div>
    </div>`;
}

function renderFactoryResearchHoldings(backtest, isComposite = false) {
  const panel = document.getElementById("researchLabHoldingsPanel");
  const compositePanel = document.getElementById("researchLabCompositePanel");
  const el = document.getElementById("researchLabHoldings");
  if (isComposite) {
    if (panel) panel.hidden = true;
    if (el) el.innerHTML = "";
    return;
  }
  if (panel) panel.hidden = false;
  if (compositePanel) compositePanel.hidden = true;
  if (!el) return;
  const holdings = backtest?.holdings;
  if (!holdings) {
    el.innerHTML = `<p class="research-notice">Current holdings unavailable: bundle field <strong>holdings</strong> is missing for this strategy. Summary metrics and risk charts above are still loaded from the research bundle.</p>`;
    return;
  }
  const longRows = (holdings.current_long_holdings || []).map((row) => ({ ...row, side: "long" }));
  const shortRows = (holdings.current_short_holdings || []).map((row) => ({ ...row, side: "short" }));
  const tradeLog = backtest.factory_research?.simulated_trade_log;
  const tradeLogHtml = tradeLog ? `
    <div class="panel-title sub">Simulated Trade Log</div>
    <p class="status-muted">${escapeHtml(tradeLog.status || "RESEARCH ONLY")} - execution enabled: <strong>${tradeLog.execution_enabled ? "YES" : "NO"}</strong> - records: <strong>${tradeLog.record_count || 0}</strong> - estimated cost: <strong>${pct(tradeLog.estimated_transaction_cost || 0, 2)}</strong></p>
    <div class="table-viewport short"><div class="table-scroll"><table class="data-table dense">
      <tr><th>Execution Date</th><th>Ticker</th><th>Action</th><th>Target Weight</th><th>Simulated Price</th><th>Estimated Cost</th></tr>
      ${(tradeLog.latest_records || []).map((row) => `<tr>
        <td>${escapeHtml(row.execution_date || "N/A")}</td>
        <td>${escapeHtml(row.ticker || "N/A")}</td>
        <td>${escapeHtml(row.action || "N/A")}</td>
        <td>${row.target_weight == null ? "N/A" : pct(row.target_weight, 2)}</td>
        <td>${row.simulated_execution_price == null ? "N/A" : num(row.simulated_execution_price, 2)}</td>
        <td>${row.estimated_transaction_cost == null ? "N/A" : pct(row.estimated_transaction_cost, 4)}</td>
      </tr>`).join("")}
    </table></div></div>` : "";
  if (!longRows.length && !shortRows.length) {
    el.innerHTML = `<p class="research-notice">Holdings object present but both <strong>holdings.current_long_holdings</strong> and <strong>holdings.current_short_holdings</strong> are empty.</p>`;
    return;
  }
  el.innerHTML = `
    <p class="status-muted">Last rebalance: <strong>${escapeHtml(holdings.last_rebalance_date || "N/A")}</strong></p>
    <div class="research-holdings-split">
      ${renderHoldingsTable("Current Long Holdings", longRows)}
      ${renderHoldingsTable("Current Short Holdings", shortRows)}
    </div>
    ${tradeLogHtml}`;
}

function renderFactoryResearchCompositeDetail(item) {
  const panel = document.getElementById("researchLabCompositePanel");
  const el = document.getElementById("researchLabCompositeDetail");
  const holdingsPanel = document.getElementById("researchLabHoldingsPanel");
  if (!panel || !el) return;
  if (item.strategy_id !== ResearchUniverse.COMPOSITE_ID) {
    panel.hidden = true;
    el.innerHTML = "";
    return;
  }
  panel.hidden = false;
  if (holdingsPanel) holdingsPanel.hidden = true;
  const backtest = item.backtest || {};
  const arch = ResearchUniverse.architecture();
  const composite = compositeDynamicSummary();
  const turnover = backtest.turnover || {};
  const ids = compositeConstituentIds(backtest);
  const weightPct = composite.weightPct;
  el.innerHTML = `
    <div class="research-composite-metrics">
      <span>Eligible ACTIVE <strong>${arch.eligible_active_count}</strong></span>
      <span>Constituents <strong>${arch.composite_constituent_count}</strong></span>
      <span>Equal-weight <strong>${arch.equal_weight_formula} = ${weightPct}%</strong></span>
      <span>Dynamic membership <strong>${composite.dynamicMembership ? "Enabled" : "Disabled"}</strong></span>
      <span>Gross return <strong>${formatMetricNa(backtest.gross_metrics?.cumulative_return, (v) => pct(v, 1))}</strong></span>
      <span>Net return <strong>${formatMetricNa(backtest.net_metrics?.cumulative_return, (v) => pct(v, 1))}</strong></span>
      <span>Sharpe <strong>${formatMetricNa(backtest.net_metrics?.sharpe, (v) => num(v, 3))}</strong></span>
      <span>Max drawdown <strong>${formatMetricNa(backtest.net_metrics?.max_drawdown, (v) => pct(v, 1))}</strong></span>
      <span>Cost drag <strong>${formatCostDragRatio(turnover.total_cost_drag)}</strong></span>
    </div>
    <p class="status-muted">${escapeHtml(composite.expansionNote)}</p>
    <div class="panel-title sub">Constituent IDs (${ids.length})</div>
    <ul class="compact-list">${ids.map((id) => `<li><strong>${escapeHtml(id)}</strong> - ${weightPct}%</li>`).join("") || "<li>No constituent IDs in bundle.</li>"}</ul>`;
}

function latestSeriesValue(values = []) {
  const finite = (values || []).map((value) => Number(value)).filter(Number.isFinite);
  return finite.length ? finite.at(-1) : null;
}

function renderFactoryResearchPerformanceMetrics(backtest) {
  const el = document.getElementById("researchLabPerformanceMetrics");
  if (!el) return;
  el.innerHTML = `
    <span>Gross cum. <strong>${formatMetricNa(backtest.gross_metrics?.cumulative_return, (v) => pct(v, 1))}</strong></span>
    <span>Net cum. <strong>${formatMetricNa(backtest.net_metrics?.cumulative_return, (v) => pct(v, 1))}</strong></span>
    <span>Ann. net <strong>${formatMetricNa(backtest.net_metrics?.annual_return, (v) => pct(v, 1))}</strong></span>
    <span>Sharpe <strong>${formatMetricNa(backtest.net_metrics?.sharpe, (v) => num(v, 3))}</strong></span>
    <span>Volatility <strong>${formatMetricNa(backtest.net_metrics?.annual_volatility, (v) => pct(v, 1))}</strong></span>
    <span>Max DD <strong>${formatMetricNa(backtest.net_metrics?.max_drawdown, (v) => pct(v, 1))}</strong></span>`;
}

function renderFactoryResearchRiskMetrics(backtest, packetSeries = {}, isComposite = false) {
  const el = document.getElementById("researchLabRiskMetrics");
  if (!el) return;
  const turnover = backtest.turnover || {};
  const currentDrawdown = latestSeriesValue(packetSeries.drawdown);
  if (isComposite) {
    el.innerHTML = `
      <span>Turnover <strong>${formatDailyTurnover(turnover.average_daily_turnover)}</strong></span>
      <span>Cost drag <strong>${formatCostDragRatio(turnover.total_cost_drag)}</strong></span>
      <span>Current drawdown <strong>${formatMetricNa(currentDrawdown, (v) => pct(v, 2))}</strong></span>`;
    return;
  }
  el.innerHTML = `
    <span>Turnover <strong>${formatDailyTurnover(turnover.average_daily_turnover)} - ${formatAnnualizedTurnover(turnover.annualized_turnover)}</strong></span>
    <span>Cost drag <strong>${formatCostDragRatio(turnover.total_cost_drag ?? turnover.annualized_cost_drag)}</strong></span>
    <span>Current drawdown <strong>${formatMetricNa(currentDrawdown, (v) => pct(v, 2))}</strong></span>`;
}

function renderFactoryResearchLabPanels(item) {
  if (!item?.backtest) return;
  selectedLiteratureItem = item;
  selectedFactoryResearchId = item.strategy_id;
  const backtest = item.backtest;
  const resolved = resolveFactoryResearchSeries(item);
  const { dates, gross, net, missingMessage } = resolved;
  const packetSeries = backtest.risk_packet?.chart_series || {};
  const isComposite = item.strategy_id === ResearchUniverse.COMPOSITE_ID;
  const arch = ResearchUniverse.architecture();
  renderFactoryResearchOverview(item);
  renderFactoryResearchMainPanel(item, resolved);
  renderFactoryResearchPerformanceMetrics(backtest);
  renderFactoryResearchRiskMetrics(backtest, packetSeries, isComposite);
  renderResearchLabShadowDetail(item.strategy_id);
  if (isComposite) {
    renderFactoryResearchCompositeDetail(item);
  } else {
    renderFactoryResearchCompositeDetail({ strategy_id: "" });
    renderFactoryResearchHoldings(backtest, false);
  }
  const caption = document.getElementById("researchLabCaption");
  if (caption) {
    const composite = compositeDynamicSummary();
    caption.textContent = isComposite
      ? `${composite.headline} - ${factoryResearchBacktestDates(item)} - N=${arch.composite_constituent_count} - weight=${composite.weightPct}% - dynamic membership enabled`
      : `${backtest.name} (${item.strategy_id}) - US-Equity Research Backtest - Research Only - ${factoryResearchBacktestDates(item)}`;
  }
  const chartEmptyMessage = missingMessage
    || "Bundle field for gross/net series not mapped yet: return_series.gross_returns, return_series.net_returns.";
  drawGrossNetEquityChart(
    document.getElementById("backtestCanvas"),
    dates,
    gross,
    net,
    chartEmptyMessage,
  );
  const drawdown = packetSeries.drawdown || [];
  setResearchNotice(
    "researchDrawdownNotice",
    drawdown.length ? "" : "Drawdown series missing from bundle field: risk_packet.chart_series.drawdown.",
  );
  drawDrawdownChart(
    document.getElementById("researchDrawdownCanvas"),
    drawdown,
    drawdown.length ? "" : "Drawdown series missing from bundle field: risk_packet.chart_series.drawdown.",
  );
  const rolling = packetSeries.rolling_63d_sharpe || packetSeries.rolling_sharpe || [];
  setResearchNotice(
    "researchRollingNotice",
    rolling.length ? "" : "Rolling Sharpe missing from bundle field: risk_packet.chart_series.rolling_63d_sharpe.",
  );
  drawRollingSharpeChart(
    document.getElementById("researchRollingCanvas"),
    rolling,
    rolling.length ? "" : "Rolling Sharpe missing from bundle field: risk_packet.chart_series.rolling_63d_sharpe.",
  );
  setResearchNotice(
    "researchDistributionNotice",
    net.length ? "" : "Return distribution missing from bundle field: return_series.net_returns.",
  );
  drawReturnDistributionChart(
    document.getElementById("researchDistributionCanvas"),
    net,
    net.length ? "" : "Return distribution missing from bundle field: return_series.net_returns.",
  );
  document.getElementById("walkForwardTable").innerHTML = "<tr><th>Train</th><th>Test</th><th>Train Sharpe</th><th>Test Sharpe</th><th>Test Return</th><th>Test Max DD</th></tr><tr><td colspan='6'>Walk-forward unavailable in current US-equity research baseline.</td></tr>";
  renderResearchChecklistUnavailable("No-look-ahead checklist unavailable for the Combined Portfolio; inspect an underlying literature prototype.");
  const selector = document.getElementById("researchLabSelector");
  if (selector && item.strategy_id) selector.value = item.strategy_id;
}

async function fetchResearchExtension() {
  const candidates = ["/api/artifact/research", "/output/literature_strategy_backtests.json"];
  for (const path of candidates) {
    try {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) continue;
      const payload = await response.json();
      if (path.includes("literature_strategy_backtests")) {
        return { literature_strategy_backtests: payload };
      }
      return payload;
    } catch {
      continue;
    }
  }
  return null;
}

async function ensureResearchExtension(artifact = activeArtifact) {
  if (!artifact) return artifact;
  const literature = artifact.literature_strategy_backtests || {};
  if ((literature.results || []).length) return artifact;
  if (!literature.lazy_load && !literature.results_count) return artifact;
  if (!researchExtensionPromise) researchExtensionPromise = fetchResearchExtension();
  const extension = await researchExtensionPromise;
  if (extension?.literature_strategy_backtests) {
    artifact.literature_strategy_backtests = extension.literature_strategy_backtests;
  }
  return artifact;
}

function mergeStrategyDetail(strategy, detail) {
  if (!strategy || !detail) return strategy;
  if (detail.position_packet) strategy.position_packet = detail.position_packet;
  if (detail.risk_packet?.chart_series) {
    strategy.risk_packet = { ...(strategy.risk_packet || {}), chart_series: detail.risk_packet.chart_series };
  }
  return strategy;
}

async function ensureStrategyDetail(strategy, artifact = activeArtifact) {
  if (!strategy) return strategy;
  if (strategy.position_packet || strategy.risk_packet?.chart_series) return strategy;
  try {
    const response = await fetch(
      `/api/artifact/strategy-detail?strategy_id=${encodeURIComponent(strategy.strategy_id)}`,
      { cache: "no-store" },
    );
    if (!response.ok) return strategy;
    const detail = await response.json();
    if (detail.ok === false) return strategy;
    mergeStrategyDetail(strategy, detail);
    const index = (artifact?.strategies || []).findIndex((row) => row.strategy_id === strategy.strategy_id);
    if (index >= 0) mergeStrategyDetail(artifact.strategies[index], detail);
  } catch {
    return strategy;
  }
  return strategy;
}

function refreshResearchLabViews(artifact = activeArtifact) {
  if (!artifact) return;
  if (hasFactoryResearch()) {
    populateResearchLabSelector(artifact);
    const defaultId = selectedFactoryResearchId || ResearchUniverse.COMPOSITE_ID;
    const item = ResearchUniverse.itemById(defaultId) || factoryResearchCatalogItems()[0];
    if (item) renderFactoryResearchLabPanels(item);
    renderFactoryResearchArchitectureBanner();
    return;
  }
  renderLiteratureStrategies(artifact.literature_strategy_backtests || {});
  populateResearchLabSelector(artifact);
  const litResults = artifact.literature_strategy_backtests?.results || [];
  if (litResults.length) renderResearchLabPanels({ ...litResults[0], _index: 0 });
}

function scheduleSecondaryRender(artifact) {
  const run = () => {
    renderHistoricalResearchContext(artifact);
    renderRiskSidebar(artifact);
    renderCardsAndMatrices(artifact);
    renderStaticTables(artifact);
    renderWorkflow(artifact);
    populateResearchLabSelector(artifact);
    installIntradayPolling(artifact);
  };
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(run, { timeout: 1200 });
  } else {
    requestAnimationFrame(run);
  }
}

function scheduleResearchExtensionLoad(artifact) {
  void ensureResearchExtension(artifact).then((updated) => {
    if (!updated) return;
    activeArtifact = updated;
    refreshResearchLabViews(updated);
    const selected = updated.strategies?.[0];
    if (selected?.walk_forward?.windows?.length) {
      document.getElementById("walkForwardTable").innerHTML = "<tr><th>Train</th><th>Test</th><th>Train Sharpe</th><th>Test Sharpe</th><th>Test Return</th><th>Test Max DD</th></tr>" +
        selected.walk_forward.windows.slice(-12).map((window) => `<tr><td>${window.train_start} → ${window.train_end}</td><td>${window.test_start} → ${window.test_end}</td><td>${num(window.train_sharpe)}</td><td>${num(window.test_sharpe)}</td><td class="${cls(window.test_return || 0)}">${pct(window.test_return || 0, 2)}</td><td class="negative">${pct(window.test_max_drawdown || 0, 2)}</td></tr>`).join("");
    }
  });
}

function setActiveTab(tab) {
  document.querySelectorAll(".nav-rail button[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.tabPanel === tab);
  });
  if (tab === "Daily Risk Report / Decision Log" && activeArtifact) {
    renderDailyReport(activeArtifact);
  }
  if (tab === "Backtesting & Research Lab" && activeArtifact) {
    const operationalDetail = document.getElementById("operationalStrategyDetail");
    if (!operationalDetail) {
      void ensureResearchExtension(activeArtifact).then((updated) => {
        activeArtifact = updated;
        refreshResearchLabViews(updated);
      });
    }
  }
  if (tab === "Daily Performance" && activeArtifact?.shadow_live) {
    renderOperationalDailyPerformance(activeArtifact);
  }
  requestAnimationFrame(() => redrawAllCharts(activeArtifact));
}

function renderLeftNav() {
  const nav = document.getElementById("navRail");
  if (!nav) return;
  let html = "";
  let lastGroup = "";
  NAV_SECTIONS.forEach((item, index) => {
    if (item.group !== lastGroup) {
      html += `<div class="nav-group-label">${item.group}</div>`;
      lastGroup = item.group;
    }
    html += `<button type="button" class="${index === 0 ? "active" : ""}" data-tab="${item.tab}" title="${item.tab}">${icon(item.icon)}<span>${item.label}</span></button>`;
  });
  nav.innerHTML = html;
  nav.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => setActiveTab(button.dataset.tab)));
  installShellControls();
}

function renderTopHeader(artifact = activeArtifact) {
  const el = document.getElementById("topbarMeta");
  if (!el || !artifact) return;
  const monitoring = formatMonitoringState(artifact);
  const modeLabel = hasFactoryResearch()
    ? "US-Equity Research Backtest - Research Only"
    : "Prototype Model Portfolio";
  el.innerHTML = `
    <span class="mode-badge">${modeLabel}</span>
    <span>As-of <strong>${artifact.as_of_date || "n/a"}</strong></span>
    <span>Initial Model Capital <strong>${money(artifact.initial_capital || 0)}</strong></span>
    <span>Monitored <strong>${artifact.strategy_count || 0}</strong></span>
    <span>Market <strong>${monitoring.headerMarket}</strong></span>
    <span>Data <strong class="${monitoring.tone || ""}">${monitoring.headerData}</strong></span>`;
  renderSecondaryStatusStrip(artifact);
}

function renderSecondaryStatusStrip(artifact, meta = artifact?.build_metadata || {}, marketAsOf = meta.market_as_of || artifact?.as_of_date) {
  const el = document.getElementById("secondaryStatusStrip");
  if (!el) return;
  const monitoring = formatMonitoringState(artifact);
  const disclosure = hasFactoryResearch()
    ? "US-Equity Research Backtest - Research Only - Not live allocation or fills"
    : (artifact?.data_classification?.disclosure || "Prototype - ETF proxy - Not live fills");
  el.innerHTML = `
    <span title="${escapeHtml(disclosure)}">Build ${meta.build_id || "n/a"}</span>
    <span>Retrieved ${meta.data_retrieved_at || meta.artifact_generated_at || "n/a"}</span>
    <span>Operating since ${investmentStart(artifact)}</span>
    <span>${monitoring.stripMonitoring} - ${monitoring.stripDataState}</span>
    <span>Proxy as-of ${marketAsOf}</span>
    <span>${disclosure.length > 90 ? `${disclosure.slice(0, 87)}…` : disclosure}</span>`;
}

function renderGlobalStatusBar() {
  /* V2: metadata moved to topbar + secondary strip */
}

function installShellControls() {
  const drawer = document.getElementById("riskDrawer");
  document.getElementById("toggleRiskDrawer")?.addEventListener("click", () => {
    drawer?.classList.toggle("collapsed");
  });
}

function renderHistoricalResearchContext(artifact = activeArtifact) {
  if (hasFactoryResearch()) {
    renderFactoryResearchArchitectureBanner();
    return;
  }
  const el = document.getElementById("historicalResearchContext");
  if (!el || !artifact) return;
  const hist = historicalResearchRiskSummary(artifact);
  const dq = artifact.data_quality || {};
  const recon = dq.static_current_weight_reconstruction || {};
  el.innerHTML = `
    <div class="research-context-banner">
      <strong>Historical research context (not operating-period PnL)</strong>
      <span>Long-window Sharpe ${num(hist.portfolio_sharpe)} - Vol ${pct(hist.portfolio_volatility || 0, 1)} - Max DD ${pct(hist.portfolio_max_drawdown || 0, 1)} - ${dq.common_portfolio_risk_window_observations || 0} aligned obs</span>
      <span class="status-muted">${recon.label || "Static weight reconstruction"}: ${recon.description || dq.important_note || ""}</span>
    </div>`;
}

function compareMetricDelta(before, after, lowerBetter, turnover) {
  if ((turnover || 0) <= 0.0001) {
    return { label: "No allocation change", className: "neutral" };
  }
  if (!Number.isFinite(before) || !Number.isFinite(after)) {
    return { label: "N/A", className: "neutral" };
  }
  if (Math.abs(after - before) < 1e-8) {
    return { label: "Unchanged", className: "neutral" };
  }
  const improved = lowerBetter ? Math.abs(after) < Math.abs(before) : after > before;
  const delta = after - before;
  return {
    label: improved ? "Improved" : "Worse",
    className: improved ? "positive" : "negative",
    delta,
  };
}

function renderTabs() {
  renderLeftNav();
}

function renderAllocationBars(strategies = []) {
  const el = document.getElementById("allocationBars");
  if (!el) return;
  const allocated = strategies.filter((strategy) => (strategy.current_weight || 0) > 0)
    .sort((left, right) => (right.current_weight || 0) - (left.current_weight || 0));
  const maxWeight = Math.max(...allocated.map((strategy) => strategy.current_weight || 0), 0.01);
  el.innerHTML = allocated.slice(0, 10).map((strategy) => `
    <div class="allocation-bar-row">
      <span>${strategy.name}</span>
      <div class="allocation-bar-track"><span class="allocation-bar-fill" style="width:${Math.min(100, (strategy.current_weight / maxWeight) * 100)}%"></span></div>
      <strong class="col-pct">${pct(strategy.current_weight || 0)}</strong>
    </div>`).join("") || "<p class='empty-state'>No allocated strategies.</p>";
}

function strategyRationale(strategy) {
  const review = strategy.decision_review || {};
  const gate = strategy.correlation_gate || {};
  if (review.summary) return review.summary;
  if (gate.interpretation) return gate.interpretation;
  if (strategy.allocation_eligibility?.summary) return strategy.allocation_eligibility.summary;
  return strategy.hypothesis || "Monitor daily behavior versus hypothesis and limits.";
}

function strategyActionLabel(strategy, proposedWeight = strategy.proposed_weight) {
  const action = strategy.final_action_after_double_check || strategy.recommended_action || "Review";
  const change = (proposedWeight ?? strategy.proposed_weight ?? 0) - (strategy.current_weight || 0);
  if (Math.abs(change) < 0.0001) return action;
  if (change > 0) return action.includes("Increase") ? action : "Increase Review";
  return action.includes("Reduce") ? action : "Reduce Review";
}

function drawAllocationDonut(canvas, strategies = []) {
  if (!canvas) return;
  const allocated = strategies.filter((strategy) => (strategy.current_weight || 0) > 0);
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!allocated.length) return;
  const colors = ["#1ac8ff", "#3bd671", "#ffb020", "#ff5a4f", "#9b7bff", "#58d1c9", "#f472b6", "#a3e635", "#fb7185", "#38bdf8"];
  const cx = w / 2;
  const cy = h / 2;
  const radius = Math.min(w, h) * 0.38;
  let start = -Math.PI / 2;
  allocated.forEach((strategy, index) => {
    const slice = Math.max(strategy.current_weight || 0, 0) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.fillStyle = colors[index % colors.length];
    ctx.arc(cx, cy, radius, start, start + slice);
    ctx.closePath();
    ctx.fill();
    start += slice;
  });
  ctx.beginPath();
  ctx.fillStyle = oklchToHex(16, 0.027, 205);
  ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "rgba(211,234,240,.85)";
  ctx.font = "11px Inter, system-ui";
  ctx.textAlign = "center";
  ctx.fillText(`${allocated.length} live`, cx, cy - 2);
  ctx.fillText("strategies", cx, cy + 12);
}

function oklchToHex() {
  return "#1a2430";
}

function renderRebalancePreview(artifact) {
  const el = document.getElementById("rebalancePreviewTable");
  if (!el) return;
  const rows = (artifact.strategies || []).filter((strategy) => {
    const proposed = sessionProposedWeight(strategy.strategy_id, strategy.proposed_weight || 0);
    return (strategy.current_weight || 0) > 0 || proposed > 0;
  });
  el.innerHTML = `<tr><th>Strategy</th><th>Current</th><th>Proposed</th><th>Change</th><th>Risk Impact</th><th>Est. Cost</th><th>Action</th><th>Gate</th><th>Human</th></tr>` +
    rows.map((strategy) => {
      const proposed = sessionProposedWeight(strategy.strategy_id, strategy.proposed_weight || 0);
      const change = proposed - (strategy.current_weight || 0);
      const cost = Math.abs(change) * artifact.initial_capital * 0.0005;
      const gate = proposalSession.simulation?.checks?.find((c) => c.status === "breach")
        || strategy.decision_review?.checks?.find((c) => c.status === "breach");
      return `<tr>
        <td><button class="table-link" data-open-strategy="${strategy.strategy_id}"><strong>${strategy.name}</strong></button></td>
        <td class="col-pct">${pct(strategy.current_weight || 0, 1)}</td>
        <td class="col-pct">${pct(proposed, 1)}</td>
        <td class="${cls(change)} col-pct">${pct(change, 1)}</td>
        <td class="wrap-cell">${proposalSession.simulation ? "See Allocation simulation" : "Simulation required for impact"}</td>
        <td class="col-num">${money(cost)}</td>
        <td class="col-status">${statusBadge(strategyActionLabel(strategy, proposed))}</td>
        <td class="col-status">${statusBadge(gate ? "blocked" : "clear")}</td>
        <td class="col-status">${statusBadge(strategy.human_approval_required ? "required" : "n/a")}</td>
      </tr>`;
    }).join("");
  el.querySelectorAll("[data-open-strategy]").forEach((button) => button.addEventListener("click", () => {
    setActiveTab("Allocation & Rebalance");
    openStrategyReview(artifact.strategies.find((strategy) => strategy.strategy_id === button.dataset.openStrategy), artifact);
  }));
}

function canonicalNonOkChecks(artifact = activeArtifact, filter = "current_model") {
  return groupedCanonicalIssues(artifact, filter === "all" ? "all" : filter);
}

function renderCommandRiskLimits(artifact) {
  const el = document.getElementById("commandRiskLimitsTable");
  if (!el) return;
  const checks = canonicalNonOkChecks(artifact).slice(0, 10);
  el.innerHTML = `<tr><th>Subject</th><th>Metric</th><th>Current</th><th>Limit</th><th>Util.</th><th>Status</th></tr>` +
    checks.map((check) => `<tr>
      <td class="wrap-cell">${escapeHtml(formatIssueSubjectLabel(check, artifact))}</td>
      <td>${humanizeMetricLabel(check.metric, artifact)}</td>
      <td>${typeof check.current_value === "number" ? num(check.current_value, 3) : humanize(check.current_value)}</td>
      <td>${typeof check.breach_threshold === "number" ? num(check.breach_threshold, 3) : humanize(check.breach_threshold)}</td>
      <td>${check.utilization != null ? pct(check.utilization, 0) : "—"}</td>
      <td>${statusBadge(check.status)}</td>
    </tr>`).join("") || `<tr><td colspan="6">All configured limits within range on allocated scope.</td></tr>`;
}

function renderCommandCorrelationMini(artifact) {
  const el = document.getElementById("commandCorrelationMini");
  if (!el) return;
  const rows = (artifact.correlation?.matrix || []).slice(0, 6);
  const names = rows.map((row) => row.strategy_id);
  if (!rows.length) {
    el.innerHTML = "";
    return;
  }
  const normalized = rows.map((row) => {
    const out = { strategy: row.name };
    row.values.forEach((value) => { if (names.includes(value.strategy_id)) out[value.strategy_id] = value.correlation; });
    return out;
  });
  renderRealMatrix("commandCorrelationMini", normalized, names, "correlation");
}

function renderCommandMarketMini(artifact) {
  const el = document.getElementById("commandMarketMini");
  if (!el) return;
  el.innerHTML = `<tr><th>Proxy</th><th>Last</th><th>Daily</th><th class="interpretation-cell">Read</th></tr>` +
    (artifact.market_monitor || []).slice(0, 6).map((row) => `<tr>
      <td>${row.ticker}</td>
      <td class="col-num">${Number(row.last || 0).toFixed(2)}</td>
      <td class="col-pct ${cls(row.daily_return || 0)}">${pct(row.daily_return || 0, 2)}</td>
      <td class="interpretation-cell wrap-cell">${row.risk_interpretation}</td>
    </tr>`).join("");
}

function renderMonitorKpiStrip(artifact) {
  const el = document.getElementById("monitorKpiStrip");
  if (!el) return;
  const strategies = artifact.strategies || [];
  const allocated = strategies.filter((strategy) => strategy.current_weight > 0);
  const warnings = allocated.filter((strategy) => ["watch", "warning"].includes(strategy.live_risk_status || strategy.risk_status)).length;
  const breaches = allocated.filter((strategy) => (strategy.live_risk_status || strategy.risk_status) === "breach").length;
  const openReviews = countOpenDecisionReviews(artifact, localDecisionEvents);
  el.innerHTML = compactKpiStrip([
    ["Monitored", strategies.length, "", ""],
    ["Allocated", allocated.length, "", ""],
    ["Warnings", warnings, "", warnings ? "warning-text" : ""],
    ["Allocated Strategy Breaches", breaches, "", breaches ? "negative" : ""],
    ["Open Decision Reviews", String(openReviews), `Policy: ${strategies.length} strategies`, openReviews ? "warning-text" : ""],
  ]);
}

function renderMonitorKpiGrid(artifact) {
  renderMonitorKpiStrip(artifact);
}

function renderFactorKpiGrid(artifact) {
  const el = document.getElementById("factorKpiGrid");
  if (!el) return;
  const exposureMap = artifact.factors?.portfolio_factor_exposure_current || {};
  const primaryMetrics = ["equity_beta", "credit_spread", "rates_duration", "usd_fx", "commodity_beta", "volatility"];
  const checksByMetric = Object.fromEntries((artifact.risk_limits?.factors?.checks || []).map((check) => [check.metric, check]));
  const checks = primaryMetrics.map((metric) => checksByMetric[metric]).filter(Boolean);
  if (!checks.length) {
    el.innerHTML = `<article class="kpi-card factor-proxy-card"><span>Proxy Factor Loadings</span><strong>Normal</strong><small>No active proxy factor limit breaches</small></article>`;
    return;
  }
  el.innerHTML = checks.map((check) => {
    const card = formatFactorLimitCard(check, exposureMap, artifact);
    const toneClass = card.statusClass === "breach" ? "negative" : card.statusClass === "warning" || card.statusClass === "watch" ? "warning-text" : "";
    return `<article class="kpi-card factor-proxy-card">
      <span class="factor-proxy-label" title="${escapeHtml(card.tooltip)}">${escapeHtml(card.label)}</span>
      <div class="factor-proxy-value-row">
        <strong class="${toneClass}" title="Signed proxy loading">${card.exposureText}</strong>
        <span class="factor-proxy-direction">${escapeHtml(card.direction)}</span>
      </div>
      <small class="factor-proxy-limit">|Loading| / Limit ${escapeHtml(card.loadingLimitText)} - ${escapeHtml(card.utilizationText)}</small>
      ${card.utilization != null ? utilizationBar(card.utilization, card.rawStatus) : ""}
      <span class="badge ${card.statusClass}">${escapeHtml(card.statusLabel)}</span>
    </article>`;
  }).join("");
}

function renderAllocationBeforeAfterStrip(artifact) {
  const el = document.getElementById("allocationBeforeAfterStrip");
  if (!el) return;
  const current = proposalSession.simulation?.metricsBefore || {
    sharpe: metricNumeric(operatingMetric(artifact, "portfolio_sharpe")) ?? artifact.risk_summary?.portfolio_sharpe ?? 0,
    volatility: artifact.risk_summary?.portfolio_volatility || 0,
    var99: artifact.risk_summary?.portfolio_var_99 || 0,
    es95: artifact.risk_summary?.portfolio_expected_shortfall_95 || 0,
    maxDrawdown: artifact.risk_summary?.portfolio_max_drawdown || 0,
  };
  const proposed = proposalSession.simulation?.metrics || current;
  const corrSummary = artifact.correlation?.summary || {};
  const turnover = proposalSession.simulation?.turnover ?? 0;
  const total = Object.values(proposalSession.weights).reduce((sum, v) => sum + Number(v || 0), 0);
  const cash = 1 - total;
  const unchanged = proposalIsUnchanged(artifact, proposalSession.weights);
  const metrics = [
    ["Sharpe", current.sharpe, proposed.sharpe, false, false],
    ["Volatility", current.volatility, proposed.volatility, true, true],
    ["VaR 99%", current.var99, proposed.var99, true, true],
    ["ES 95%", current.es95, proposed.es95, true, true],
    ["Max DD", current.maxDrawdown, proposed.maxDrawdown, true, true],
    ["Avg |Corr|", corrSummary.average_abs_correlation || 0, corrSummary.average_abs_correlation || 0, true, false],
    ["Concentration", corrSummary.max_abs_correlation || 0, corrSummary.max_abs_correlation || 0, true, false],
    ["Residual Cash", cash, cash, true, true],
    ["Turnover", turnover, turnover, true, false],
    ["Txn Cost", proposalSession.simulation?.estimatedCost ?? 0, proposalSession.simulation?.estimatedCost ?? 0, true, false],
  ];
  el.innerHTML = `<div class="before-after-strip">${metrics.map(([label, before, after, lowerBetter, asPct]) => {
    const m = metricDelta(before, after, { lowerBetter, asPct, turnover: unchanged ? 0 : turnover });
    const avail = label.includes("Sharpe") && !operatingMetric(artifact, "portfolio_sharpe")?.available ? "N/A" : "";
    return `<div class="before-after-metric"><span class="label">${label}</span><span class="ba-values">${avail || `${m.beforeText} → ${m.afterText}`}</span><span class="ba-delta ${m.className}">${unchanged ? "No change" : m.label}</span></div>`;
  }).join("")}${unchanged ? `<div class="before-after-metric"><span class="label">Net improvement</span><span class="ba-values">—</span><span class="ba-delta neutral">No rebalance proposed</span></div>` : ""}</div>`;
}

function renderCompareAllocationKpis(artifact) {
  renderAllocationBeforeAfterStrip(artifact);
}

function renderAllocationPersistentChecks(artifact) {
  const el = document.getElementById("allocationPersistentChecks");
  if (!el) return;
  const total = Object.values(proposalSession.weights).reduce((sum, v) => sum + Number(v || 0), 0);
  const cash = 1 - total;
  const gateImpact = summarizeProposalGateImpact(proposalSession.simulation);
  const currentBreaches = countCurrentPortfolioBreaches(artifact);
  const reduceOnly = (artifact.strategies || []).filter((s) => {
    const e = formatEligibilityDisplay(s);
    return e.label.includes("reduce-only") || e.label.includes("under review");
  }).length;
  el.innerHTML = `
    <span>Proposed weight <strong>${pct(total, 1)}</strong></span>
    <span>Invested <strong>${pct(total, 1)}</strong></span>
    <span>Residual cash <strong>${pct(cash, 1)}</strong></span>
    <span>Reduce-only <strong>${reduceOnly}</strong></span>
    <span>Current portfolio breaches <strong class="${currentBreaches ? "negative" : ""}">${currentBreaches}</strong></span>
    <span>New proposal breaches <strong class="${gateImpact.newBreaches ? "negative" : ""}">${gateImpact.newBreaches}</strong></span>
    <span>Worsened breaches <strong class="${gateImpact.worsened ? "warning-text" : ""}">${gateImpact.worsened}</strong></span>
    <span>Improved/resolved <strong class="${gateImpact.improved ? "positive" : ""}">${gateImpact.improved}</strong></span>
    <span>Proposal gate blockers <strong class="${gateImpact.blockers ? "negative" : ""}">${gateImpact.blockers}</strong></span>
    <span>Turnover <strong>${pct(proposalSession.simulation?.turnover ?? 0, 1)}</strong></span>
    <span>Txn cost <strong>${money(proposalSession.simulation?.estimatedCost ?? 0)}</strong></span>`;
}

function renderDecisionStatusLines(artifact) {
  const el = document.getElementById("decisionStatusLines");
  if (!el) return;
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  el.innerHTML = `
    <div><strong>Proposal status:</strong> ${statusBadge(proposal.status)} — ${proposal.detail}</div>
    <div><strong>Human approval:</strong> ${localDecisionEvents.at(-1)?.event || "Not recorded"}</div>
    <div><strong>Execution authorization:</strong> disabled / not authorized</div>`;
}

function renderAllocationAnalysisPanels(artifact) {
  const factorTable = document.getElementById("factorConcentrationTable");
  const corrPanel = document.getElementById("correlationComparePanel");
  const budget = document.getElementById("riskBudgetUsage");
  const scenarioTable = document.getElementById("scenarioImpactTable");
  const currentExp = proposalSession.simulation?.factorExposureBefore || artifact.factors?.portfolio_factor_exposure_current || {};
  const proposedExp = proposalSession.simulation?.factorExposureAfter || artifact.factors?.portfolio_factor_exposure_proposed || artifact.factors?.portfolio_factor_exposure_current || {};
  const factorChecks = artifact.risk_limits?.factors?.checks || [];
  if (factorTable) {
    const keys = [...new Set([...Object.keys(currentExp), ...Object.keys(proposedExp)])].slice(0, 10);
    factorTable.innerHTML = `<tr><th>Factor</th><th>Current</th><th>Proposed</th><th>Limit</th><th>Util. Before</th><th>Util. After</th><th>Δ</th></tr>` +
      keys.map((factor) => {
        const check = factorChecks.find((c) => c.metric === factor || humanizeFactor(c.metric, artifact) === humanizeFactor(factor, artifact));
        const before = Number(currentExp[factor] || 0);
        const after = Number(proposedExp[factor] || 0);
        const utilBefore = check?.utilization ?? Math.abs(before);
        const utilAfter = check?.utilization ?? Math.abs(after);
        return `<tr><td>${humanizeFactor(factor, artifact)}</td><td>${num(before, 3)}</td><td>${num(after, 3)}</td><td>${check ? num(check.breach_threshold, 3) : "—"}</td><td>${utilizationBar(utilBefore, check?.status)}</td><td>${utilizationBar(utilAfter, check?.status)}</td><td class="${cls(after - before)}">${num(after - before, 3)}</td></tr>`;
      }).join("");
  }
  const corr = artifact.correlation?.summary || {};
  if (corrPanel) {
    corrPanel.innerHTML = `
      <p>Avg |correlation|: <strong>${num(corr.average_abs_correlation)}</strong> (before/after proxy)</p>
      <p>Duplicate-risk pairs: <strong>${corr.breach_count || 0}</strong></p>
      <p>Max |correlation|: <strong>${num(corr.max_abs_correlation)}</strong></p>`;
  }
  if (budget) {
    const exposure = currentExp;
    const maxAbs = Math.max(...Object.values(exposure).map((v) => Math.abs(Number(v) || 0)), 0.01);
    budget.innerHTML = Object.entries(exposure).slice(0, 8).map(([factor, value]) => `<div><span>${humanizeFactor(factor, artifact)}</span><div class="bar"><span style="width:${clamp(Math.abs(value) / maxAbs * 100, 4, 100)}%"></span></div><strong>${num(value, 3)}</strong></div>`).join("");
  }
  if (scenarioTable) {
    scenarioTable.innerHTML = `<tr><th>Scenario</th><th>Current</th><th>Proposed</th><th>Status</th></tr>` +
      (artifact.factors?.scenario_shock_table || []).slice(0, 8).map((row) => `<tr><td>${row.scenario}</td><td class="negative">${pct(row.estimated_portfolio_impact || 0, 2)}</td><td class="negative">${pct(row.estimated_portfolio_impact || 0, 2)}</td><td>${statusBadge(row.risk_status)}</td></tr>`).join("");
  }
}

function renderApprovalStatusBar(artifact) {
  const el = document.getElementById("approvalStatusBar");
  if (!el) return;
  const cost = proposalSession.simulation?.estimatedCost ?? artifact.allocation?.estimated_transaction_cost ?? 0;
  const gateImpact = summarizeProposalGateImpact(proposalSession.simulation);
  const simHardBlockers = (proposalSession.simulation?.checks || []).filter((check) => check.status === "breach");
  const currentBreaches = countCurrentPortfolioBreaches(artifact);
  const unchanged = proposalIsUnchanged(artifact, proposalSession.weights);
  const gateStatus = unchanged
    ? "Proposal gate status: clear (no allocation change)"
    : gateImpact.blockers
      ? `Proposal gate status: blocked (${gateImpact.blockers} blocker${gateImpact.blockers === 1 ? "" : "s"})`
      : "Proposal gate status: clear (no new or worsened blockers)";
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  const humanReview = proposal.status === "No rebalance proposed"
    ? "Human review: monitoring acknowledgement only"
    : proposal.status === "Simulation required"
      ? "Human review: pending simulation"
      : "Human review: required";
  const blocked = !unchanged && (gateImpact.blockers > 0 || simHardBlockers.length > 0);
  el.className = `approval-status-bar v2-approval-bar ${blocked ? "pending" : ""}`;
  el.innerHTML = `
    <div><strong>Proposal Status</strong><div>${statusBadge(proposal.status)} ${proposal.detail}</div></div>
    <div><strong>Est. Transaction Cost</strong><div>${money(proposal.status === "No rebalance proposed" ? 0 : cost)}</div></div>
    <div><strong>Optimizer</strong><div>${humanize(proposalSession.simulation?.optimizerLabel || artifact.rebalance_simulation?.official_optimizer?.optimizer_label, "Heuristic proposal")}</div></div>
    <div><strong>Proposal Gates</strong><div>${gateStatus}</div><small class="status-muted">Current portfolio breaches: ${currentBreaches}</small></div>
    <div><strong>Governance</strong><div>${humanReview} - Execution authorization: disabled</div></div>`;
  const approveBtn = document.getElementById("approveDecision");
  if (approveBtn) approveBtn.disabled = blocked;
}

function renderAllocationSidePanels(artifact) {
  const factorCompare = document.getElementById("factorConcentrationCompare");
  const budget = document.getElementById("riskBudgetUsage");
  const warnings = document.getElementById("allocationWarnings");
  if (!factorCompare || !budget || !warnings) return;
  const current = artifact.allocation?.factor_concentration_before_after?.current || artifact.factors?.portfolio_factor_concentration_current || {};
  const proposed = artifact.allocation?.factor_concentration_before_after?.proposed || artifact.factors?.portfolio_factor_concentration_proposed || {};
  factorCompare.innerHTML = [
    ["Top factor", current.top_factor, proposed.top_factor],
    ["Top |exposure|", num(current.top_abs_exposure, 3), num(proposed.top_abs_exposure, 3)],
    ["Gross factor exposure", num(current.gross_factor_exposure, 3), num(proposed.gross_factor_exposure, 3)],
  ].map(([label, before, after]) => `<div><span>${humanize(label)}</span><strong>${before || "—"} → ${after || "—"}</strong></div>`).join("");
  const exposure = artifact.factors?.portfolio_factor_exposure_current || {};
  const maxAbs = Math.max(...Object.values(exposure).map((value) => Math.abs(Number(value) || 0)), 0.01);
  budget.innerHTML = Object.entries(exposure).slice(0, 6).map(([factor, value]) => `<div><span>${humanize(factor)}</span><div class="bar"><span style="width:${clamp(Math.abs(value) / maxAbs * 100, 4, 100)}%"></span></div><strong>${num(value, 3)}</strong></div>`).join("");
  warnings.innerHTML = (artifact.factors?.human_review_alerts || []).slice(0, 5).map((alert) => `<p>${statusBadge("warning")} <strong>${humanize(alert.topic)}</strong><br>${alert.message}</p>`).join("") || "<p>No additional allocation warnings.</p>";
}

function renderAiRiskSummary(artifact, targetId = "aiRiskSummary") {
  const el = document.getElementById(targetId);
  if (!el) return;
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  const recs = artifact.recommendations || [];
  const impact = (artifact.decision_review?.expected_impact?.risk_metric_changes || []).slice(0, 4);
  el.innerHTML = `
    <p><strong>Proposal status:</strong> ${statusBadge(proposal.status)} — ${proposal.detail}</p>
    <ul>${recs.slice(0, 5).map((rec) => `<li>${escapeHtml(humanizeUserFacingText(rec.action, artifact))}: ${escapeHtml(humanizeUserFacingText(rec.rationale, artifact))}</li>`).join("")}</ul>
    <p><strong>Expected metric shifts (official optimizer):</strong></p>
    <ul>${impact.map((metric) => `<li>${humanize(metric.metric)} ${num(metric.current, 3)} → ${num(metric.proposed, 3)} (${metric.expected_outcome})</li>`).join("") || "<li>Run simulation to refresh custom-weight impact.</li>"}</ul>
    <p><strong>Current portfolio breaches:</strong> ${countCurrentPortfolioBreaches(artifact)} - <strong>Proposal gate blockers:</strong> ${summarizeProposalGateImpact(proposalSession.simulation).blockers}</p>`;
}

function renderRebalanceTradeList(artifact) {
  const el = document.getElementById("rebalanceTradeList");
  if (!el) return;
  const trades = artifact.allocation?.rebalance_trade_list || [];
  el.innerHTML = `<tr><th>Strategy</th><th>Side</th><th>Weight Δ</th><th>$ Notional</th><th>Est. Cost</th></tr>` +
    trades.slice(0, 12).map((trade) => `<tr>
      <td>${trade.name || trade.strategy_id}</td>
      <td>${humanize(trade.side)}</td>
      <td class="${cls(trade.weight_change || 0)}">${pct(trade.weight_change || 0, 1)}</td>
      <td>${money(trade.dollar_amount || 0)}</td>
      <td>${money(trade.estimated_transaction_cost || 0)}</td>
    </tr>`).join("") || `<tr><td colspan="5">No material trades in current proposal.</td></tr>`;
}

function renderWorkstationPanels(artifact) {
  renderAllocationBars(artifact.strategies || []);
  renderContributorsDetractorsTables(artifact);
  renderOperatingLedgerOrCharts(artifact);
  renderRiskActionCenter(artifact);
  renderRebalancePreview(artifact);
  renderCommandMarketMini(artifact);
  renderCommandWatchlistPanels(artifact);
  renderMonitorKpiStrip(artifact);
  renderFactorKpiGrid(artifact);
  renderAllocationBeforeAfterStrip(artifact);
  renderAllocationAnalysisPanels(artifact);
  renderApprovalStatusBar(artifact);
  renderDecisionStatusLines(artifact);
  renderAllocationPersistentChecks(artifact);
}

function canvasScale(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width && rect.height && (canvas.width !== rect.width * ratio || canvas.height !== rect.height * ratio)) {
    canvas.width = Math.floor(rect.width * ratio);
    canvas.height = Math.floor(rect.height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, w: rect.width || canvas.width, h: rect.height || canvas.height };
}

function pathFromSeries(ctx, values, x0, y0, width, height, min, max) {
  values.forEach((value, i) => {
    const x = x0 + (i / Math.max(values.length - 1, 1)) * width;
    const y = y0 + (1 - (value - min) / (max - min || 1)) * height;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
}

function downsampleSeries(values, maxPoints) {
  if (values.length <= maxPoints) return values;
  const bucket = values.length / maxPoints;
  return Array.from({ length: maxPoints }, (_, index) => {
    const start = Math.floor(index * bucket);
    const end = Math.max(start + 1, Math.floor((index + 1) * bucket));
    const slice = values.slice(start, end).filter(Number.isFinite);
    return slice.length ? slice.reduce((sum, value) => sum + value, 0) / slice.length : 0;
  });
}

function drawSparkline(canvas, values = [], color = "#1ac8ff") {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  const raw = (values || []).filter(Number.isFinite);
  const series = raw.length > 3 ? downsampleSeries(raw, 48) : raw.length ? raw : [0, 0];
  const min = Math.min(...series);
  const max = Math.max(...series);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(155, 190, 202, .16)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, h * 0.62);
  ctx.lineTo(w, h * 0.62);
  ctx.stroke();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  pathFromSeries(ctx, series, 0, 3, w, h - 6, min, max === min ? min + 1e-6 : max);
  ctx.stroke();
}

function drawOperatingPeriodCharts(series = {}) {
  drawSingleMetricChart(document.getElementById("pnlCanvas"), series.cumulative_return || [], {
    label: "Cumulative return",
    color: "#1ac8ff",
    format: (value) => pct(value, 2),
  });
  drawSingleMetricChart(document.getElementById("drawdownCanvas"), series.drawdown || [], {
    label: "Drawdown",
    color: "#ff5a4f",
    format: (value) => pct(value, 2),
  });
}

function drawSingleMetricChart(canvas, values = [], options = {}) {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  const series = downsampleSeries((values || []).filter(Number.isFinite), Math.max(80, Math.floor(w * 1.1)));
  ctx.clearRect(0, 0, w, h);
  if (!series.length) {
    ctx.fillStyle = "rgba(211, 234, 240, .72)";
    ctx.font = "12px Inter, system-ui";
    ctx.fillText("Operating-period series unavailable.", 12, 24);
    return;
  }
  const pad = { l: 44, r: 16, t: 20, b: 22 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const min = Math.min(...series, 0);
  const max = Math.max(...series, 0.001);
  ctx.strokeStyle = "rgba(160, 205, 218, .13)";
  for (let i = 0; i <= 3; i += 1) {
    const y = pad.t + (plotH / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  ctx.strokeStyle = options.color || "#1ac8ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  pathFromSeries(ctx, series, pad.l, pad.t, plotW, plotH, min, max);
  ctx.stroke();
  ctx.fillStyle = "rgba(211, 234, 240, .72)";
  ctx.font = "11px Inter, system-ui";
  ctx.fillText(options.label || "Series", pad.l, 12);
  ctx.textAlign = "right";
  const latest = series.at(-1) || 0;
  const latestLabel = options.currentLabel
    ? `${options.currentLabel}: ${options.format ? options.format(latest) : num(latest, 2)}`
    : (options.format ? options.format(latest) : num(latest, 2));
  ctx.fillText(latestLabel, w - 8, 12);
  ctx.textAlign = "left";
}

function drawDualAxisChart(canvas, series, options = {}) {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  const rawPrimary = series?.cumulative_return || [];
  const rawDrawdown = series?.drawdown || [];
  ctx.clearRect(0, 0, w, h);
  if (!rawPrimary.length) return;
  const maxPoints = Math.max(120, Math.floor(w * 1.2));
  const primary = downsampleSeries(rawPrimary, maxPoints);
  const drawdown = downsampleSeries(rawDrawdown, maxPoints);
  const pad = { l: 44, r: 48, t: 22, b: 24 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  ctx.fillStyle = "rgba(0, 229, 255, .025)";
  ctx.fillRect(pad.l, pad.t, plotW, plotH);
  ctx.strokeStyle = "rgba(160, 205, 218, .13)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.t + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  const minP = Math.min(...primary, 0);
  const maxP = Math.max(...primary, 0.001);
  ctx.strokeStyle = options.color || "#1ac8ff";
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  pathFromSeries(ctx, primary, pad.l, pad.t, plotW, plotH * 0.58, minP, maxP);
  ctx.stroke();
  if (drawdown.length) {
    const minD = Math.min(...drawdown, -0.001);
    ctx.strokeStyle = "#ff5a4f";
    ctx.lineWidth = 2;
    ctx.beginPath();
    pathFromSeries(ctx, drawdown, pad.l, pad.t + plotH * 0.64, plotW, plotH * 0.31, minD, 0);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(211, 234, 240, .72)";
  ctx.font = "11px Inter, system-ui";
  ctx.fillText(options.label || "Cumulative return", pad.l, 12);
  ctx.fillStyle = "rgba(255, 102, 88, .86)";
  ctx.fillText("Drawdown", pad.l + 140, 12);
  ctx.textAlign = "right";
  ctx.fillStyle = "rgba(211, 234, 240, .68)";
  ctx.fillText(pct(maxP, 0), w - 6, pad.t + 8);
  ctx.fillText(pct(minP, 0), w - 6, pad.t + plotH * 0.58);
  if (drawdown.length) {
    ctx.fillStyle = "rgba(255, 102, 88, .78)";
    ctx.fillText(pct(Math.min(...drawdown), 0), w - 6, pad.t + plotH * 0.92);
  }
  ctx.textAlign = "left";
}

function drawGrossNetEquityChart(canvas, dates, grossReturns, netReturns, emptyMessage = "Bundle field for gross/net series not mapped yet: return_series.gross_returns, return_series.net_returns.") {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  ctx.clearRect(0, 0, w, h);
  const length = Math.min((grossReturns || []).length, (netReturns || []).length);
  if (!length) {
    drawDrawerChartMessage(canvas, emptyMessage);
    return;
  }
  const grossSlice = grossReturns.slice(0, length);
  const netSlice = netReturns.slice(0, length);
  const grossCurve = [];
  const netCurve = [];
  let grossWealth = 1;
  let netWealth = 1;
  grossSlice.forEach((value, index) => {
    grossWealth *= 1 + Number(grossSlice[index] || 0);
    netWealth *= 1 + Number(netSlice[index] || 0);
    grossCurve.push(grossWealth - 1);
    netCurve.push(netWealth - 1);
  });
  const maxPoints = Math.max(120, Math.floor(w * 1.2));
  const gross = downsampleSeries(grossCurve, maxPoints);
  const net = downsampleSeries(netCurve, maxPoints);
  const pad = { l: 44, r: 16, t: 22, b: 24 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const minV = Math.min(...gross, ...net, 0);
  const maxV = Math.max(...gross, ...net, 0.001);
  ctx.strokeStyle = "rgba(160, 205, 218, .13)";
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.t + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  ctx.strokeStyle = "#8ea0ad";
  ctx.lineWidth = 2;
  ctx.beginPath();
  pathFromSeries(ctx, gross, pad.l, pad.t, plotW, plotH, minV, maxV);
  ctx.stroke();
  ctx.strokeStyle = "#55d48b";
  ctx.beginPath();
  pathFromSeries(ctx, net, pad.l, pad.t, plotW, plotH, minV, maxV);
  ctx.stroke();
  ctx.fillStyle = "rgba(211, 234, 240, .72)";
  ctx.font = "11px Inter, system-ui";
  ctx.fillText("Gross cumulative return", pad.l, 12);
  ctx.fillStyle = "rgba(85, 212, 139, .9)";
  ctx.fillText("Net after 5 bps/side costs", pad.l + 150, 12);
}

function drawReturnDistributionChart(canvas, returns = [], emptyMessage = "Return distribution missing from bundle field: return_series.net_returns.") {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  ctx.clearRect(0, 0, w, h);
  const values = (returns || []).filter(Number.isFinite);
  if (!values.length) {
    drawDrawerChartMessage(canvas, emptyMessage);
    return;
  }
  const bins = 24;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = (max - min) || 1e-6;
  const counts = Array.from({ length: bins }, () => 0);
  values.forEach((value) => {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor(((value - min) / width) * bins)));
    counts[idx] += 1;
  });
  const peak = Math.max(...counts, 1);
  const pad = { l: 28, r: 8, t: 18, b: 18 };
  ctx.fillStyle = "rgba(211, 234, 240, .72)";
  ctx.font = "11px Inter, system-ui";
  ctx.fillText("Daily return distribution", pad.l, 12);
  counts.forEach((count, i) => {
    const barW = (w - pad.l - pad.r) / bins - 2;
    const x = pad.l + i * ((w - pad.l - pad.r) / bins);
    const barH = (count / peak) * (h - pad.t - pad.b);
    ctx.fillStyle = "rgba(26, 200, 255, 0.65)";
    ctx.fillRect(x, h - pad.b - barH, barW, barH);
  });
}

function researchDecisionLabel(backtest, walk = {}) {
  const action = String(backtest?.action?.priority || backtest?.action?.label || "").toLowerCase();
  if (action.includes("reject") || action.includes("pause")) return "Reject";
  if (action.includes("redesign") || action.includes("modify")) return "Redesign";
  if (action.includes("watch") || action.includes("research")) return "Keep Researching";
  if ((walk.positive_windows || 0) >= (walk.number_of_windows || 1) * 0.5 && (backtest.net_metrics?.sharpe || 0) > 0.5) return "Eligible";
  return "Keep Researching";
}

function populateResearchLabSelector(artifact) {
  const select = document.getElementById("researchLabSelector");
  if (!select) return;
  if (hasFactoryResearch()) {
    const items = factoryResearchCatalogItems();
    const groups = [
      ["ACTIVE", items.filter((row) => row.backtest?.factory_research?.membership === "ACTIVE")],
      ["REPAIR", items.filter((row) => row.backtest?.factory_research?.membership === "REPAIR")],
      ["DATA_INSUFFICIENT", items.filter((row) => row.backtest?.factory_research?.membership === "DATA_INSUFFICIENT")],
      ["RESEARCH_CANDIDATE", items.filter((row) => row.backtest?.factory_research?.membership === "RESEARCH_CANDIDATE")],
      ["REFERENCE_ONLY / ARCHIVED", items.filter((row) => ["REFERENCE_ONLY", "ARCHIVED"].includes(row.backtest?.factory_research?.membership))],
      ["COMBINED_PORTFOLIO", items.filter((row) => row.strategy_id === ResearchUniverse.COMPOSITE_ID)],
    ];
    select.innerHTML = groups.flatMap(([label, rows]) => {
      if (!rows.length) return [];
      return [`<optgroup label="${escapeHtml(label)}">`, ...rows.map((row) =>
        `<option value="${escapeHtml(row.strategy_id)}">${escapeHtml(row.backtest?.name || row.strategy_id)} (${escapeHtml(row.strategy_id)})</option>`,
      ), "</optgroup>"];
    }).join("");
    select.onchange = () => openFactoryResearchStrategy(select.value);
    return;
  }
  const results = artifact?.literature_strategy_backtests?.results || [];
  select.innerHTML = results.map((row, index) => `<option value="${index}">${escapeHtml(row.backtest?.name || `Strategy ${index + 1}`)}</option>`).join("");
  select.onchange = () => {
    const item = results[Number(select.value)];
    if (item) renderResearchLabPanels({ ...item, _index: Number(select.value) });
  };
}

function renderResearchLabPanels(item) {
  if (!item?.backtest) return;
  selectedLiteratureItem = item;
  const backtest = item.backtest;
  const walk = item.walk_forward || {};
  const series = backtest.return_series || {};
  const gross = series.gross_returns || [];
  const net = series.net_returns || [];
  const dates = series.dates || [];
  const packetSeries = backtest.risk_packet?.chart_series || {};
  const overview = document.getElementById("researchLabOverview");
  if (overview) {
    overview.innerHTML = [
      renderOverviewField("Strategy Name", backtest.name),
      renderOverviewField("Source", backtest.literature_source || "literature prototype"),
      renderOverviewField("Hypothesis", backtest.hypothesis || "N/A", true),
      renderOverviewField("Backtest Period", `${dates[0] || "N/A"} to ${dates.at(-1) || "N/A"}`, true),
    ].join("");
  }
  const caption = document.getElementById("researchLabCaption");
  if (caption) {
    caption.textContent = `${backtest.name} | ${backtest.literature_source || "literature prototype"} | ${dates[0] || "N/A"} to ${dates.at(-1) || "N/A"}`;
  }
  const performance = document.getElementById("researchLabPerformanceMetrics");
  if (performance) {
    performance.innerHTML = `
      <span>Net ann. return <strong>${pct(backtest.net_metrics?.annual_return || 0, 1)}</strong></span>
      <span>Sharpe <strong>${num(backtest.net_metrics?.sharpe)}</strong></span>
      <span>Volatility <strong>${pct(backtest.net_metrics?.annual_volatility || 0, 1)}</strong></span>
      <span>Max DD <strong>${pct(backtest.net_metrics?.max_drawdown || 0, 1)}</strong></span>`;
  }
  const risk = document.getElementById("researchLabRiskMetrics");
  if (risk) {
    risk.innerHTML = `
      <span>Turnover <strong>${formatAnnualizedTurnover(backtest.turnover?.annualized_turnover)}</strong></span>
      <span>Cost drag <strong>${formatCostDragRatio(backtest.turnover?.annualized_cost_drag)}</strong></span>
      <span>Current drawdown <strong>${formatMetricNa(latestSeriesValue(packetSeries.drawdown), (v) => pct(v, 2))}</strong></span>
      <span>OOS avg Sharpe <strong>${num(walk.average_test_sharpe)}</strong></span>
      <span>Positive OOS windows <strong>${formatOosWindows(walk)}</strong></span>`;
  }
  const holdingsPanel = document.getElementById("researchLabHoldingsPanel");
  const compositePanel = document.getElementById("researchLabCompositePanel");
  if (holdingsPanel) holdingsPanel.hidden = true;
  if (compositePanel) compositePanel.hidden = true;
  const mainDetail = document.getElementById("researchLabMainDetail");
  const chartSection = document.getElementById("researchLabChartSection");
  if (chartSection) chartSection.hidden = false;
  if (mainDetail) {
    mainDetail.hidden = true;
    mainDetail.innerHTML = "";
  }
  const missingGrossNet = [];
  if (!gross.length) missingGrossNet.push("return_series.gross_returns");
  if (!net.length) missingGrossNet.push("return_series.net_returns");
  const chartEmptyMessage = missingGrossNet.length
    ? `Bundle field for gross/net series not mapped yet: ${missingGrossNet.join(", ")}.`
    : "Bundle field for gross/net series not mapped yet: return_series.gross_returns, return_series.net_returns.";
  if (!gross.length || !net.length) {
    if (chartSection) chartSection.hidden = true;
    if (mainDetail) {
      mainDetail.hidden = false;
      mainDetail.innerHTML = `<div class="panel-title sub">Structured Strategy Overview</div><div class="research-overview-grid">${overview?.innerHTML || ""}</div>`;
    }
    setResearchNotice(
      "researchLabChartNotice",
      `${chartEmptyMessage} This strategy currently has summary/risk data only; risk charts are shown below.`,
    );
  } else {
    setResearchNotice("researchLabChartNotice", "");
  }
  drawGrossNetEquityChart(
    document.getElementById("backtestCanvas"),
    dates,
    gross,
    net,
    chartEmptyMessage,
  );
  setResearchNotice(
    "researchDrawdownNotice",
    (packetSeries.drawdown || []).length ? "" : "Drawdown series missing from bundle field: risk_packet.chart_series.drawdown.",
  );
  drawDrawdownChart(
    document.getElementById("researchDrawdownCanvas"),
    packetSeries.drawdown || [],
    (packetSeries.drawdown || []).length ? "" : "Drawdown series missing from bundle field: risk_packet.chart_series.drawdown.",
  );
  setResearchNotice(
    "researchRollingNotice",
    (packetSeries.rolling_63d_sharpe || packetSeries.rolling_sharpe || []).length
      ? ""
      : "Rolling Sharpe missing from bundle field: risk_packet.chart_series.rolling_63d_sharpe.",
  );
  drawRollingSharpeChart(
    document.getElementById("researchRollingCanvas"),
    packetSeries.rolling_63d_sharpe || packetSeries.rolling_sharpe || [],
    (packetSeries.rolling_63d_sharpe || packetSeries.rolling_sharpe || []).length
      ? ""
      : "Rolling Sharpe missing from bundle field: risk_packet.chart_series.rolling_63d_sharpe.",
  );
  setResearchNotice(
    "researchDistributionNotice",
    net.length ? "" : "Return distribution missing from bundle field: return_series.net_returns.",
  );
  drawReturnDistributionChart(
    document.getElementById("researchDistributionCanvas"),
    net,
    net.length ? "" : "Return distribution missing from bundle field: return_series.net_returns.",
  );
  document.getElementById("walkForwardTable").innerHTML = "<tr><th>Train</th><th>Test</th><th>Train Sharpe</th><th>Test Sharpe</th><th>Test Return</th><th>Test Max DD</th></tr>" +
    (walk.windows || []).slice(-12).map((window) => `<tr><td>${window.train_start} → ${window.train_end}</td><td>${window.test_start} → ${window.test_end}</td><td>${num(window.train_sharpe)}</td><td>${num(window.test_sharpe)}</td><td class="${cls(window.test_return || 0)}">${pct(window.test_return || 0, 2)}</td><td class="negative">${pct(window.test_max_drawdown || 0, 2)}</td></tr>`).join("") ||
    "<tr><td colspan='6'>Walk-forward windows unavailable.</td></tr>";
  document.querySelectorAll("[data-literature-strategy]").forEach((row) => {
    row.classList.toggle("selected", Number(row.dataset.literatureStrategy) === (item._index ?? -1));
  });
  const selector = document.getElementById("researchLabSelector");
  if (selector && item._index != null) selector.value = String(item._index);
  const packet = backtest.risk_packet || {};
  if (packet.summary_statistics || (walk.windows || []).length) {
    renderLiteratureChecklist(backtest, packet, walk);
  } else {
    renderResearchChecklistUnavailable("No-look-ahead checklist unavailable for this literature prototype. Risk packet or walk-forward evidence is missing.");
  }
}

function renderResearchChecklistUnavailable(message) {
  const el = document.getElementById("researchChecklist");
  if (!el) return;
  el.innerHTML = `<p class="status-muted">${escapeHtml(message || "No-look-ahead checklist unavailable. Select a literature prototype with validated research evidence.")}</p>`;
}

function renderResearchChecklistHtml(checklist) {
  const el = document.getElementById("researchChecklist");
  if (!el) return;
  if (!checklist?.length) {
    renderResearchChecklistUnavailable();
    return;
  }
  el.innerHTML = checklist.map((section) => `
    <section class="check-section">
      <header>
        <h3>${section.title}</h3>
        <span class="badge ${section.status.includes("Pending") ? "warning" : section.status.includes("Partial") ? "warning" : "ok"}">${section.status}</span>
      </header>
      <ul>${section.items.map((item) => `<li>${item}</li>`).join("")}</ul>
      <p><strong>Analyst prompt:</strong> ${section.prompt}</p>
    </section>
  `).join("");
}

function mean(values) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function std(values) {
  const avg = mean(values);
  return Math.sqrt(values.reduce((sum, value) => sum + (value - avg) ** 2, 0) / Math.max(values.length - 1, 1));
}

function quantile(values, q) {
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * sorted.length)));
  return sorted[index];
}

function distributionStats(returns) {
  const avg = mean(returns);
  const vol = std(returns);
  const annReturn = avg * 252;
  const annVol = vol * Math.sqrt(252);
  const downside = returns.filter((value) => value < 0);
  const downVol = std(downside.length ? downside : [0]) * Math.sqrt(252);
  const sorted = [...returns].sort((a, b) => a - b);
  const var95 = quantile(returns, 0.05);
  const var99 = quantile(returns, 0.01);
  const es95 = mean(sorted.slice(0, Math.max(1, Math.ceil(returns.length * 0.05))));
  const centered = returns.map((value) => value - avg);
  const skew = mean(centered.map((value) => value ** 3)) / (vol ** 3 || 1);
  const kurt = mean(centered.map((value) => value ** 4)) / (vol ** 4 || 1);
  const curve = returns.reduce((acc, value) => {
    acc.push(acc[acc.length - 1] * (1 + value));
    return acc;
  }, [1]).slice(1);
  let peak = curve[0];
  const drawdowns = curve.map((value) => {
    peak = Math.max(peak, value);
    return value / peak - 1;
  });
  return {
    annReturn,
    annVol,
    sharpe: annVol ? annReturn / annVol : 0,
    sortino: downVol ? annReturn / downVol : 0,
    winRate: returns.filter((value) => value > 0).length / returns.length,
    skew,
    kurt,
    var95,
    var99,
    es95,
    worst: sorted[0],
    best: sorted[sorted.length - 1],
    maxDrawdown: Math.min(...drawdowns),
    currentDrawdown: drawdowns[drawdowns.length - 1],
    curve,
    drawdowns,
  };
}

function drawDistribution(canvas, returns) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!returns.length) {
    ctx.fillStyle = "rgba(255,255,255,0.62)";
    ctx.fillText("No validated return series available.", 12, 24);
    return;
  }
  const min = Math.min(...returns);
  const max = Math.max(...returns);
  const buckets = 24;
  const counts = Array.from({ length: buckets }, () => 0);
  returns.forEach((value) => {
    const index = Math.min(buckets - 1, Math.max(0, Math.floor(((value - min) / (max - min || 1)) * buckets)));
    counts[index] += 1;
  });
  const maxCount = Math.max(...counts);
  ctx.strokeStyle = "rgba(255,255,255,0.09)";
  for (let i = 1; i < 5; i += 1) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 5) * i);
    ctx.lineTo(w, (h / 5) * i);
    ctx.stroke();
  }
  counts.forEach((count, index) => {
    const barW = w / buckets - 3;
    const barH = (count / maxCount) * (h - 30);
    const x = index * (w / buckets) + 1;
    const y = h - barH - 14;
    const mid = min + ((index + 0.5) / buckets) * (max - min);
    ctx.fillStyle = mid < 0 ? "#ff4a36" : "#59cf74";
    ctx.fillRect(x, y, barW, barH);
  });
  ctx.fillStyle = "rgba(255,255,255,0.62)";
  ctx.fillText("left tail", 12, h - 4);
  ctx.fillText("right tail", w - 62, h - 4);
}

function drawReturnAndDrawdown(canvas, stats) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(255,255,255,0.09)";
  for (let i = 1; i < 5; i += 1) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 5) * i);
    ctx.lineTo(w, (h / 5) * i);
    ctx.stroke();
  }
  const minCurve = Math.min(...stats.curve);
  const maxCurve = Math.max(...stats.curve);
  ctx.strokeStyle = "#29a8ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  stats.curve.forEach((value, i) => {
    const x = (i / (stats.curve.length - 1)) * w;
    const y = 12 + (1 - (value - minCurve) / (maxCurve - minCurve || 1)) * (h * 0.5);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.strokeStyle = "#ff4a36";
  ctx.beginPath();
  stats.drawdowns.forEach((value, i) => {
    const x = (i / (stats.drawdowns.length - 1)) * w;
    const y = h * 0.62 + Math.abs(value / (stats.maxDrawdown || -0.01)) * h * 0.3;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawSeriesReturnAndDrawdown(canvas, series) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const curve = series.cumulative_return || [];
  const drawdowns = series.drawdown || [];
  if (!curve.length) return;
  ctx.strokeStyle = "rgba(255,255,255,0.09)";
  for (let i = 1; i < 5; i += 1) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 5) * i);
    ctx.lineTo(w, (h / 5) * i);
    ctx.stroke();
  }
  const minCurve = Math.min(...curve);
  const maxCurve = Math.max(...curve);
  ctx.strokeStyle = "#29a8ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  curve.forEach((value, i) => {
    const x = (i / Math.max(curve.length - 1, 1)) * w;
    const y = 12 + (1 - (value - minCurve) / (maxCurve - minCurve || 1)) * (h * 0.5);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const minDd = Math.min(...drawdowns, -0.001);
  ctx.strokeStyle = "#ff4a36";
  ctx.beginPath();
  drawdowns.forEach((value, i) => {
    const x = (i / Math.max(drawdowns.length - 1, 1)) * w;
    const y = h * 0.62 + Math.abs(value / minDd) * h * 0.3;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawRolling(canvas, returns) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const window = 42;
  const rolling = returns.slice(window).map((_, i) => {
    const slice = returns.slice(i, i + window);
    const vol = std(slice) * Math.sqrt(252);
    return vol ? (mean(slice) * 252) / vol : 0;
  });
  const min = Math.min(...rolling, -1);
  const max = Math.max(...rolling, 1);
  ctx.strokeStyle = "rgba(255,255,255,0.09)";
  for (let i = 1; i < 5; i += 1) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 5) * i);
    ctx.lineTo(w, (h / 5) * i);
    ctx.stroke();
  }
  ctx.strokeStyle = "#f5c542";
  ctx.lineWidth = 2;
  ctx.beginPath();
  rolling.forEach((value, i) => {
    const x = (i / (rolling.length - 1)) * w;
    const y = 12 + (1 - (value - min) / (max - min || 1)) * (h - 24);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawRollingSeries(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const rolling = (values || []).filter((value) => Number.isFinite(value));
  ctx.clearRect(0, 0, w, h);
  if (!rolling.length) return;
  const min = Math.min(...rolling, -1);
  const max = Math.max(...rolling, 1);
  ctx.strokeStyle = "rgba(255,255,255,0.09)";
  for (let i = 1; i < 5; i += 1) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 5) * i);
    ctx.lineTo(w, (h / 5) * i);
    ctx.stroke();
  }
  ctx.strokeStyle = "#f5c542";
  ctx.lineWidth = 2;
  ctx.beginPath();
  rolling.forEach((value, i) => {
    const x = (i / Math.max(rolling.length - 1, 1)) * w;
    const y = 12 + (1 - (value - min) / (max - min || 1)) * (h - 24);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

const DRAWER_CHART_UNAVAILABLE = "Chart series missing from bundle.";

function strategyChartSeries(strategy) {
  const series = strategy?.risk_packet?.chart_series || {};
  return {
    dates: series.dates || [],
    returns: series.returns || [],
    cumulative_return: series.cumulative_return || [],
    drawdown: series.drawdown || [],
    rolling_sharpe: series.rolling_63d_sharpe || series.rolling_sharpe || [],
  };
}

function chartHasFiniteValues(values) {
  return (values || []).some((value) => Number.isFinite(Number(value)));
}

function cumulativeFromReturns(returns) {
  let wealth = 1;
  return (returns || []).map((value) => {
    wealth *= 1 + (Number(value) || 0);
    return wealth - 1;
  });
}

function literatureBacktestForStrategy(strategy, artifact = activeArtifact) {
  return (artifact?.literature_strategy_backtests?.results || []).find(
    (row) => row.backtest?.strategy_id === strategy?.strategy_id,
  )?.backtest;
}

function grossNetCumulativeSeries(strategy, artifact, length) {
  const returnSeries = literatureBacktestForStrategy(strategy, artifact)?.return_series;
  if (!returnSeries?.gross_returns?.length || !returnSeries?.net_returns?.length) return null;
  const sliceLen = length || returnSeries.net_returns.length;
  return {
    gross: cumulativeFromReturns(returnSeries.gross_returns.slice(-sliceLen)),
    net: cumulativeFromReturns(returnSeries.net_returns.slice(-sliceLen)),
  };
}

function drawDrawerChartMessage(canvas, message = DRAWER_CHART_UNAVAILABLE) {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "rgba(211, 234, 240, .72)";
  ctx.font = "11px Inter, system-ui";
  ctx.fillText(message, 12, Math.max(24, h / 2));
}

function drawDrawerLineChart(canvas, values, options = {}) {
  if (!canvas) return;
  if (!chartHasFiniteValues(values)) {
    drawDrawerChartMessage(canvas, options.emptyMessage || DRAWER_CHART_UNAVAILABLE);
    return;
  }
  drawSingleMetricChart(
    canvas,
    (values || []).map((value) => Number(value)).filter(Number.isFinite),
    {
      label: options.label || "Series",
      currentLabel: options.currentLabel,
      color: options.color || "#1ac8ff",
      format: options.format || ((value) => num(value, 2)),
    },
  );
}

function drawCumulativeReturnChart(canvas, values, options = {}) {
  drawDrawerLineChart(canvas, values, {
    label: options.label || "Net cumulative return",
    color: options.color || "#1ac8ff",
    format: (value) => pct(value, 2),
    emptyMessage: options.emptyMessage,
  });
}

function drawDrawdownChart(canvas, values, emptyMessage = "Drawdown series missing from bundle field: risk_packet.chart_series.drawdown.") {
  drawDrawerLineChart(canvas, values, {
    label: "Drawdown",
    currentLabel: "Current Drawdown",
    color: "#ff5a4f",
    format: (value) => pct(value, 2),
    emptyMessage,
  });
}

function drawRollingSharpeChart(canvas, values, emptyMessage = "Rolling Sharpe missing from bundle field: risk_packet.chart_series.rolling_63d_sharpe.") {
  const rolling = (values || []).map((value) => (value == null ? NaN : Number(value))).filter(Number.isFinite);
  drawDrawerLineChart(canvas, rolling, {
    label: "Rolling Sharpe (63D)",
    color: "#f5c542",
    format: (value) => num(value, 2),
    emptyMessage,
  });
}

function drawGrossNetCumulativeChart(canvas, gross, net) {
  if (!canvas) return;
  const { ctx, w, h } = canvasScale(canvas);
  ctx.clearRect(0, 0, w, h);
  const grossSeries = downsampleSeries((gross || []).filter(Number.isFinite), Math.max(80, Math.floor(w * 1.1)));
  const netSeries = downsampleSeries((net || []).filter(Number.isFinite), Math.max(80, Math.floor(w * 1.1)));
  if (!grossSeries.length && !netSeries.length) {
    drawDrawerChartMessage(canvas);
    return;
  }
  const pad = { l: 44, r: 16, t: 24, b: 22 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const combined = [...grossSeries, ...netSeries];
  const min = Math.min(...combined, 0);
  const max = Math.max(...combined, 0.001);
  ctx.strokeStyle = "rgba(160, 205, 218, .13)";
  for (let i = 0; i <= 3; i += 1) {
    const y = pad.t + (plotH / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(211, 234, 240, .72)";
  ctx.font = "11px Inter, system-ui";
  ctx.fillText("Gross vs net cumulative return", pad.l, 12);
  ctx.textAlign = "right";
  ctx.fillStyle = "#9fd8ff";
  ctx.fillText("● Gross", w - pad.r, 12);
  ctx.fillStyle = "#1ac8ff";
  ctx.fillText("● Net", w - pad.r - 58, 12);
  ctx.textAlign = "left";
  if (grossSeries.length) {
    ctx.strokeStyle = "#9fd8ff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    pathFromSeries(ctx, grossSeries, pad.l, pad.t, plotW, plotH, min, max);
    ctx.stroke();
  }
  if (netSeries.length) {
    ctx.strokeStyle = "#1ac8ff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    pathFromSeries(ctx, netSeries, pad.l, pad.t, plotW, plotH, min, max);
    ctx.stroke();
  }
}

function drawerChartBlock(title, canvasId, legendHtml = "") {
  return `<section class="drawer-chart-block">
    <div class="drawer-chart-head"><strong>${title}</strong>${legendHtml ? `<span class="drawer-chart-legend">${legendHtml}</span>` : ""}</div>
    <canvas id="${canvasId}" class="drawer-canvas compact" width="380" height="110"></canvas>
  </section>`;
}

function paintDrawerViewCharts(strategy, view, artifact = activeArtifact) {
  const series = strategyChartSeries(strategy);
  if (view === "overview") {
    drawCumulativeReturnChart(document.getElementById("drawerOverviewCumCanvas"), series.cumulative_return, {
      label: "Net cumulative performance",
    });
    drawDrawdownChart(document.getElementById("drawerOverviewDdCanvas"), series.drawdown);
    return;
  }
  if (view === "performance") {
    const grossNet = grossNetCumulativeSeries(strategy, artifact, series.cumulative_return.length);
    if (grossNet) {
      drawGrossNetCumulativeChart(
        document.getElementById("drawerPerfGrossNetCanvas"),
        grossNet.gross,
        grossNet.net,
      );
    } else {
      drawCumulativeReturnChart(
        document.getElementById("drawerPerfGrossNetCanvas"),
        series.cumulative_return,
        { label: "Net cumulative return (gross series unavailable)" },
      );
    }
    drawDrawdownChart(document.getElementById("drawerPerfDrawdownCanvas"), series.drawdown);
    drawRollingSharpeChart(document.getElementById("drawerPerfRollingSharpeCanvas"), series.rolling_sharpe);
  }
}

function openLiteratureStrategyReview(item, artifact) {
  const backtest = item.backtest;
  const walk = item.walk_forward || {};
  const strategy = (artifact?.strategies || []).find((s) => s.strategy_id === backtest?.strategy_id)
    || (artifact?.strategies || [])[0];
  if (strategy) openStrategyReview(strategy, artifact);
  const caption = document.getElementById("researchLabCaption");
  if (caption && backtest) {
    caption.textContent = `${backtest.name} | ${backtest.literature_source || "literature"} | WFO avg Sharpe ${num(walk.average_test_sharpe)} | ${walk.status || "pending"}`;
  }
  renderResearchLabPanels(item);
}

function renderEmptyLiteraturePacket() {
  ["literatureDetailSummary", "literatureRegimeBreakdown", "literatureBenchmarkComparison", "literatureWorstDays"].forEach((id) => {
    document.getElementById(id).innerHTML = "<tr><td>Open a literature prototype to view real yfinance-backed diagnostics.</td></tr>";
  });
}

function renderLiteratureMetricPacket(packet, backtest, walk) {
  const summary = packet.summary_statistics || {};
  const distribution = packet.distribution_shape || {};
  const tail = packet.tail_risk || {};
  const drawdown = packet.drawdown_behavior || {};
  const stability = packet.time_stability || {};
  const benchmark = packet.comparison_vs_benchmark || {};
  document.getElementById("literatureDetailSummary").innerHTML = "<tr><th>Category</th><th>Metric</th><th>Value</th><th>Risk Manager Read</th></tr>" + [
    ["Summary", "Cumulative Return", pct(summary.cumulative_return || 0, 2), "Total net growth after costs."],
    ["Summary", "Annual Return / Vol", `${pct(summary.annual_return || 0, 2)} / ${pct(summary.annual_volatility || 0, 2)}`, "Return must be judged against volatility."],
    ["Summary", "Sharpe / Sortino / Calmar", `${num(summary.sharpe)} / ${num(summary.sortino)} / ${num(summary.calmar)}`, "Risk-adjusted return, downside-adjusted return, drawdown-adjusted return."],
    ["Summary", "Win Rate / Payoff", `${pct(summary.win_rate || 0, 1)} / ${num(summary.payoff_ratio)}`, "High win rate is not enough if losses are much larger."],
    ["Distribution", "Skew / Excess Kurtosis", `${num(distribution.skewness)} / ${num(distribution.excess_kurtosis)}`, "Negative skew and fat tails are hidden risk."],
    ["Distribution", "P01 / P05 / P95 / P99", `${pct(distribution.p01 || 0, 2)} / ${pct(distribution.p05 || 0, 2)} / ${pct(distribution.p95 || 0, 2)} / ${pct(distribution.p99 || 0, 2)}`, "Shows the left and right edges of the return distribution."],
    ["Tail", "VaR 95 / VaR 99", `${pct(tail.var_95 || 0, 2)} / ${pct(tail.var_99 || 0, 2)}`, "Loss threshold in bad days."],
    ["Tail", "ES 95 / ES 99", `${pct(tail.expected_shortfall_95 || 0, 2)} / ${pct(tail.expected_shortfall_99 || 0, 2)}`, "Average loss after VaR is breached."],
    ["Drawdown", "Max / Current DD", `${pct(drawdown.max_drawdown || 0, 2)} / ${pct(drawdown.current_drawdown || 0, 2)}`, "Whether loss is historic breach or current pain."],
    ["Drawdown", "Max Duration / Episodes", `${drawdown.max_drawdown_duration_days || 0} days / ${drawdown.drawdown_episode_count || 0}`, "How long capital can stay underwater."],
    ["Stability", "63D Rolling Sharpe Latest / Avg / Min", `${num(stability["63d"]?.latest_rolling_sharpe)} / ${num(stability["63d"]?.average_rolling_sharpe)} / ${num(stability["63d"]?.min_rolling_sharpe)}`, "Detects recent strategy decay."],
    ["Stability", "252D Positive Sharpe Rate", pct(stability["252d"]?.positive_sharpe_rate || 0, 0), "How often longer windows were actually useful."],
    ["Benchmark", "Beta / Corr To SPY", `${num(benchmark.beta)} / ${num(benchmark.correlation)}`, "Tells whether this is alpha or disguised equity exposure."],
    ["Benchmark", "Alpha / IR", `${pct(benchmark.alpha_annualized || 0, 2)} / ${num(benchmark.information_ratio)}`, "Active performance versus benchmark."],
  ].map(([category, metric, value, read]) => `<tr><td>${category}</td><td>${metric}</td><td>${value}</td><td>${read}</td></tr>`).join("");

  const regimes = packet.regime_breakdown || {};
  document.getElementById("literatureRegimeBreakdown").innerHTML = "<tr><th>Regime</th><th>Obs.</th><th>Ann. Ret</th><th>Vol</th><th>Sharpe</th><th>Max DD</th><th>Win</th><th>ES 95</th></tr>" +
    Object.entries(regimes).map(([name, value]) => `<tr>
      <td>${name.replaceAll("_", " ")}</td>
      <td>${value.observations || 0}</td>
      <td class="${cls(value.annual_return || 0)}">${pct(value.annual_return || 0, 2)}</td>
      <td>${pct(value.annual_volatility || 0, 2)}</td>
      <td>${num(value.sharpe)}</td>
      <td class="negative">${pct(value.max_drawdown || 0, 2)}</td>
      <td>${pct(value.win_rate || 0, 0)}</td>
      <td class="negative">${pct(value.expected_shortfall_95 || 0, 2)}</td>
    </tr>`).join("");

  document.getElementById("literatureBenchmarkComparison").innerHTML = "<tr><th>Benchmark</th><th>Beta</th><th>Corr</th><th>Alpha Ann.</th><th>Tracking Error</th><th>Info Ratio</th><th>Up Capture</th><th>Down Capture</th></tr>" +
    `<tr><td>${benchmark.benchmark || "SPY"}</td><td>${num(benchmark.beta)}</td><td>${num(benchmark.correlation)}</td><td class="${cls(benchmark.alpha_annualized || 0)}">${pct(benchmark.alpha_annualized || 0, 2)}</td><td>${pct(benchmark.tracking_error || 0, 2)}</td><td>${num(benchmark.information_ratio)}</td><td>${num(benchmark.up_capture)}</td><td>${num(benchmark.down_capture)}</td></tr>`;

  document.getElementById("literatureWorstDays").innerHTML = "<tr><th>Date</th><th>Return</th><th>Interpretation</th></tr>" +
    (tail.worst_10_days || []).map((day) => `<tr><td>${day.date}</td><td class="negative">${pct(day.return || 0, 2)}</td><td>Review market regime, factor shock, and whether loss was expected by the strategy design.</td></tr>`).join("");
}

function renderLiteratureChecklist(backtest, packet, walk) {
  const summary = packet.summary_statistics || {};
  const distribution = packet.distribution_shape || {};
  const tail = packet.tail_risk || {};
  const drawdown = packet.drawdown_behavior || {};
  const benchmark = packet.comparison_vs_benchmark || {};
  const checklist = [
    {
      title: "1. Summary Statistics",
      status: "Calculated",
      items: [
        `Annual return ${pct(summary.annual_return || 0, 2)}, annual volatility ${pct(summary.annual_volatility || 0, 2)}, Sharpe ${num(summary.sharpe)}.`,
        `Sortino ${num(summary.sortino)}, Calmar ${num(summary.calmar)}, profit factor ${num(summary.profit_factor)}.`,
        `Annualized turnover ${pct(summary.annualized_turnover || 0, 1)}, so cost drag must be checked before allocation.`,
      ],
      prompt: "Is the return high enough for the volatility, drawdown, and turnover it consumes?",
    },
    {
      title: "2. Distribution Shape",
      status: "Calculated",
      items: [
        `Skewness ${num(distribution.skewness)}, excess kurtosis ${num(distribution.excess_kurtosis)}.`,
        `P01 ${pct(distribution.p01 || 0, 2)}, P05 ${pct(distribution.p05 || 0, 2)}, P95 ${pct(distribution.p95 || 0, 2)}, P99 ${pct(distribution.p99 || 0, 2)}.`,
        "Negative skew means the strategy may look calm most days but lose heavily in stress.",
      ],
      prompt: "Is this a smooth alpha distribution, or a strategy selling hidden tail risk?",
    },
    {
      title: "3. Tail Risk",
      status: "Calculated",
      items: [
        `VaR 95 ${pct(tail.var_95 || 0, 2)}, VaR 99 ${pct(tail.var_99 || 0, 2)}.`,
        `ES 95 ${pct(tail.expected_shortfall_95 || 0, 2)}, ES 99 ${pct(tail.expected_shortfall_99 || 0, 2)}.`,
        `${tail.left_tail_2sigma_count || 0} days breached the 2-sigma left-tail threshold.`,
      ],
      prompt: "Can the portfolio survive this strategy's bad tail at the proposed allocation?",
    },
    {
      title: "4. Drawdown Behavior",
      status: "Calculated",
      items: [
        `Max drawdown ${pct(drawdown.max_drawdown || 0, 2)} on ${drawdown.max_drawdown_date || "n/a"}.`,
        `Current drawdown ${pct(drawdown.current_drawdown || 0, 2)}, max duration ${drawdown.max_drawdown_duration_days || 0} trading days.`,
        `${drawdown.drawdown_episode_count || 0} drawdown episodes across the sample.`,
      ],
      prompt: "Is current pain within normal drawdown behavior, or already a breach?",
    },
    {
      title: "5. Time Stability",
      status: "Calculated",
      items: [
        `Walk-forward status ${walk.status || "pending"}, average test Sharpe ${num(walk.average_test_sharpe)}.`,
        `Positive test windows ${pct(walk.positive_window_rate || 0, 0)}.`,
        "Rolling 21D, 63D, 126D, and 252D Sharpe/vol/drawdown are stored in the metric packet.",
      ],
      prompt: "Did this work repeatedly through time, or only in one historical segment?",
    },
    {
      title: "6. Regime Breakdown",
      status: "Calculated",
      items: [
        "Returns are split by equity up/down, realized volatility high/low, credit stress/supportive, rates up/down, and USD up/down.",
        "This tells us whether losses are expected regime headwind or abnormal strategy decay.",
        "A strategy can be kept during explainable headwind, but reduced if it fails in regimes where it is supposed to help.",
      ],
      prompt: "Which regime does this strategy actually want, and are we currently in the wrong one?",
    },
    {
      title: "7. Comparison Vs Benchmark / Strategies",
      status: "Calculated",
      items: [
        `SPY beta ${num(benchmark.beta)}, correlation ${num(benchmark.correlation)}.`,
        `Annualized alpha ${pct(benchmark.alpha_annualized || 0, 2)}, information ratio ${num(benchmark.information_ratio)}.`,
        "Next layer is comparing this strategy to all other active strategies for duplicate exposure.",
      ],
      prompt: "Is it independent alpha, useful diversification, or another form of equity beta?",
    },
    {
      title: "Decision",
      status: "Human review required",
      items: [
        `System action: ${backtest.action?.action || "Review"} because ${backtest.action?.reason_code || "pending"}.`,
        `Failure modes: ${backtest.failure_modes.join("; ")}.`,
        "Decision choices remain keep, increase review, reduce, hedge, pause, retire, or reject.",
      ],
      prompt: "What action can we defend to the boss from evidence, not from hope?",
    },
  ];
  renderResearchChecklistHtml(checklist);
}

function renderCandidateStrategies() {
  document.getElementById("candidateStrategyTable").innerHTML = "<tr><th>Candidate</th><th>Paper Source</th><th>ETF Coverage</th><th>Signal</th><th>Main Risk</th><th>Status</th></tr>" +
    strategyCandidateShelf.map(([name, source, universe, signal, risk, status]) => {
      const badge = status.includes("running") ? "ok" : status.includes("Next") ? "warning" : "";
      return `<tr>
        <td><strong>${name}</strong></td>
        <td>${source}</td>
        <td>${universe}</td>
        <td>${signal}</td>
        <td>${risk}</td>
        <td><span class="badge ${badge || "warning"}">${status}</span></td>
      </tr>`;
    }).join("");
}

function renderLiteratureStrategies(snapshot) {
  const results = snapshot.results || [];
  const table = document.getElementById("literatureStrategyTable");
  if (!table) return;
  if (!results.length) {
    table.innerHTML = "<tr><td>No literature strategy backtest yet. Run refresh_platform.py.</td></tr>";
    if (!hasFactoryResearch()) {
      renderResearchChecklistUnavailable("No literature strategy backtests loaded. No-look-ahead checklist unavailable until refresh_platform.py generates research evidence.");
    }
    return;
  }
  document.getElementById("literatureStrategyTable").innerHTML = "<tr><th>Prototype</th><th>Source</th><th>Net Sharpe</th><th>Ann. Return</th><th>Max DD</th><th>Cost Drag</th><th>WFO</th><th>Avg Test Sharpe</th><th>Positive Windows</th><th>Action</th><th>Reason</th></tr>" +
    results.map((item, idx) => {
      const backtest = item.backtest;
      const walk = item.walk_forward || {};
      const net = backtest.net_metrics || {};
      const turnover = backtest.turnover || {};
      const action = backtest.action || {};
      const isPause = action.action === "Pause" || action.action === "Reduce";
      const isReview = action.action === "Increase Review";
      const badge = isPause ? "breach" : isReview ? "ok" : "warning";
      return `<tr data-literature-strategy="${idx}">
        <td>${backtest.name}</td>
        <td>${backtest.literature_source}</td>
        <td>${(net.sharpe || 0).toFixed(2)}</td>
        <td class="${cls(net.annual_return || 0)}">${pct(net.annual_return || 0, 2)}</td>
        <td class="negative">${pct(net.max_drawdown || 0, 2)}</td>
        <td>${pct(turnover.annualized_cost_drag || 0, 2)}</td>
        <td>${walk.status || "pending"}</td>
        <td>${(walk.average_test_sharpe || 0).toFixed(2)}</td>
        <td>${pct(walk.positive_window_rate || 0, 0)}</td>
        <td><span class="badge ${badge}">${action.action || "Review"}</span></td>
        <td>${action.reason_code || "pending"}</td>
      </tr>`;
    }).join("");
  document.querySelectorAll("[data-literature-strategy]").forEach((row) => {
    row.addEventListener("click", () => {
      if (hasFactoryResearch()) return;
      const item = results[Number(row.dataset.literatureStrategy)];
      item._index = Number(row.dataset.literatureStrategy);
      renderResearchLabPanels(item);
      setActiveTab("Backtesting & Research Lab");
      openLiteratureStrategyReview(item, activeArtifact || fallbackArtifact);
    });
  });
  if (results.length && !hasFactoryResearch()) {
    const first = { ...results[0], _index: 0 };
    renderResearchLabPanels(first);
  }
}

function renderReplicationClone(snapshot) {
  const results = snapshot.results || [];
  const rolling = results.find((item) => item.method && item.method.startsWith("rolling")) || results[0];
  if (!rolling) {
    document.getElementById("replicationSummaryTable").innerHTML = "<tr><td>No replication snapshot yet. Run refresh_platform.py.</td></tr>";
    document.getElementById("replicationBetas").innerHTML = "";
    return;
  }
  document.getElementById("replicationSummaryTable").innerHTML = `
    <tr><th>Target</th><th>Method</th><th>Obs.</th><th>R2</th><th>Alpha Ann.</th><th>Target Sharpe</th><th>Clone Sharpe</th><th>Interpretation</th></tr>
    <tr>
      <td>${rolling.target_name}</td>
      <td>${rolling.method}</td>
      <td>${rolling.observations}</td>
      <td>${rolling.r_squared.toFixed(3)}</td>
      <td class="${cls(rolling.alpha_annualized)}">${pct(rolling.alpha_annualized, 2)}</td>
      <td>${rolling.target_metrics.sharpe.toFixed(2)}</td>
      <td>${rolling.clone_metrics.sharpe.toFixed(2)}</td>
      <td>${rolling.r_squared > 0.7 ? "Mostly common factor beta" : "Large residual / missing factors"}</td>
    </tr>
  `;
  const betas = rolling.betas || {};
  const maxAbs = Math.max(...Object.values(betas).map((value) => Math.abs(value)), 0.01);
  document.getElementById("replicationBetas").innerHTML = Object.entries(betas).map(([factor, beta]) => `
    <div>
      <span>${factor}</span>
      <div class="bar"><span style="width:${Math.min(100, Math.abs(beta) / maxAbs * 100)}%"></span></div>
      <strong class="${beta < 0 ? "negative" : "positive"}">${beta.toFixed(2)}</strong>
    </div>
  `).join("") + `<p>${(rolling.warnings || []).join(" ")}</p>`;
}

function statusBadge(status) {
  const normalized = String(status || "watch").toLowerCase();
  const badge = normalized === "ok" || normalized.includes("pass") || normalized.includes("keep") || normalized.includes("within") || normalized === "eligible"
    ? "ok"
    : normalized === "breach" || normalized.includes("reject") || normalized.includes("pause") || normalized.includes("block")
      ? "breach"
      : "warning";
  return `<span class="badge ${badge}">${String(status || "watch").replaceAll("_", " ")}</span>`;
}

function setBadgeElement(element, status) {
  const normalized = String(status || "watch").toLowerCase();
  const badge = normalized === "ok" || normalized.includes("pass") || normalized.includes("keep")
    ? "ok"
    : normalized === "breach" || normalized.includes("reject") || normalized.includes("pause") || normalized.includes("block")
      ? "breach"
      : "warning";
  element.className = `badge ${badge}`;
  element.textContent = String(status || "watch").replaceAll("_", " ");
}

function positionSummary(strategy) {
  const positions = strategy.position_packet?.latest_positions || [];
  if (!positions.length) return "No active position";
  return positions.slice(0, 3).map((position) => `${position.ticker} ${pct(position.weight, 0)}`).join(" / ");
}

function renderKpis(artifact) {
  renderCommandKpiStrip(artifact);
  renderAllocationBeforeAfterStrip(artifact);
}

function renderCommandKpiStrip(artifact) {
  const el = document.getElementById("commandKpiStrip");
  if (!el) return;
  const series = portfolioSeriesForDisplay(artifact);
  const cumulative = series.cumulative_return || [];
  const dailyPnlMetric = operatingPnlMetric(artifact, "daily_return");
  const cumPnlMetric = operatingPnlMetric(artifact, "cumulative_return");
  const latestCum = metricNumeric(cumPnlMetric) ?? cumulative.at(-1) ?? 0;
  const latestReturn = metricNumeric(dailyPnlMetric) ?? series.returns?.at(-1) ?? 0;
  const marks = artifact.intraday_marks || {};
  const estimatedNav = marks.estimated_model_nav;
  const estimatedIntradayPnl = marks.estimated_intraday_pnl;
  const aumNow = estimatedNav ?? artifact.initial_capital * (1 + latestCum);
  const headline = canonicalRiskHeadline(artifact);
  const issueCounts = countIssueCategories(artifact);
  const breached = issueCounts.breached_controls;
  const dq = artifact.data_quality || {};
  const intradayDq = dq.intraday || marks.data_quality || {};
  el.innerHTML = compactKpiStrip([
    [estimatedNav ? "Est. Model NAV (proxy)" : "Current Model NAV", money(aumNow), estimatedNav ? "Intraday proxy mark - not realized" : `Operating since ${investmentStart(artifact)}`, cls(latestCum)],
    [estimatedIntradayPnl != null ? "Est. Intraday PnL" : "Daily PnL", money(estimatedIntradayPnl ?? latestReturn * artifact.initial_capital), estimatedIntradayPnl != null ? "Estimated from proxy bars" : formatOperatingMetric(dailyPnlMetric), cls(estimatedIntradayPnl ?? latestReturn)],
    ["Operating Cum. PnL", money(latestCum * artifact.initial_capital), formatOperatingMetric(cumPnlMetric), cls(latestCum)],
    ["Current Drawdown", formatOperatingMetric(operatingMetric(artifact, "portfolio_max_drawdown"), { asPct: true }), "", "negative"],
    ["Volatility", formatOperatingMetric(operatingMetric(artifact, "portfolio_volatility"), { asPct: true }), "Operating period", ""],
    ["VaR 99%", formatOperatingMetric(operatingMetric(artifact, "portfolio_var_99"), { asPct: true }), "", "warning-text"],
    ["Exp. Shortfall", formatOperatingMetric(operatingMetric(artifact, "portfolio_expected_shortfall_95"), { asPct: true }), "", "warning-text"],
    ["Breached Controls", String(breached), `${issueCounts.current_model_issues} current-model issues`, breached ? "negative" : ""],
    ["Data Quality", humanize(intradayDq.freshness || dq.overall_status || "monitor"), intradayDq.freshness ? "Intraday proxy" : dq.stale ? "Stale proxy" : "Proxy OK", intradayDq.freshness === "Stale" || intradayDq.freshness === "Failed" ? "warning-text" : ""],
  ]);
}

function renderOperatingLedgerOrCharts(artifact) {
  const series = portfolioSeriesForDisplay(artifact);
  const obs = (series.returns || []).length;
  const wrap = document.getElementById("operatingLedgerWrap");
  const pnlCanvas = document.getElementById("pnlCanvas");
  const ddPanel = document.getElementById("operatingDrawdownPanel");
  const capital = artifact.initial_capital || 0;
  if (obs < 5 && wrap) {
    wrap.innerHTML = `<div class="table-viewport short operating-ledger-viewport"><div class="table-scroll"><table class="data-table dense operating-ledger-table"><tr><th>Date</th><th>Daily Return</th><th>Daily PnL</th><th>Model NAV</th><th>Cumulative Return</th><th>Drawdown</th></tr>
      ${(series.dates || []).slice(-obs).map((date, i) => {
        const idx = series.dates.length - obs + i;
        const dailyReturn = series.returns[idx] || 0;
        const cumReturn = series.cumulative_return?.[idx] || 0;
        return `<tr><td>${date}</td><td class="${cls(dailyReturn)}">${pct(dailyReturn, 2)}</td><td class="${cls(dailyReturn)}">${money(dailyReturn * capital)}</td><td>${money(capital * (1 + cumReturn))}</td><td>${pct(cumReturn, 2)}</td><td class="negative">${pct(series.drawdown?.[idx] || 0, 2)}</td></tr>`;
      }).join("")}</table></div></div>`;
    if (pnlCanvas) pnlCanvas.style.display = "none";
    if (ddPanel) ddPanel.style.display = "none";
  } else {
    if (wrap) wrap.innerHTML = "";
    if (pnlCanvas) pnlCanvas.style.display = "block";
    if (ddPanel) ddPanel.style.display = "";
    drawOperatingPeriodCharts(series);
  }
}

function renderContributorsDetractorsTables(artifact) {
  const strategies = (artifact.strategies || []).filter((s) => s.current_weight > 0);
  const positive = [...strategies].filter((s) => (s.daily_pnl || 0) > 0).sort((a, b) => (b.daily_pnl || 0) - (a.daily_pnl || 0)).slice(0, 6);
  const negative = [...strategies].filter((s) => (s.daily_pnl || 0) < 0).sort((a, b) => (a.daily_pnl || 0) - (b.daily_pnl || 0)).slice(0, 6);
  const row = (s) => {
    const driver = s.risk_manager_question_answered?.why || s.hypothesis || "—";
    const shortDriver = driver.length > 48 ? `${driver.slice(0, 45)}…` : driver;
    return `<tr><td>${s.name}</td><td class="col-num ${cls(s.daily_pnl || 0)}">${money(s.daily_pnl || 0)}</td><td class="col-pct">${pct(s.current_weight || 0)}</td><td class="wrap-cell" title="${escapeHtml(driver)}">${escapeHtml(shortDriver)}</td></tr>`;
  };
  const ct = document.getElementById("contributorsTable");
  const dt = document.getElementById("detractorsTable");
  if (ct) ct.innerHTML = `<tr><th>Strategy</th><th>Daily PnL</th><th>Alloc.</th><th>Driver</th></tr>${positive.map(row).join("") || "<tr><td colspan='4'>No contributors today.</td></tr>"}`;
  if (dt) dt.innerHTML = `<tr><th>Strategy</th><th>Daily PnL</th><th>Alloc.</th><th>Driver</th></tr>${negative.map(row).join("") || "<tr><td colspan='4'>No detractors today.</td></tr>"}`;
}

function renderRiskActionCenter(artifact) {
  const el = document.getElementById("riskActionTable");
  if (!el) return;
  const checks = collectRiskActionCenterChecks(artifact, riskActionFilter);
  el.innerHTML = `<tr><th>Subject</th><th>Scope</th><th>Issue</th><th>Current</th><th>Threshold</th><th>Util./Gap</th><th>Action</th><th>Status</th></tr>` +
    checks.slice(0, 16).map((check) => `<tr>
      <td class="wrap-cell">${escapeHtml(formatIssueSubjectLabel(check, artifact))}</td>
      <td>${humanize(check.scope)}</td>
      <td class="wrap-cell">${humanizeMetricLabel(check.metric, artifact)}</td>
      <td class="col-num">${escapeHtml(formatRiskActionCurrentValue(check))}</td>
      <td class="col-num">${formatRiskActionThresholdCell(check)}</td>
      <td>${formatRiskActionUtilCell(check)}</td>
      <td class="wrap-cell">${escapeHtml(formatRiskActionAction(check))}</td>
      <td class="col-status">${riskActionStatusBadge(check)}</td>
    </tr>`).join("") || `<tr><td colspan="8">No active issues in ${humanize(riskActionFilter)} view.</td></tr>`;
  document.querySelectorAll("#riskActionFilters [data-risk-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.riskFilter === riskActionFilter);
    button.onclick = () => {
      riskActionFilter = button.dataset.riskFilter;
      renderRiskActionCenter(artifact);
    };
  });
}

function renderCommandWatchlistPanels(artifact) {
  const recs = artifact.recommendations || [];
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  const workflowView = deriveWorkflowPresentation(artifact, proposal);
  document.getElementById("commandWatchlist").innerHTML = recs.slice(0, 5).map((rec) => `<p>${statusBadge(rec.priority || "watch")} <strong>${escapeHtml(humanizeUserFacingText(rec.action, artifact))}</strong> — ${escapeHtml(humanizeUserFacingText(rec.rationale, artifact))}</p>`).join("") || emptyState("No watchlist items.");
  const dq = artifact.data_quality || {};
  document.getElementById("commandDataQuality").innerHTML = `
    <p><strong>Active proposal:</strong> ${statusBadge(proposal.status)} ${proposal.detail}</p>
    <p><strong>Missing series:</strong> ${(dq.missing_return_series || []).length || 0}</p>
    <p><strong>Common window:</strong> ${dq.common_portfolio_risk_window_observations || 0} obs</p>
    <p><strong>Governance:</strong> ${humanize(workflowView.workflowStatus, "monitoring")}</p>
    <p><strong>Open decision reviews:</strong> ${countOpenDecisionReviews(artifact, localDecisionEvents)} - Approval policy applies to ${artifact.strategy_count || 0} strategies</p>`;
}

function renderTables(artifact) {
  const strategies = artifact.strategies || [];
  const allocationTable = document.getElementById("allocationTable");
  if (allocationTable) {
    allocationTable.innerHTML = `<tr><th>Strategy</th><th>Alloc.</th></tr>` +
      strategies.filter((s) => s.current_weight > 0).map((s) => `<tr><td><button class="table-link" data-open-strategy="${s.strategy_id}">${s.name}</button></td><td>${pct(s.current_weight || 0)}</td></tr>`).join("");
  }
  const strategyTable = document.getElementById("strategyTable");
  if (strategyTable) {
    const performanceHeader = "<tr><th>#</th><th>Strategy</th><th>Type</th><th>Status</th><th>Current</th><th>Proposed</th><th>Daily PnL</th><th>Daily Ret</th><th>Op. Sharpe</th><th>Historical Sharpe</th><th>Vol</th><th>Current DD</th><th>Model Risk</th><th>Action</th></tr>";
    strategyTable.innerHTML = performanceHeader + strategies.map((s, idx) => {
      const live = s.current_weight > 0;
      const opSharpe = s.since_investment?.sharpe;
      const opSharpeText = opSharpe?.available === false || opSharpe?.value == null
        ? `N/A (${opSharpe?.observations || 0}/${opSharpe?.minimum_observations || "?"} obs)`
        : num(typeof opSharpe === "object" ? opSharpe.value : opSharpe);
      return `<tr class="${live ? "" : "research-only-row"}" data-strategy="${s.strategy_id}">
      <td>${idx + 1}</td><td><button class="table-link" data-open-strategy="${s.strategy_id}"><strong>${s.name}</strong></button></td><td>${s.strategy_type}</td>
      <td>${live ? statusBadge("model allocated") : statusBadge("research only")}</td>
      <td>${pct(s.current_weight || 0)}</td><td>${pct(sessionProposedWeight(s.strategy_id, s.proposed_weight || 0))}</td>
      <td class="${cls(s.daily_pnl || 0)}">${money(s.daily_pnl || 0)}</td>
      <td class="${cls(s.daily_return || 0)}">${pct(s.daily_return || 0, 2)}</td>
      <td>${live ? opSharpeText : "—"}</td>
      <td>${num(s.sharpe)}</td><td>${pct(s.volatility || 0, 1)}</td>
      <td class="negative">${pct(s.current_drawdown || s.max_drawdown || 0, 1)}</td>
      <td>${statusBadge(live ? (s.live_risk_status || s.risk_status) : "not applicable")}</td><td>${statusBadge(s.final_action_after_double_check || s.recommended_action)}</td>
    </tr>`;
    }).join("");
    strategyTable.querySelectorAll("[data-open-strategy]").forEach((button) => button.addEventListener("click", () => {
      openStrategyReview(strategies.find((row) => row.strategy_id === button.dataset.openStrategy), artifact);
      setActiveTab("Strategy Monitor");
    }));
  }

  populateMonitorFilters(strategies);
  const monitorSortValue = (strategy, key) => {
    if (key === "name") return strategy.name || "";
    if (key === "family") return strategy.strategy_type || "";
    if (key === "turnover") return strategy.turnover?.annualized_turnover || 0;
    if (key === "mtd") return strategy.mtd_return || 0;
    if (key === "cost_drag") return strategy.transaction_cost_drag || strategy.turnover?.annualized_cost_drag || 0;
    return strategy[key] ?? 0;
  };
  const sortedStrategies = [...strategies].sort((left, right) => {
    const a = monitorSortValue(left, monitorSort.key);
    const b = monitorSortValue(right, monitorSort.key);
    if (typeof a === "string" || typeof b === "string") {
      return monitorSort.direction === "asc" ? String(a).localeCompare(String(b)) : String(b).localeCompare(String(a));
    }
    return monitorSort.direction === "asc" ? a - b : b - a;
  });
  const sortableHeader = (label, key) => {
    const active = monitorSort.key === key ? ` sorted-${monitorSort.direction}` : "";
    return `<th><button type="button" class="table-sort${active}" data-sort-key="${key}">${label}</button></th>`;
  };
  const monitorHeader = `<tr>${sortableHeader("Strategy", "name")}<th>Family</th><th>Lifecycle</th><th class="col-pct">Current</th><th class="col-pct">Proposed</th><th>Eligibility</th>${sortableHeader("Daily PnL", "daily_pnl")}<th>MTD</th><th>Hist. Sharpe</th><th>Roll. Sharpe</th><th>Vol</th>${sortableHeader("Current DD", "current_drawdown")}<th>Turnover</th><th>Cost Drag</th><th>Model Risk</th><th>Research</th><th class="wrap-cell">Required Action</th></tr>`;
  const monitorTable = document.getElementById("monitorTable");
  const monitorPanel = monitorTable?.closest(".strategy-monitor-panel");
  if (monitorPanel) {
    if (hasFactoryResearch()) {
      monitorPanel.style.display = "none";
    } else {
      monitorPanel.style.display = "";
    }
  }
  if (!monitorTable || hasFactoryResearch()) return;
  monitorTable.innerHTML = monitorHeader + sortedStrategies.map((s) => {
    const elig = formatEligibilityDisplay(s);
    const live = s.current_weight > 0;
    return `<tr data-strategy="${s.strategy_id}" data-risk="${live ? (s.live_risk_status || s.risk_status) : "not-applicable"}" data-allocated="${live ? "active" : "research"}" data-family="${(s.strategy_type || "").toLowerCase()}" data-action="${(s.final_action_after_double_check || s.recommended_action || "").toLowerCase()}" data-search="${`${s.name} ${s.strategy_type} ${positionSummary(s)}`.toLowerCase()}">
    <td><strong>${s.name}</strong></td>
    <td>${s.strategy_type || "—"}</td>
    <td class="col-status">${statusBadge(live ? "allocated" : "research")}</td>
    <td class="col-pct">${pct(s.current_weight || 0)}</td>
    <td class="col-pct">${pct(sessionProposedWeight(s.strategy_id, s.proposed_weight || 0))}</td>
    <td class="col-status" title="${escapeHtml(elig.detail)}">${statusBadge(elig.label)}</td>
    <td class="col-num ${cls(s.daily_pnl || 0)}">${money(s.daily_pnl || 0)}</td>
    <td class="col-pct ${cls(s.mtd_return || 0)}">${pct(s.mtd_return || 0, 2)}</td>
    <td class="col-num">${num(s.sharpe)}</td>
    <td class="col-num">${num(s.rolling_sharpe)}</td>
    <td class="col-pct">${pct(s.volatility || 0, 1)}</td>
    <td class="col-pct negative">${pct(s.current_drawdown || 0, 1)}</td>
    <td class="col-num">${num(s.turnover?.annualized_turnover, 1)}x</td>
    <td class="col-pct">${pct(s.transaction_cost_drag || s.turnover?.annualized_cost_drag || 0, 2)}</td>
    <td class="col-status">${statusBadge(live ? (s.live_risk_status || s.risk_status) : "not applicable")}</td>
    <td class="col-status">${statusBadge(s.research_quality_status || s.research_status)}</td>
    <td class="wrap-cell">${statusBadge(s.final_action_after_double_check || s.recommended_action || "Review")}</td>
  </tr>`;
  }).join("");
  monitorTable.querySelectorAll("[data-sort-key]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.sortKey;
    if (monitorSort.key === key) monitorSort.direction = monitorSort.direction === "asc" ? "desc" : "asc";
    else { monitorSort.key = key; monitorSort.direction = key === "name" ? "asc" : "desc"; }
    renderTables(artifact);
    installStrategyMonitorControls(artifact);
  }));
  monitorTable.querySelectorAll("tr[data-strategy]").forEach((row) => row.addEventListener("click", () => {
    const selected = strategies.find((item) => item.strategy_id === row.dataset.strategy);
    monitorTable.querySelectorAll("tr[data-strategy]").forEach((item) => item.classList.toggle("selected", item === row));
    openStrategyReview(selected, artifact);
  }));
  document.querySelectorAll("[data-open-strategy]").forEach((row) => row.addEventListener("click", (event) => {
    event.stopPropagation();
    const selected = strategies.find((item) => item.strategy_id === row.dataset.openStrategy);
    setActiveTab("Strategy Monitor");
    openStrategyReview(selected, artifact);
    monitorTable.querySelectorAll("tr[data-strategy]").forEach((item) => item.classList.toggle("selected", item.dataset.strategy === selected?.strategy_id));
  }));
}

function populateMonitorFilters(strategies) {
  const familyFilter = document.getElementById("strategyFamilyFilter");
  const actionFilter = document.getElementById("strategyActionFilter");
  if (familyFilter && familyFilter.options.length <= 1) {
    [...new Set(strategies.map((s) => s.strategy_type).filter(Boolean))].forEach((family) => {
      const opt = document.createElement("option");
      opt.value = family.toLowerCase();
      opt.textContent = family;
      familyFilter.appendChild(opt);
    });
  }
  if (actionFilter && actionFilter.options.length <= 1) {
    [...new Set(strategies.map((s) => s.final_action_after_double_check || s.recommended_action).filter(Boolean))].forEach((action) => {
      const opt = document.createElement("option");
      opt.value = action.toLowerCase();
      opt.textContent = action;
      actionFilter.appendChild(opt);
    });
  }
}

function quantile(values, q) {
  const sorted = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const index = (sorted.length - 1) * q;
  const low = Math.floor(index);
  const high = Math.ceil(index);
  return sorted[low] + (sorted[high] - sorted[low]) * (index - low);
}

function normalizeSimulationPayload(payload) {
  const before = payload.metrics_before || payload.metrics?.before || {};
  const after = payload.metrics_after || payload.metrics || {};
  return {
    source: payload.source || "python_rebalance_simulation",
    metrics: {
      sharpe: after.portfolio_sharpe ?? after.sharpe ?? 0,
      volatility: after.portfolio_volatility ?? after.volatility ?? 0,
      var99: after.portfolio_var_99 ?? after.var99 ?? 0,
      es95: after.portfolio_expected_shortfall_95 ?? after.es95 ?? 0,
      maxDrawdown: after.portfolio_max_drawdown ?? after.maxDrawdown ?? 0,
    },
    metricsBefore: {
      sharpe: before.portfolio_sharpe ?? before.sharpe ?? 0,
      volatility: before.portfolio_volatility ?? before.volatility ?? 0,
      var99: before.portfolio_var_99 ?? before.var99 ?? 0,
      es95: before.portfolio_expected_shortfall_95 ?? before.es95 ?? 0,
      maxDrawdown: before.portfolio_max_drawdown ?? before.maxDrawdown ?? 0,
    },
    checks: payload.checks || [],
    turnover: payload.turnover || 0,
    estimatedCost: payload.estimated_transaction_cost ?? payload.estimatedCost ?? 0,
    limitations: payload.limitations || [],
    factorExposureBefore: payload.factor_exposure_before || {},
    factorExposureAfter: payload.factor_exposure_after || {},
    factorChange: payload.factor_change || {},
    cashWeight: payload.cash_weight,
    proposalGates: payload.proposal_gates || [],
    optimizerLabel: payload.optimizer_label,
    timestamp: payload.timestamp || new Date().toISOString(),
  };
}

async function ensureSimulationApi(artifact, targetWeights) {
  if (officialSimulationFromArtifact(artifact, targetWeights)) return false;
  try {
    const response = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_weights: Object.fromEntries((artifact.strategies || []).map((strategy) => [strategy.strategy_id, strategy.current_weight || 0])),
        target_weights: targetWeights,
        capital: artifact.initial_capital,
      }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function fetchBackendSimulation(artifact, targetWeights) {
  const currentWeights = Object.fromEntries((artifact.strategies || []).map((strategy) => [strategy.strategy_id, strategy.current_weight || 0]));
  const response = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_weights: currentWeights,
      target_weights: targetWeights,
      capital: artifact.initial_capital,
    }),
  });
  const body = await response.json();
  if (!response.ok || body.ok === false) {
    throw new Error(body.error || `simulation api failed: ${response.status}`);
  }
  return normalizeSimulationPayload(body);
}

function officialSimulationFromArtifact(artifact, targetWeights) {
  const currentWeights = Object.fromEntries((artifact.strategies || []).map((strategy) => [strategy.strategy_id, strategy.current_weight || 0]));
  const proposedWeights = Object.fromEntries((artifact.strategies || []).map((strategy) => [strategy.strategy_id, strategy.proposed_weight || 0]));
  const sameAsCurrent = Object.keys(targetWeights).every((key) => Math.abs((targetWeights[key] || 0) - (currentWeights[key] || 0)) < 1e-8);
  const sameAsProposed = Object.keys(targetWeights).every((key) => Math.abs((targetWeights[key] || 0) - (proposedWeights[key] || 0)) < 1e-8);
  const context = artifact.rebalance_simulation || {};
  const payload = sameAsProposed
    ? context.official_optimizer
    : sameAsCurrent
      ? context.current_baseline
      : null;
  if (!payload) return null;
  return normalizeSimulationPayload(payload);
}

function updateWeightTotalsOnly() {
  const total = Object.values(proposalSession.weights).reduce((sum, value) => sum + Number(value || 0), 0);
  const cash = 1 - total;
  const totalState = document.getElementById("weightTotalState");
  if (!totalState) return;
  totalState.className = total > 1.00001 ? "negative" : total < 0 ? "negative" : "positive";
  totalState.textContent = `Invested ${pct(total, 1)} | Cash ${pct(cash, 1)}`;
}

function renderAllocationEditor(artifact) {
  const total = Object.values(proposalSession.weights).reduce((sum, value) => sum + Number(value || 0), 0);
  const cash = 1 - total;
  const totalState = document.getElementById("weightTotalState");
  if (totalState) {
    totalState.className = total > 1.00001 ? "negative weight-total-state" : "positive weight-total-state";
    totalState.textContent = `Invested ${pct(total, 1)} - Residual cash ${pct(cash, 1)}`;
  }
  const table = document.getElementById("allocationEditorTable");
  if (!table) return;
  table.innerHTML = "<tr><th>Strategy</th><th>Lifecycle</th><th>Eligibility</th><th>Current</th><th>Proposed</th><th>Change</th><th>Direction</th><th>Trade $</th><th>Est. Cost</th><th>Risk Contrib.</th><th>Action</th><th>Rationale</th></tr>" +
    (artifact.strategies || []).map((strategy) => {
      const current = strategy.current_weight || 0;
      const target = proposalSession.weights[strategy.strategy_id] || 0;
      const change = target - current;
      const elig = formatEligibilityDisplay({ ...strategy, proposed_weight: target });
      const disabled = !strategy.allocation_eligibility?.eligible && current === 0;
      const reduceOnly = current > 0 && !strategy.allocation_eligibility?.eligible;
      const maxWeight = reduceOnly ? current : 0.25;
      return `<tr data-strategy-row="${strategy.strategy_id}">
        <td><button class="table-link" data-open-strategy="${strategy.strategy_id}"><strong>${strategy.name}</strong></button></td>
        <td class="col-status">${statusBadge(current > 0 ? "allocated" : "research")}</td>
        <td class="col-status" title="${escapeHtml(elig.detail)}">${statusBadge(elig.label)}</td>
        <td class="col-pct">${pct(current, 1)}</td>
        <td><div class="weight-adj"><button type="button" data-weight-delta="${strategy.strategy_id}" data-delta="-0.005" ${disabled ? "disabled" : ""}>−</button><input class="weight-input" data-weight-id="${strategy.strategy_id}" type="number" min="0" max="${(maxWeight * 100).toFixed(1)}" step="0.1" value="${(target * 100).toFixed(1)}" ${disabled ? "disabled" : ""}>%<button type="button" data-weight-delta="${strategy.strategy_id}" data-delta="0.005" ${disabled || (reduceOnly && target >= current - 1e-6) ? "disabled" : ""}>+</button></div></td>
        <td class="${cls(change)} col-pct">${pct(change, 1)}</td>
        <td class="col-status">${change > 0.0001 ? "Buy" : change < -0.0001 ? "Sell" : "Hold"}</td>
        <td class="col-num ${cls(change)}">${money(change * artifact.initial_capital)}</td>
        <td class="col-num">${money(Math.abs(change) * artifact.initial_capital * 0.0005)}</td>
        <td class="col-pct">${pct(strategy.risk_contribution || 0, 1)}</td>
        <td class="col-status">${statusBadge(strategyActionLabel({ ...strategy, proposed_weight: target }))}</td>
        <td class="wrap-cell">${strategyRationale(strategy)}</td>
      </tr>`;
    }).join("");
  table.querySelectorAll("[data-weight-id]").forEach((input) => input.addEventListener("input", () => {
    const strategy = artifact.strategies.find((s) => s.strategy_id === input.dataset.weightId);
    let val = Math.max(0, Number(input.value || 0) / 100);
    if (strategy && strategy.current_weight > 0 && !strategy.allocation_eligibility?.eligible) val = Math.min(val, strategy.current_weight);
    proposalSession.weights[input.dataset.weightId] = val;
    proposalSession.source = "custom";
    invalidateProposalSimulation();
    updateWeightTotalsOnly();
    refreshProposalStatusViews(artifact);
  }));
  table.querySelectorAll("[data-weight-delta]").forEach((button) => button.addEventListener("click", () => {
    const id = button.dataset.weightDelta;
    const delta = Number(button.dataset.delta || 0);
    const strategy = artifact.strategies.find((s) => s.strategy_id === id);
    let next = Math.max(0, (proposalSession.weights[id] || 0) + delta);
    if (strategy && strategy.current_weight > 0 && !strategy.allocation_eligibility?.eligible) next = Math.min(next, strategy.current_weight);
    proposalSession.weights[id] = Math.min(next, 0.25);
    proposalSession.source = "custom";
    invalidateProposalSimulation();
    renderAllocationEditor(artifact);
    refreshProposalStatusViews(artifact);
  }));
  table.querySelectorAll("[data-open-strategy]").forEach((button) => button.addEventListener("click", () => {
    openStrategyReview(artifact.strategies.find((strategy) => strategy.strategy_id === button.dataset.openStrategy), artifact);
    setActiveTab("Strategy Monitor");
  }));
}

function renderSimulationResult(artifact) {
  const el = document.getElementById("simulationChecks");
  if (!el) return;
  const checks = proposalSession.simulation?.checks || [];
  const gates = proposalSession.simulation?.proposalGates || [];
  const sourceNote = proposalSession.simulation?.source === "python_rebalance_simulation"
    ? "Backend-tested Python simulation."
    : proposalSession.simulation ? "Artifact-embedded official optimizer result." : "Run simulation to refresh checks.";
  const cashSemantics = artifact.factors?.cash_semantics || {};
  const cashHtml = Number.isFinite(proposalSession.simulation?.cashWeight)
    ? `<p>${cashSemantics.residual_cash_display_label || "Unallocated residual cash"}: <strong>${pct(proposalSession.simulation.cashWeight, 1)}</strong> - Treasury-bill / liquidity proxy tracked separately.</p>`
    : "";
  el.innerHTML = `<p class="simulation-source">${sourceNote}</p>${cashHtml}` +
    gates.map((gate) => `<p>${statusBadge(gate.status)} <strong>${humanizeMetricLabel(gate.metric || gate.gate, artifact)}</strong> — ${gate.text || gate.required_action || ""}</p>`).join("") +
    checks.map((check) => `<p>${statusBadge(check.status)} <strong>${humanizeMetricLabel(check.metric, artifact)}</strong> — ${check.text}</p>`).join("") || emptyState("No simulation checks yet.");
  renderAllocationBeforeAfterStrip(artifact);
}

async function runSimulation(artifact) {
  if (proposalIsUnchanged(artifact, proposalSession.weights)) {
    proposalSession.simulation = null;
    refreshProposalStatusViews(artifact);
    const statusEl = document.getElementById("decisionAuthorityStatus");
    if (statusEl) statusEl.textContent = "No allocation change from current weights. Simulation not required.";
    return true;
  }
  let payload = officialSimulationFromArtifact(artifact, proposalSession.weights);
  if (!payload && await ensureSimulationApi(artifact, proposalSession.weights)) {
    try {
      payload = await fetchBackendSimulation(artifact, proposalSession.weights);
    } catch {
      payload = null;
    }
  }
  if (!payload) {
    proposalSession.simulation = null;
    refreshProposalStatusViews(artifact);
    document.getElementById("decisionAuthorityStatus").textContent = "Simulation unavailable. Start scripts/run_workstation_server.py for custom weights or regenerate the dashboard artifact.";
    return false;
  }
  proposalSession.simulation = payload;
  refreshProposalStatusViews(artifact);
  const statusEl = document.getElementById("decisionAuthorityStatus");
  if (statusEl) statusEl.textContent = `Simulation completed (${payload.source}). Turnover ${pct(payload.turnover, 1)}, estimated cost ${money(payload.estimatedCost)}. Human approval is still required; execution remains disabled.`;
  return true;
}

function initializeSimulation(artifact) {
  initProposalSession(artifact);
  renderAllocationEditor(artifact);
}

function renderDailyExplanation(artifact) {
  const allocated = (artifact.strategies || []).filter((strategy) => strategy.current_weight > 0);
  const positive = allocated.filter((strategy) => (strategy.daily_pnl || 0) > 0);
  const negative = allocated.filter((strategy) => (strategy.daily_pnl || 0) < 0);
  const gains = positive.reduce((sum, strategy) => sum + strategy.daily_pnl, 0);
  const losses = Math.abs(negative.reduce((sum, strategy) => sum + strategy.daily_pnl, 0));
  const net = gains - losses;
  const factorBreaches = (artifact.risk_limits?.factors?.checks || []).filter((check) => check.status === "breach");
  document.getElementById("dailyExplanation").innerHTML = `
    <div class="explanation-headline"><div><span>Net daily PnL</span><strong class="${cls(net)}">${money(net)}</strong></div><div><span>Protection delivered</span><strong class="positive">${money(gains)}</strong></div><div><span>Loss offset ratio</span><strong>${losses ? pct(gains / losses, 1) : "n/a"}</strong></div><div><span>Allocated live breaches</span><strong class="positive">0</strong></div></div>
    <div class="explanation-grid">
      <section><h4>What happened</h4><p>${negative.length} allocated strategies lost money, while ${positive.length} strategies delivered positive offsets. Diversification worked partially, but the offsets covered only ${losses ? pct(gains / losses, 1) : "0%"} of gross losses.</p></section>
      <section><h4>Why risk remains</h4><p>${factorBreaches.map((check) => `${humanizeMetricLabel(check.metric, artifact)} ${num(check.current_value, 3)} vs limit ${num(check.breach_threshold, 3)}`).join("; ") || "No factor hard breach."} Historical research drawdowns are shown separately and are not live breaches.</p></section>
      <section><h4>Required action</h4><p>Do not add capital simply because a strategy lost. Simulate reductions that lower breached factor exposure, preserve the strategies that offset the selloff, and approve only after the before/after risk and transaction-cost trade-off is documented.</p></section>
    </div>`;
}

function renderRealMatrix(id, rows, factors, mode = "exposure") {
  const el = document.getElementById(id);
  if (!el) return;
  const colWidth = mode === "correlation" ? "minmax(52px, 1fr)" : "minmax(66px, 1fr)";
  el.style.gridTemplateColumns = `minmax(140px, 1.8fr) repeat(${factors.length}, ${colWidth})`;
  const shortLabel = (label) => {
    const text = humanizeFactor(String(label || "").replaceAll("_", " "), activeArtifact);
    return text.length > 22 ? `${text.slice(0, 20)}…` : text;
  };
  const headers = `<div class="cell matrix-label">Strategy</div>${factors.map((factor) => `<div class="cell matrix-label" title="${factor}">${shortLabel(factor)}</div>`).join("")}`;
  const cells = rows.map((row) => `<div class="cell matrix-label">${row.strategy || row.name}</div>` + factors.map((factor) => {
    const value = Number(row[factor] || 0);
    const abs = Math.abs(value);
    const color = mode === "correlation" && value <= -.75
      ? "var(--green-dim)"
      : abs >= .75
        ? "var(--red-dim)"
        : abs >= .45
          ? "oklch(29% 0.09 82)"
          : abs >= .15
            ? "var(--blue-dim)"
            : "var(--panel-3)";
    return `<div class="cell" style="background:${color}">${num(value, 2)}</div>`;
  }).join("")).join("");
  el.innerHTML = headers + cells;
}

function renderCardsAndMatrices(artifact) {
  const strategies = artifact.strategies || [];
  renderContributorsDetractorsTables(artifact);
  renderRecommendationPanels(artifact.recommendations || []);
  const factorRows = artifact.factors?.strategy_by_factor_matrix || [];
  const factorNames = (artifact.factors?.factor_contribution_to_risk || []).slice(0, 6).map((row) => row.factor);
  renderRealMatrix("factorMatrix", factorRows, factorNames);
  renderSimulationResult(artifact);
  renderFactorExposureBars("portfolioFactorBars", artifact.factors?.portfolio_factor_exposure_current, artifact);
  renderFactorExposureBars("riskFactorBars", artifact.factors?.portfolio_factor_exposure_current, artifact);
  renderFactorNotes(artifact);
  renderNewsRiskSummary(artifact.news_risk);
  const allocatedIds = new Set(strategies.filter((strategy) => strategy.current_weight > 0).map((strategy) => strategy.strategy_id));
  const universeSelect = document.getElementById("correlationUniverse");
  if (universeSelect) {
    universeSelect.value = correlationUniverse;
    universeSelect.onchange = () => {
      correlationUniverse = universeSelect.value;
      renderCardsAndMatrices(artifact);
    };
  }
  const corrRowsAll = artifact.correlation?.matrix || [];
  const corrRows = correlationUniverse === "allocated"
    ? corrRowsAll.filter((row) => allocatedIds.has(row.strategy_id))
    : corrRowsAll;
  const corrNames = corrRows.map((row) => row.strategy_id);
  const normalizedCorr = corrRows.map((row) => {
    const out = { strategy: row.name };
    row.values.forEach((value) => {
      if (corrNames.includes(value.strategy_id)) out[value.strategy_id] = value.correlation;
    });
    return out;
  });
  const matrixTitle = document.getElementById("correlationMatrixTitle");
  if (matrixTitle) {
    matrixTitle.textContent = correlationUniverse === "allocated"
      ? `Allocated ${corrRows.length}-Strategy Correlation Matrix`
      : `All-Research ${corrRows.length}-Strategy Correlation Matrix`;
  }
  renderRealMatrix("correlationMatrix", normalizedCorr, corrNames, "correlation");
  const corrSummary = artifact.correlation?.summary || {};
  document.getElementById("correlationSummary").innerHTML = [
    ["Strategies", corrSummary.strategy_count || 0],
    ["Pair count", corrSummary.pair_count || 0],
    ["Average abs. correlation", num(corrSummary.average_abs_correlation)],
    ["Maximum abs. correlation", num(corrSummary.max_abs_correlation)],
    ["Duplicate breaches", corrSummary.breach_count || 0],
    ["Hedge relationships", corrSummary.hedge_relationship_count || 0],
    ["Limit", num(corrSummary.limit)],
  ].map(([label, value]) => drawerMetric(label, value)).join("");
  document.getElementById("correlationPairs").innerHTML = "<tr><th>Left Strategy</th><th>Right Strategy</th><th class='col-num'>Correlation</th><th class='col-status'>Status</th><th class='wrap-cell'>Allocation Read</th></tr>" +
    [...(corrSummary.breaches || []), ...(corrSummary.hedge_relationships || [])].map((pair) => `<tr><td>${pair.left_name}</td><td>${pair.right_name}</td><td class="col-num ${pair.correlation >= pair.limit ? "negative" : "positive"}">${num(pair.correlation)}</td><td class="col-status">${statusBadge(pair.status)}</td><td class="wrap-cell">${pair.correlation > 0 ? "Compare research quality; block or redesign the weaker duplicate." : "Validate hedge stability, stress behavior, carry cost, and basis risk."}</td></tr>`).join("");
  document.getElementById("riskContribution").innerHTML = (artifact.factors?.factor_contribution_to_risk || []).slice(0, 8).map((row) => `<div><span>${humanizeFactor(row.factor, artifact)}</span><div class="bar"><span style="width:${clamp(row.risk_share * 100, 2, 100)}%"></span></div><strong>${pct(row.risk_share, 1)}</strong></div>`).join("");
}

function renderStaticTables(artifact) {
  document.getElementById("scenarioTable").innerHTML = "<tr><th>Scenario</th><th>Estimated Impact</th><th>Status</th><th>Main Drivers</th></tr>" +
    (artifact.factors?.scenario_shock_table || []).map((row) => `<tr><td>${row.scenario}</td><td class="${cls(row.estimated_portfolio_impact || 0)}">${pct(row.estimated_portfolio_impact || 0, 2)}</td><td>${statusBadge(row.risk_status)}</td><td>${(row.drivers || []).slice(0, 3).map((driver) => humanizeFactor(driver.factor, artifact)).join(" / ")}</td></tr>`).join("");
  const exposureMap = artifact.factors?.portfolio_factor_exposure_current || {};
  document.getElementById("factorLimitAlerts").innerHTML = (artifact.risk_limits?.factors?.checks || []).filter((check) => check.status !== "ok" && check.status !== "not_modeled").map((check) => {
    const card = formatFactorLimitCard(check, exposureMap, artifact);
    return `<p><span class="badge ${card.statusClass}">${escapeHtml(card.statusLabel)}</span> <strong>${escapeHtml(card.label)}</strong><br>${escapeHtml(card.direction)} - |Loading| / Limit ${escapeHtml(card.loadingLimitText)} - ${escapeHtml(card.utilizationText)}. ${escapeHtml(check.action || "")}</p>`;
  }).join("");

  const marketRows = artifact.market_monitor || [];
  document.getElementById("marketTable").innerHTML = "<tr><th>Market</th><th class='col-num'>Current</th><th class='col-pct'>Daily Move</th><th class='col-status'>Status</th><th class='interpretation-cell'>Risk Interpretation</th></tr>" +
    marketRows.map((row) => `<tr><td>${row.ticker}</td><td class="col-num">${Number(row.last || 0).toFixed(2)}</td><td class="col-pct ${cls(row.daily_return || 0)}">${pct(row.daily_return || 0, 2)}</td><td class="col-status">${statusBadge(row.status)}</td><td class="interpretation-cell">${row.risk_interpretation}</td></tr>`).join("");
  document.getElementById("newsTable").innerHTML = "<tr><th>Severity</th><th>Source</th><th>Published</th><th>Headline</th><th>Affected</th><th>Relevance</th><th>Review</th></tr>" +
    (artifact.news_risk?.items || []).map((item) => {
      const interpretation = item.risk_interpretation || "";
      const headline = item.headline || "";
      const cleanInterpretation = interpretation.startsWith(headline) ? interpretation.slice(headline.length).replace(/^[\s:—-]+/, "") : interpretation;
      return `<tr>
        <td class="col-status">${statusBadge(item.severity)}</td>
        <td>${escapeHtml(item.source || artifact.news_risk?.source || "proxy")}</td>
        <td>${escapeHtml(item.published_at || item.as_of || "n/a")}</td>
        <td class="wrap-cell">${escapeHtml(headline)}</td>
        <td class="wrap-cell">${escapeHtml((item.affected_strategies || item.affected_factors || [item.topic]).filter(Boolean).join(", ") || "General monitor")}</td>
        <td class="wrap-cell">${escapeHtml(cleanInterpretation || item.topic || "Monitor")}</td>
        <td class="col-status">${item.human_review ? "Required" : "Monitor"}</td>
      </tr>`;
    }).join("");

  const selected = artifact.strategies?.[0];
  if (!hasFactoryResearch()) {
    document.getElementById("walkForwardTable").innerHTML = "<tr><th>Train</th><th>Test</th><th>Train Sharpe</th><th>Test Sharpe</th><th>Test Return</th><th>Test Max DD</th></tr>" +
      (selected?.walk_forward?.windows || []).slice(-12).map((window) => `<tr><td>${window.train_start} → ${window.train_end}</td><td>${window.test_start} → ${window.test_end}</td><td>${num(window.train_sharpe)}</td><td>${num(window.test_sharpe)}</td><td class="${cls(window.test_return || 0)}">${pct(window.test_return || 0, 2)}</td><td class="negative">${pct(window.test_max_drawdown || 0, 2)}</td></tr>`).join("");
  }
  renderLiteratureStrategies(artifact.literature_strategy_backtests || {});
  renderCandidateStrategies();
  renderReplicationClone(artifact.replication_clone || {});
  const decisionFootnote = document.getElementById("decisionAuthorityStatus");
  if (decisionFootnote && !proposalSession.simulation) {
    decisionFootnote.textContent = "Human approval does not authorize execution. Simulate proposal before recording a decision.";
  }
}

function renderWorkflow(artifact) {
  const gateBadge = (status) => statusBadge(status || "pending");
  document.getElementById("workflowTable").innerHTML = "<tr><th>Strategy</th><th>Hypothesis</th><th>Data</th><th>Signal</th><th>Backtest</th><th>Walk-Fwd</th><th>Risk Limits</th><th>Registry</th><th>Model Alloc</th><th>Approval</th><th>Next Action</th></tr>" +
    artifact.strategies.map((s) => {
      const wf = s.workflow_gates || {};
      const elig = formatEligibilityDisplay(s);
      return `<tr>
        <td><strong>${s.name}</strong><small>${s.current_weight > 0 ? `Allocated ${pct(s.current_weight)}` : "Research only"}</small></td>
        <td class="wrap-cell">${s.hypothesis || "—"}</td>
        <td>${gateBadge(wf.data_validation || s.evidence_status)}</td>
        <td>${gateBadge(wf.signal || s.signal_status)}</td>
        <td>${gateBadge(wf.backtest || s.research_quality_status)}</td>
        <td>${gateBadge(wf.walk_forward || (s.walk_forward?.windows?.length ? "complete" : "pending"))}</td>
        <td>${gateBadge(s.current_weight > 0 ? (s.live_risk_status || s.risk_status) : (s.research_quality_status || "research review"))}</td>
        <td>${gateBadge(wf.registry || s.registry_status || "registered")}</td>
        <td>${statusBadge(elig.label)}</td>
        <td>${s.human_approval_required ? gateBadge("required") : gateBadge("not required")}</td>
        <td>${statusBadge(s.final_action_after_double_check || s.recommended_action || "review")}</td>
      </tr>`;
    }).join("");
  const workflowBanner = document.getElementById("workflowFilters");
  if (workflowBanner) {
    workflowBanner.innerHTML = [
      "Hypothesis", "Data validation", "Signal", "Backtest", "Walk-forward",
      "Risk limits", "Registry", "Model allocation", "Human approval",
    ].map((label) => `<span class="workflow-filter-chip">${label}</span>`).join("");
  }
}

function renderRiskSidebar(artifact) {
  const headline = canonicalRiskHeadline(artifact);
  const factorScope = scopeSummary(artifact, "factor");
  const allocatedScope = scopeSummary(artifact, "allocated_strategy_live");
  document.getElementById("limitOkCount").textContent = (
    (scopeSummary(artifact, "portfolio_live").ok || 0)
    + (allocatedScope.ok || 0)
    + (factorScope.ok || 0)
    + (scopeSummary(artifact, "scenario").ok || 0)
    + (scopeSummary(artifact, "correlation").ok || 0)
    + (scopeSummary(artifact, "rebalance").ok || 0)
  );
  document.getElementById("limitWarningCount").textContent = headline.warnings || 0;
  document.getElementById("limitBreachCount").textContent = headline.blocking_breaches || 0;
  const allocatedBreaches = allocatedScope.breach || 0;
  document.getElementById("portfolioLimitState").innerHTML = `${statusBadge(headline.blocking_breaches ? "action required" : "within limits")}<br>${allocatedBreaches} allocated-model strategy breaches in canonical summary. Research-quality failures tracked separately.`;
  const workflow = artifact.decision_workflow || {};
  const review = workflow.stage_2_independent_risk_review || {};
  const authority = workflow.stage_3_decision_authority || {};
  const execution = workflow.stage_4_execution_and_monitoring || {};
  const quality = artifact.data_quality || {};
  document.getElementById("sidebarDecision").innerHTML = `
    ${statusBadge(review.system_conclusion || "review pending")}
    <strong>${humanize(review.status, "No independent review")}</strong>
    <span>${(review.blocking_objections || []).length} blocking objections, ${(review.warnings_and_conditions || []).length} warnings.</span>`;
  document.getElementById("sidebarGovernance").innerHTML = `
    <p><span>Human decision</span><strong>${humanize(authority.decision_outcome, "Not recorded")}</strong></p>
    <p><span>Execution</span><strong>${authority.execution_authorized ? "Authorized" : "Not authorized"}</strong></p>
    <p><span>Realized outcome</span><strong>${humanize(execution.realized_outcome_status, "Pending")}</strong></p>`;
  document.getElementById("sidebarDataQuality").innerHTML = `
    <p><span>Source</span><strong>${quality.source || "Unavailable"}</strong></p>
    <p><span>History</span><strong>${quality.earliest_strategy_start || "n/a"} to ${quality.latest_strategy_end || "n/a"}</strong></p>
    <p><span>Common window</span><strong>${quality.common_portfolio_risk_window_observations || 0} days</strong></p>
    <p><span>Missing series</span><strong>${(quality.missing_return_series || []).length}</strong></p>`;
  document.getElementById("headerRegime")?.remove();
  renderLiveDataState(artifact);
  document.getElementById("macroRegimeLabel").textContent = "Strategy-specific regime diagnostics";
  document.getElementById("macroRegimeNote").textContent = "The current prototype evaluates equity, realized-volatility, credit, rates, and USD regimes. A single live macro regime label remains pending validated release-timed macro inputs.";
}

function renderDrawer(strategy, artifact) {
  if (!strategy) return;
  activeStrategy = strategy;
  activeArtifact = artifact;
  const packet = strategy.risk_packet || {};
  const summary = packet.summary_statistics || {};
  const walk = strategy.walk_forward || {};
  const series = packet.chart_series || {};
  const current = strategy.current_weight || 0;
  const proposed = sessionProposedWeight(strategy.strategy_id, strategy.proposed_weight || 0);
  document.getElementById("selectedStrategyName").textContent = strategy.name;
  document.getElementById("selectedStrategyType").textContent = `${strategy.strategy_type} | ${strategy.strategy_id}`;
  document.getElementById("drawerAlloc").textContent = pct(current);
  document.getElementById("drawerProposed").textContent = pct(proposed);
  const statusEl = document.querySelector(".drawer-kpis div:nth-child(3) strong");
  statusEl.innerHTML = statusBadge(strategy.risk_status);
  setBadgeElement(document.querySelector(".drawer-heading .badge"), strategy.final_action_after_double_check);
  drawSeriesReturnAndDrawdown(document.getElementById("strategyCanvas"), series);
  const weightInput = document.getElementById("drawerWeightInput");
  if (weightInput) {
    weightInput.value = Number(proposalSession.weights[strategy.strategy_id] ?? proposed).toFixed(4);
    weightInput.disabled = !strategy.allocation_eligibility?.eligible && current === 0;
  }
  renderDrawerView(strategy, activeDrawerView, artifact);
}

function resetDrawerView() {
  activeDrawerView = "overview";
  document.querySelectorAll("#drawerTabs .drawer-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.drawerView === "overview");
  });
}

function installDrawerWeightControls(artifact) {
  const applyWeight = async (delta = 0) => {
    if (!activeStrategy) return;
    const input = document.getElementById("drawerWeightInput");
    const base = Number(input?.value || sessionProposedWeight(activeStrategy.strategy_id, activeStrategy.proposed_weight || 0));
    const next = Math.max(0, Math.min(0.25, base + delta));
    proposalSession.weights[activeStrategy.strategy_id] = next;
    proposalSession.source = "custom";
    if (input) input.value = next.toFixed(4);
    invalidateProposalSimulation();
    setActiveTab("Allocation & Rebalance");
    renderAllocationEditor(artifact);
    refreshProposalStatusViews(artifact);
  };
  document.getElementById("drawerWeightUp")?.addEventListener("click", () => applyWeight(0.01));
  document.getElementById("drawerWeightDown")?.addEventListener("click", () => applyWeight(-0.01));
  document.getElementById("drawerApplyWeight")?.addEventListener("click", async () => {
    if (!activeStrategy) return;
    const input = document.getElementById("drawerWeightInput");
    const next = Math.max(0, Math.min(0.25, Number(input?.value || 0)));
    proposalSession.weights[activeStrategy.strategy_id] = next;
    proposalSession.source = "custom";
    invalidateProposalSimulation();
    setActiveTab("Allocation & Rebalance");
    renderAllocationEditor(artifact);
    refreshProposalStatusViews(artifact);
  });
  document.getElementById("drawerGoAllocation")?.addEventListener("click", () => {
    if (activeStrategy) {
      setActiveTab("Allocation & Rebalance");
      renderAllocationEditor(artifact);
    }
  });
}

function drawerMetric(label, value, tone = "") {
  return `<div class="drawer-metric"><span>${label}</span><strong class="${tone}">${value}</strong></div>`;
}

function drawerBodyMessage(message, tone = "status-muted") {
  return `<div class="drawer-callout ${tone}"><p>${escapeHtml(message)}</p></div>`;
}

function renderDrawerView(strategy, view, artifact = activeArtifact) {
  if (!strategy) return;
  activeDrawerView = view;
  document.querySelectorAll("#drawerTabs .drawer-tab").forEach((button) => button.classList.toggle("active", button.dataset.drawerView === view));
  const content = document.getElementById("drawerBody");
  if (!content) return;
  const needsSeries = view === "overview" || view === "performance";
  const paint = (resolvedStrategy) => {
    content.innerHTML = `<p class="status-muted drawer-loading">Loading ${escapeHtml(view)}…</p>`;
    try {
      renderDrawerViewBody(resolvedStrategy, view, artifact, content);
    } catch (error) {
      console.error("Drawer render failed:", error);
      content.innerHTML = drawerBodyMessage(`Unable to render ${view} view. ${error?.message || "See console for details."}`, "negative");
    }
  };
  if (needsSeries && !strategy.risk_packet?.chart_series) {
    content.innerHTML = `<p class="status-muted drawer-loading">Loading ${escapeHtml(view)}…</p>`;
    void ensureStrategyDetail(strategy, artifact).then((detailed) => {
      activeStrategy = detailed;
      paint(detailed);
    });
    return;
  }
  paint(strategy);
}

function renderDrawerViewBody(strategy, view, artifact, content) {
  const packet = strategy.risk_packet || {};
  const summary = packet.summary_statistics || {};
  const drawdown = packet.drawdown_behavior || {};
  const tail = packet.tail_risk || {};
  const walk = strategy.walk_forward || {};
  const live = strategy.current_weight > 0;
  const elig = formatEligibilityDisplay(strategy);
  let html = "";
  if (view === "overview") {
      html = `<div class="drawer-metric-grid">
      ${drawerMetric("Current allocation", pct(strategy.current_weight || 0))}
      ${drawerMetric("Proposed allocation", pct(sessionProposedWeight(strategy.strategy_id, strategy.proposed_weight || 0)))}
      ${drawerMetric("Eligibility", elig.label)}
      ${drawerMetric("Model risk", live ? humanize(strategy.live_risk_status || strategy.risk_status) : "Not applicable")}
      ${drawerMetric("Research quality", humanize(strategy.research_quality_status || strategy.research_status))}
      ${drawerMetric("Recommended action", strategy.final_action_after_double_check || strategy.recommended_action)}
      ${drawerMetric("Rolling Sharpe", num(strategy.rolling_sharpe), cls(strategy.rolling_sharpe || 0))}
      ${drawerMetric("Volatility", pct(strategy.volatility || summary.annual_volatility || 0, 1))}
      ${drawerMetric("Current drawdown", pct(strategy.current_drawdown || drawdown.current_drawdown || 0, 1), "negative")}
      ${drawerMetric("Turnover", `${num(strategy.turnover?.annualized_turnover, 1)}x`)}
      ${drawerMetric("Cost drag", pct(strategy.transaction_cost_drag || strategy.turnover?.annualized_cost_drag || 0, 2))}
    </div>
    ${drawerChartBlock("Net cumulative performance", "drawerOverviewCumCanvas", '<span class="legend-dot net"></span> Net')}
    ${drawerChartBlock("Drawdown", "drawerOverviewDdCanvas", '<span class="legend-dot drawdown"></span> Drawdown')}
    <p class="status-muted">${elig.detail}</p>`;
    } else if (view === "performance") {
      html = `${drawerChartBlock("Gross vs net cumulative return", "drawerPerfGrossNetCanvas", '<span class="legend-dot gross"></span> Gross <span class="legend-dot net"></span> Net')}
      ${drawerChartBlock("Drawdown", "drawerPerfDrawdownCanvas", '<span class="legend-dot drawdown"></span> Drawdown')}
      ${drawerChartBlock("Rolling Sharpe (63D)", "drawerPerfRollingSharpeCanvas", '<span class="legend-dot sharpe"></span> 63D rolling')}
      <div class="drawer-metric-grid">
        ${drawerMetric("Gross Sharpe", num(strategy.gross_metrics?.sharpe || summary.sharpe))}
        ${drawerMetric("Net Sharpe", num(strategy.net_metrics?.sharpe || summary.sharpe))}
        ${drawerMetric("Max drawdown", pct(drawdown.max_drawdown || 0, 1), "negative")}
        ${drawerMetric("OOS windows", String(walk.number_of_windows || 0))}
      </div>`;
    } else if (view === "risk") {
      const factors = strategy.factor_exposure?.latest || {};
      const maxFactor = Math.max(...Object.values(factors).map((v) => Math.abs(v)), 0.01);
      html = `<div class="drawer-metric-grid">
      ${drawerMetric("VaR 99%", pct(tail.var_99 || 0, 2), "negative")}
      ${drawerMetric("ES 95%", pct(tail.expected_shortfall_95 || 0, 2), "negative")}
      ${drawerMetric("Tail 2σ days", String(tail.left_tail_2sigma_count || 0))}
      ${drawerMetric("Risk contribution", pct(strategy.risk_contribution || 0, 1))}
      ${drawerMetric("Corr. to portfolio", num(packet.comparison_vs_benchmark?.correlation))}
      ${drawerMetric("Avg |corr| others", num(packet.comparison_vs_other_strategies?.average_abs_correlation_to_others))}
    </div><h4>Factor exposure</h4><div class="mini-bars">${Object.entries(factors).slice(0, 6).map(([label, value]) => `<div><span>${humanizeFactor(label, artifact)}</span><div class="bar"><span style="width:${Math.min(100, Math.abs(value) / maxFactor * 100)}%"></span></div><strong>${num(value)}</strong></div>`).join("")}</div>`;
    } else if (view === "evidence") {
      html = `<p><strong>Hypothesis:</strong> ${strategy.hypothesis || "—"}</p>
      <p><strong>Data source:</strong> ${strategy.data_source || strategy.evidence_status || "—"}</p>
      <p><strong>Backtest period:</strong> ${strategy.backtest_evidence?.years?.toFixed(1) || "0"} years - ${summary.observations || 0} obs</p>
      <p><strong>Walk-forward:</strong> ${walk.number_of_windows || 0} windows - avg OOS Sharpe ${num(walk.average_test_sharpe)}</p>
      <p><strong>Assumptions:</strong> ${strategy.bias_controls?.lookahead_bias || "—"}</p>
      <p><strong>Limitations:</strong> ${(strategy.limitations || [strategy.bias_controls?.survivorship_bias]).filter(Boolean).join("; ") || "See research lab."}</p>`;
    } else if (view === "limits") {
      const checks = [...(strategy.risk_limit_checks || []), ...(strategy.research_quality_checks || [])];
      html = checks.length
        ? `<div class="table-viewport short"><div class="table-scroll"><table class="data-table dense"><tr><th>Metric</th><th>Current</th><th>Threshold</th><th>Util.</th><th>Status</th><th>Action</th></tr>
      ${checks.map((check) => `<tr><td>${humanizeMetricLabel(check.metric, artifact)}</td><td>${typeof check.current_value === "number" ? num(check.current_value, 3) : humanize(check.current_value)}</td><td>${typeof check.breach_threshold === "number" ? num(check.breach_threshold, 3) : humanize(check.breach_threshold)}</td><td>${check.utilization != null ? utilizationBar(check.utilization, check.status) : "—"}</td><td>${statusBadge(check.status)}</td><td class="wrap-cell">${check.action || check.required_action || "—"}</td></tr>`).join("")}</table></div></div>`
        : drawerBodyMessage("No configured risk-limit or research-quality checks for this strategy.");
    } else if (view === "decision") {
      html = `<div class="drawer-callout">${statusBadge(strategy.final_action_after_double_check)}<p>${strategyRationale(strategy)}</p></div>
      <label>Decision<textarea id="drawerDecisionNote" rows="3" placeholder="Reviewer notes"></textarea></label>
      <div class="decision-buttons compact-decision">
        <button class="modify compact-btn" data-decision="Keep">Keep</button>
        <button class="modify compact-btn" data-decision="Watch">Watch</button>
        <button class="modify compact-btn" data-decision="Reduce">Reduce</button>
        <button class="modify compact-btn" data-decision="Human Review">Human Review</button>
      </div>
      <p class="decision-footnote">Decisions recorded locally only. No execution authorized.</p>`;
  } else {
    html = drawerBodyMessage(`Unknown drawer view: ${view}.`);
  }
  content.innerHTML = html;
  if (view === "overview") {
    requestAnimationFrame(() => paintDrawerViewCharts(strategy, "overview", artifact));
  } else if (view === "performance") {
    requestAnimationFrame(() => paintDrawerViewCharts(strategy, "performance", artifact));
  }
}

function installStrategyMonitorControls(artifact) {
  const controls = ["strategySearch", "strategyAllocationFilter", "strategyRiskFilter", "strategyFamilyFilter", "strategyActionFilter"].map((id) => document.getElementById(id)).filter(Boolean);
  const apply = () => {
    const search = document.getElementById("strategySearch")?.value.trim().toLowerCase() || "";
    const allocation = document.getElementById("strategyAllocationFilter")?.value || "all";
    const risk = document.getElementById("strategyRiskFilter")?.value || "all";
    const family = document.getElementById("strategyFamilyFilter")?.value || "all";
    const action = document.getElementById("strategyActionFilter")?.value || "all";
    let visible = 0;
    document.querySelectorAll("#monitorTable tr[data-strategy]").forEach((row) => {
      const show = (!search || row.dataset.search.includes(search))
        && (allocation === "all" || row.dataset.allocated === allocation)
        && (risk === "all" || row.dataset.risk === risk)
        && (family === "all" || row.dataset.family === family)
        && (action === "all" || row.dataset.action.includes(action));
      row.hidden = !show;
      visible += show ? 1 : 0;
    });
    const allocated = artifact.strategies.filter((strategy) => strategy.current_weight > 0).length;
    const openReviews = countOpenDecisionReviews(artifact, localDecisionEvents);
    document.getElementById("monitorSummary").innerHTML = `<span><strong>${visible}</strong> visible</span><span><strong>${allocated}</strong> allocated</span><span><strong>${openReviews}</strong> open reviews</span>`;
  };
  controls.forEach((control) => control.addEventListener(control.tagName === "INPUT" ? "input" : "change", apply));
  apply();
}

function metricTableRows(packet, strategy) {
  const summary = packet.summary_statistics || {};
  const distribution = packet.distribution_shape || {};
  const tail = packet.tail_risk || {};
  const drawdown = packet.drawdown_behavior || {};
  const stability = packet.time_stability || {};
  const benchmark = packet.comparison_vs_benchmark || {};
  return [
    ["Summary", "Annual return / volatility", `${pct(summary.annual_return || 0, 2)} / ${pct(summary.annual_volatility || 0, 2)}`, "Judge return against the risk budget."],
    ["Summary", "Sharpe / Sortino / Calmar", `${num(summary.sharpe)} / ${num(summary.sortino)} / ${num(summary.calmar)}`, "Three views of risk-adjusted performance."],
    ["Summary", "Win rate / payoff ratio", `${pct(summary.win_rate || 0, 1)} / ${num(summary.payoff_ratio)}`, "A high hit rate can still hide large losses."],
    ["Distribution", "Skew / excess kurtosis", `${num(distribution.skewness)} / ${num(distribution.excess_kurtosis)}`, "Negative skew and fat tails require tighter limits."],
    ["Tail", "VaR 95 / ES 95", `${pct(tail.var_95 || 0, 2)} / ${pct(tail.expected_shortfall_95 || 0, 2)}`, "ES estimates loss after VaR is breached."],
    ["Drawdown", "Max / current drawdown", `${pct(drawdown.max_drawdown || 0, 2)} / ${pct(drawdown.current_drawdown || 0, 2)}`, "Distinguish historic failure from current pain."],
    ["Drawdown", "Max duration / episodes", `${drawdown.max_drawdown_duration_days || 0} days / ${drawdown.drawdown_episode_count || 0}`, "How long capital can remain underwater."],
    ["Stability", "63D rolling Sharpe latest / min", `${num(stability["63d"]?.latest_rolling_sharpe)} / ${num(stability["63d"]?.min_rolling_sharpe)}`, "Checks recent decay and worst rolling period."],
    ["Stability", "252D positive Sharpe rate", pct(stability["252d"]?.positive_sharpe_rate || 0, 0), "Persistence across long rolling windows."],
    ["Benchmark", "Beta / correlation", `${num(benchmark.beta)} / ${num(benchmark.correlation)}`, "Tests whether alpha is disguised market beta."],
    ["Evidence", "Bias controls", strategy.bias_controls?.lookahead_bias || "Not documented", "Every allocation requires defensible evidence."],
  ];
}

function openStrategyReview(strategy, artifact) {
  if (!strategy) return;
  activeStrategy = strategy;
  activeArtifact = artifact;
  activeDrawerView = "overview";
  const drawer = document.getElementById("strategyDrawer");
  document.getElementById("drawerStrategyId").textContent = strategy.strategy_id;
  document.getElementById("drawerStrategyName").textContent = strategy.name;
  document.getElementById("drawerStrategyMeta").textContent = `${strategy.strategy_type} - ${strategy.backtest_evidence?.data_source || "proxy data"} - ${positionSummary(strategy)}`;
  drawer?.classList.remove("collapsed");
  renderDrawerView(strategy, "overview", artifact);
}

function installStrategyDrawerControls(artifact) {
  document.getElementById("closeStrategyDrawer")?.addEventListener("click", () => {
    document.getElementById("strategyDrawer")?.classList.add("collapsed");
    resetDrawerView();
  });
  document.querySelectorAll("#drawerTabs .drawer-tab").forEach((button) => {
    button.addEventListener("click", () => renderDrawerView(activeStrategy, button.dataset.drawerView, activeArtifact));
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

function loadLocalDecisionEvents() {
  try {
    localDecisionEvents = JSON.parse(localStorage.getItem("riskManagerDecisionEvents") || "[]");
  } catch {
    localDecisionEvents = [];
  }
}

function renderReportDecisionLog(artifact) {
  renderDecisionLog(artifact, true);
}

function renderDecisionLog(artifact, full = false) {
  const workflowEvents = artifact.decision_workflow?.audit_trail || [];
  const events = [...workflowEvents, ...localDecisionEvents].sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)));
  const header = full
    ? "<tr><th>Time</th><th>Actor</th><th>Event</th><th>Decision</th><th>Note</th><th>Conditions</th><th>Execution authorized</th></tr>"
    : "<tr><th>Time</th><th>Actor</th><th>Event</th><th>Note</th></tr>";
  document.getElementById("decisionLog").innerHTML = header +
    events.map((event) => full
      ? `<tr>
        <td>${escapeHtml(event.timestamp)}</td>
        <td>${escapeHtml(event.actor)}</td>
        <td>${statusBadge(event.event)}</td>
        <td>${escapeHtml(event.event)}</td>
        <td class="wrap-cell">${escapeHtml(event.note)}</td>
        <td class="wrap-cell">${escapeHtml(event.conditions || "—")}</td>
        <td>${event.execution_authorized ? "Yes" : "No"}</td>
      </tr>`
      : `<tr><td>${escapeHtml(event.timestamp)}</td><td>${escapeHtml(event.actor)}</td><td>${statusBadge(event.event)}</td><td class="wrap-cell">${escapeHtml(event.note)}</td></tr>`).join("");
}

async function recordDecision(artifact, action) {
  const reviewer = document.getElementById("decisionReviewer").value.trim()
    || document.getElementById("reportDecisionReviewer")?.value?.trim()
    || "";
  const note = document.getElementById("decisionNote").value.trim()
    || document.getElementById("reportDecisionNote")?.value?.trim()
    || "";
  if (!reviewer || !note) {
    document.getElementById("decisionAuthorityStatus").textContent = "Reviewer and decision note are required before recording a human decision.";
    return;
  }
  const unchanged = proposalIsUnchanged(artifact, proposalSession.weights);
  if (!proposalSession.simulation && !unchanged) {
    const simulated = await runSimulation(artifact);
    if (!simulated || !proposalSession.simulation) {
      document.getElementById("decisionAuthorityStatus").textContent = "Cannot record a decision until a valid simulation is available.";
      return;
    }
  }
  const blockers = (proposalSession.simulation?.checks || []).filter((check) => check.status === "breach");
  const gateBlockers = (proposalSession.simulation?.proposalGates || []).filter((gate) => gate.status === "breach");
  if (action === "Approved for execution review" && (blockers.length || gateBlockers.length)) {
    document.getElementById("decisionAuthorityStatus").textContent = `Approval blocked by ${blockers.length + gateBlockers.length} hard simulation or proposal gate checks. Modify or reject the proposal. Human approval does not authorize execution.`;
    return;
  }
  const event = {
    timestamp: new Date().toISOString(),
    actor: reviewer,
    event: action,
    note,
    conditions: document.getElementById("decisionConditions")?.value?.trim() || document.getElementById("reportDecisionConditions")?.value?.trim() || "",
    execution_authorized: false,
    simulated_weights: proposalSession.weights,
    simulation: proposalSession.simulation ? {
      turnover: proposalSession.simulation.turnover,
      estimated_cost: proposalSession.simulation.estimatedCost,
      hard_breaches: blockers.map((check) => check.metric),
    } : null,
  };
  localDecisionEvents.push(event);
  localStorage.setItem("riskManagerDecisionEvents", JSON.stringify(localDecisionEvents));
  renderDecisionLog(artifact, true);
  renderDailyReport(artifact);
  document.getElementById("decisionAuthorityStatus").textContent = `${action} recorded by ${reviewer}. No trade was executed; execution authorization remains disabled.`;
}

function latestHumanDecision() {
  return localDecisionEvents.at(-1) || null;
}

function reportNavEstimate(artifact) {
  const marks = artifact.intraday_marks || {};
  const cum = metricNumeric(operatingPnlMetric(artifact, "cumulative_return")) ?? artifact.portfolio_series?.cumulative_return?.at(-1) ?? 0;
  const daily = metricNumeric(operatingPnlMetric(artifact, "daily_return")) ?? artifact.portfolio_series?.returns?.at(-1) ?? 0;
  const nav = marks.estimated_model_nav ?? artifact.initial_capital * (1 + cum);
  const dailyPnl = marks.estimated_intraday_pnl ?? daily * artifact.initial_capital;
  return { nav, dailyPnl, cumPnl: cum * artifact.initial_capital, cumReturn: cum, dailyReturn: daily };
}

function renderReportStatusStrip(artifact) {
  const el = document.getElementById("reportStatusStrip");
  if (!el) return;
  const proxyState = deriveCanonicalProxyDataState(artifact);
  const est = reportNavEstimate(artifact);
  const openReviews = countOpenDecisionReviews(artifact, localDecisionEvents);
  const issueCounts = countIssueCategories(artifact);
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  el.innerHTML = `
    <span>Report date <strong>${artifact.as_of_date || "n/a"}</strong></span>
    <span>Current Model NAV <strong>${money(est.nav)}</strong></span>
    <span>Daily PnL <strong class="${cls(est.dailyReturn)}">${money(est.dailyPnl)}</strong></span>
    <span>Operating PnL <strong class="${cls(est.cumReturn)}">${money(est.cumPnl)}</strong></span>
    <span>Proposal <strong>${escapeHtml(proposal.status)}</strong></span>
    <span>Current-model issues <strong>${issueCounts.current_model_issues}</strong></span>
    <span>Breached controls <strong class="${issueCounts.breached_controls ? "negative" : ""}">${issueCounts.breached_controls}</strong></span>
    <span>Research quality <strong>${issueCounts.research_quality}</strong></span>
    <span>Data quality <strong>${issueCounts.data_quality}</strong></span>
    <span>Governance <strong>${issueCounts.governance}</strong></span>
    <span>Open reviews <strong>${openReviews}</strong></span>
    <span>Data state <strong class="${proxyState.tone || ""}">${proxyState.label}</strong></span>
    <span>Execution <strong>Not authorized</strong></span>`;
}

function renderReportWorkflow(artifact) {
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  const workflowView = deriveWorkflowPresentation(artifact, proposal);
  document.getElementById("governanceFlow").innerHTML = workflowView.stages.map((stage) => `
    <div class="governance-stage">
      <strong>${stage.title}</strong>
      ${statusBadge(stage.statusLabel || stage.status)}
      <span>Owner: ${escapeHtml(stage.owner || "n/a")}</span>
      <span>Next: ${escapeHtml(stage.next || "Awaiting prior stage")}</span>
    </div>`).join("");
  const lastDecision = latestHumanDecision();
  const humanDecisionLabel = proposal.status === "No rebalance proposed"
    ? (lastDecision?.event || "Monitoring acknowledgement only")
    : (lastDecision?.event || "Not recorded");
  document.getElementById("reportHumanDecision").innerHTML = `
    <p><strong>Proposal status:</strong> ${statusBadge(proposal.status)} — ${proposal.detail}</p>
    <p><strong>Human approval status:</strong> ${escapeHtml(humanDecisionLabel)}</p>
    <p><strong>Execution authorization:</strong> Not authorized</p>
    <label>Reviewer<input id="reportDecisionReviewer" placeholder="Name or role" value="${escapeHtml(document.getElementById("decisionReviewer")?.value || "")}"></label>
    <label>Decision
      <select id="reportDecisionAction">
        <option value="Approved for execution review">Approve</option>
        <option value="Modification requested">Modify</option>
        <option value="Proposal rejected">Reject</option>
      </select>
    </label>
    <label>Rationale<textarea id="reportDecisionNote" rows="3" placeholder="Document rationale and conditions"></textarea></label>
    <label>Conditions<input id="reportDecisionConditions" placeholder="Optional approval conditions"></label>
    <label>Next monitoring action<input id="reportDecisionFollowUp" placeholder="What to monitor next"></label>
    <div class="decision-buttons compact-decision">
      <button type="button" class="approve compact-btn" id="reportRecordDecision">Record Decision</button>
    </div>`;
  document.getElementById("reportRecordDecision")?.addEventListener("click", () => {
    document.getElementById("decisionReviewer").value = document.getElementById("reportDecisionReviewer").value;
    document.getElementById("decisionNote").value = [
      document.getElementById("reportDecisionNote").value,
      document.getElementById("reportDecisionConditions").value ? `Conditions: ${document.getElementById("reportDecisionConditions").value}` : "",
      document.getElementById("reportDecisionFollowUp").value ? `Follow-up: ${document.getElementById("reportDecisionFollowUp").value}` : "",
    ].filter(Boolean).join(" | ");
    recordDecision(artifact, document.getElementById("reportDecisionAction").value).then(() => renderDailyReport(artifact));
  });
}

function renderReportIssuesTable(artifact) {
  const el = document.getElementById("reportIssuesTable");
  if (!el) return;
  const checks = groupedCurrentPortfolioIssues(artifact).concat(groupedCanonicalIssues(artifact, "research")).slice(0, 20);
  el.innerHTML = `<tr><th>Subject</th><th>Scope</th><th>Issue</th><th>Current</th><th>Threshold</th><th>Severity</th><th>Action</th><th>Review</th></tr>` +
    checks.map((check) => `<tr>
      <td class="wrap-cell">${escapeHtml(formatIssueSubjectLabel(check, artifact))}</td>
      <td>${humanize(check.scope)}</td>
      <td>${humanizeMetricLabel(check.metric, artifact)}</td>
      <td class="col-num">${typeof check.current_value === "number" ? num(check.current_value, 3) : humanize(check.current_value)}</td>
      <td class="col-num">${typeof check.breach_threshold === "number" ? num(check.breach_threshold, 3) : humanize(check.breach_threshold)}</td>
      <td class="col-status">${statusBadge(check.status)}</td>
      <td class="wrap-cell">${escapeHtml(check.required_action || check.action || "Review")}</td>
      <td>${humanize(check.review_status || "Open")}</td>
    </tr>`).join("") || `<tr><td colspan="8">No active strategy alerts or limit issues on current model scope.</td></tr>`;
}

function renderReportRebalancePanel(artifact) {
  const el = document.getElementById("reportRebalancePanel");
  if (!el) return;
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  if (proposal.status === "No rebalance proposed") {
    el.innerHTML = `<div class="rebalance-summary-card">
      <p><strong>No rebalance proposed</strong></p>
      <p>Current allocation remains under monitoring</p>
      <p>Transaction cost: ${money(0)}</p>
      <p>Human decision status: ${escapeHtml(latestHumanDecision()?.event || "Not recorded")}</p>
      <p>Execution authorization: Not authorized</p>
    </div>`;
    return;
  }
  if (proposal.status === "Simulation required") {
    el.innerHTML = `<div class="rebalance-summary-card">
      <p><strong>Simulation required</strong></p>
      <p>Proposed weights differ from current allocation. Run simulation before human review.</p>
      <p>Human decision status: ${escapeHtml(latestHumanDecision()?.event || "Not recorded")}</p>
      <p>Execution authorization: Not authorized</p>
    </div>`;
    return;
  }
  const rows = (artifact.strategies || []).filter((s) => Math.abs((proposalSession.weights[s.strategy_id] || 0) - (s.current_weight || 0)) > 1e-6);
  el.innerHTML = `<div class="rebalance-summary-card">
    <p><strong>${proposal.status}</strong> - ${proposal.detail}</p>
    <p>Estimated cost: ${money(proposalSession.simulation.estimatedCost || 0)} - Turnover: ${pct(proposalSession.simulation.turnover || 0, 1)}</p>
    <p>Gate status: ${statusBadge(proposal.tone === "breach" ? "blocked" : proposal.tone === "warning" ? "watch" : "clear")}</p>
    <p>Human decision: ${escapeHtml(latestHumanDecision()?.event || "Not recorded")} - Execution: Not authorized</p>
  </div>
  <div class="table-viewport short"><div class="table-scroll"><table class="data-table dense"><tr><th>Strategy</th><th>Current</th><th>Proposed</th><th>Change</th><th>Est. cost</th></tr>
    ${rows.map((s) => {
      const current = s.current_weight || 0;
      const proposed = proposalSession.weights[s.strategy_id] || 0;
      const change = proposed - current;
      return `<tr><td>${escapeHtml(s.name)}</td><td>${pct(current)}</td><td>${pct(proposed)}</td><td class="${cls(change)}">${pct(change)}</td><td>${money(Math.abs(change) * artifact.initial_capital * 0.0005)}</td></tr>`;
    }).join("")}
  </table></div></div>`;
}

function renderReportMonitoringPanel(artifact) {
  const el = document.getElementById("reportMonitoringPanel");
  if (!el) return;
  const recs = artifact.recommendations || [];
  const dq = artifact.data_quality || {};
  el.innerHTML = `
    <p><strong>Next-day watchlist</strong></p>
    ${recs.slice(0, 4).map((rec) => `<p>${statusBadge(rec.priority)} ${escapeHtml(humanizeUserFacingText(rec.action, artifact))}</p>`).join("") || emptyState("No watchlist items.")}
    <p><strong>Market events to monitor</strong></p>
    ${(artifact.market_monitor || []).slice(0, 4).map((row) => `<p>${row.ticker}: ${escapeHtml(row.risk_interpretation || "Monitor proxy move")}</p>`).join("") || emptyState("No market proxy warnings.")}
    <p><strong>Data issues to verify</strong></p>
    <p>Missing series: ${(dq.missing_return_series || []).length} - Common window: ${dq.common_portfolio_risk_window_observations || 0} obs</p>
    <p><strong>Follow-up owners</strong></p>
    <p>Risk manager - Portfolio manager - Data operations (prototype local review)</p>`;
}

function renderReportDataQualityPanel(artifact) {
  const el = document.getElementById("reportDataQualityPanel");
  if (!el) return;
  const dq = artifact.data_quality || {};
  const proxy = deriveCanonicalProxyDataState(artifact);
  const intraday = artifact.intraday_marks?.data_quality || dq.intraday || {};
  el.innerHTML = `
    <p><strong>Market proxy source:</strong> yfinance research proxy (${dq.source || "artifact"})</p>
    <p><strong>Latest observation:</strong> ${artifact.live_market_as_of || intraday.latest_observation_ts_et || dq.latest_strategy_end || "n/a"}</p>
    <p><strong>Retrieval time:</strong> ${artifact.build_metadata?.data_retrieved_at || artifact.live_refreshed_at || "n/a"}</p>
    <p><strong>Data state:</strong> ${proxy.label} — ${proxy.detail}</p>
    <p><strong>Missing / stale tickers:</strong> ${(intraday.missing_tickers || []).join(", ") || "None flagged"} / ${(intraday.stale_tickers || []).join(", ") || "None flagged"}</p>
    <p><strong>Disclosure:</strong> ${escapeHtml(artifact.data_classification?.disclosure || "Prototype model portfolio; not live positions or fills.")}</p>
    <p><strong>Model limitations:</strong> ${escapeHtml(dq.important_note || "Operating-period metrics may be unavailable with short history.")}</p>
    <p><strong>Audit limitation:</strong> Decision events in this prototype are stored in browser localStorage only.</p>`;
}

function buildDailyMemoSections(artifact) {
  const est = reportNavEstimate(artifact);
  const allocated = (artifact.strategies || []).filter((s) => s.current_weight > 0);
  const winners = allocated.filter((s) => (s.daily_pnl || 0) > 0).sort((a, b) => b.daily_pnl - a.daily_pnl);
  const losers = allocated.filter((s) => (s.daily_pnl || 0) < 0).sort((a, b) => a.daily_pnl - b.daily_pnl);
  const issues = groupedCurrentPortfolioIssues(artifact).slice(0, 5);
  const proposal = deriveProposalStatus(artifact, proposalSession.simulation, proposalSession.weights);
  const lastDecision = latestHumanDecision();
  const regimeNote = (artifact.market_monitor || []).slice(0, 3).map((row) => `${row.ticker} ${pct(row.daily_return || 0, 2)}`).join("; ");
  const allocationConclusion = proposal.status === "No rebalance proposed"
    ? "No rebalance proposed. Current allocation remains under monitoring."
    : proposal.status === "Simulation required"
      ? "Weights differ from current allocation. Simulation required before human review."
      : `${proposal.status}. ${proposal.detail}${proposalSession.simulation ? ` Estimated transaction cost ${money(proposalSession.simulation.estimatedCost || 0)}.` : ""}`;
  return [
    ["Executive risk conclusion", `${proposal.status}. ${proposal.detail}`],
    ["Portfolio performance", `Current Model NAV ${money(est.nav)}; daily PnL ${money(est.dailyPnl)}; operating cumulative PnL ${money(est.cumPnl)}.`],
    ["Main contributors and detractors", `Contributors: ${winners.slice(0, 3).map((s) => `${s.name} ${money(s.daily_pnl)}`).join(", ") || "none"}. Detractors: ${losers.slice(0, 3).map((s) => `${s.name} ${money(s.daily_pnl)}`).join(", ") || "none"}.`],
    ["Market and proxy-regime context", regimeNote || "Market proxy monitor loaded from validated artifact / intraday snapshot."],
    ["Current portfolio, factor, and correlation issues", issues.map((check) => `${formatIssueSubjectLabel(check, artifact)}: ${humanizeMetricLabel(check.metric, artifact)} (${check.status})`).join("; ") || "No grouped current-model issues beyond routine monitoring."],
    ["Proposed allocation or no-rebalance conclusion", allocationConclusion],
    ["Human decision and conditions", lastDecision ? `${lastDecision.event} by ${lastDecision.actor}: ${lastDecision.note}` : "Human decision not yet recorded in this session."],
    ["Next monitoring actions", (artifact.recommendations || []).slice(0, 3).map((rec) => humanizeUserFacingText(rec.action, artifact)).join("; ") || "Continue operating-period monitoring and proxy-data quality checks."],
    ["Data quality and limitations", `${formatMonitoringState(artifact).stripDataState}. ${artifact.data_classification?.disclosure || ""}`],
  ];
}

function renderDailyMemo(artifact) {
  const sections = buildDailyMemoSections(artifact);
  const html = sections.map(([title, body]) => `<section><h3>${escapeHtml(title)}</h3><p>${escapeHtml(humanizeUserFacingText(body, artifact))}</p></section>`).join("");
  document.getElementById("dailyRiskMemo").innerHTML = html;
  document.getElementById("generatedReport").innerHTML = `
    <header class="report-print-header">
      <h2>Daily Risk Report — ${artifact.as_of_date}</h2>
      <p>Prototype model portfolio - Research proxy data - Not live positions or fills</p>
      ${reportFrozenAt ? `<p>Frozen at ${reportFrozenAt}</p>` : ""}
    </header>${html}`;
  const caption = document.getElementById("reportPreviewCaption");
  if (caption) caption.textContent = reportFrozenAt ? `Frozen ${reportFrozenAt}` : "Live preview from current artifact";
}

function renderDailyReport(artifact) {
  renderReportStatusStrip(artifact);
  renderDailyMemo(artifact);
  renderReportWorkflow(artifact);
  renderReportIssuesTable(artifact);
  renderReportRebalancePanel(artifact);
  renderReportDecisionLog(artifact);
  renderReportMonitoringPanel(artifact);
  renderReportDataQualityPanel(artifact);
}

async function generateDailyReport(artifact) {
  reportFrozenAt = new Date().toLocaleString();
  renderDailyReport(artifact);
  setActiveTab("Daily Risk Report / Decision Log");
}

function downloadBlob(filename, type, content) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function installOperationalControls(artifact) {
  loadLocalDecisionEvents();
  renderDecisionLog(artifact);
  document.getElementById("useSystemProposal").addEventListener("click", async () => {
    loadSystemProposalSession(artifact);
    await runSimulation(artifact);
  });
  document.getElementById("resetWeights").addEventListener("click", () => {
    initProposalSession(artifact);
    refreshProposalStatusViews(artifact);
  });
  document.getElementById("simulateWeights").addEventListener("click", () => runSimulation(artifact));
  const rebalanceJump = document.getElementById("openRebalanceTab");
  if (rebalanceJump) rebalanceJump.addEventListener("click", () => setActiveTab("Allocation & Rebalance"));
  document.getElementById("approveDecision").addEventListener("click", () => recordDecision(artifact, "Approved for execution review"));
  document.getElementById("modifyDecision").addEventListener("click", () => recordDecision(artifact, "Modification requested"));
  document.getElementById("rejectDecision").addEventListener("click", () => recordDecision(artifact, "Proposal rejected"));
  document.getElementById("generateReport").addEventListener("click", () => generateDailyReport(artifact));
  document.getElementById("addReportDecisionNote")?.addEventListener("click", () => {
    setActiveTab("Daily Risk Report / Decision Log");
    document.getElementById("reportDecisionNote")?.focus();
  });
  document.getElementById("printReport").addEventListener("click", async () => {
    if (!reportFrozenAt) generateDailyReport(artifact);
    setTimeout(() => window.print(), 100);
  });
  document.getElementById("exportJson").addEventListener("click", () => downloadBlob(`risk-decision-${artifact.as_of_date}.json`, "application/json", JSON.stringify({
    as_of_date: artifact.as_of_date,
    simulated_weights: proposalSession.weights,
    simulation: proposalSession.simulation,
    decisions: localDecisionEvents,
    execution_authorized: false,
  }, null, 2)));
  document.getElementById("exportCsv").addEventListener("click", () => {
    const rows = [["strategy_id", "strategy", "current_weight", "target_weight", "change", "estimated_cost"]];
    (artifact.strategies || []).forEach((strategy) => {
      const target = proposalSession.weights[strategy.strategy_id] || 0;
      const change = target - (strategy.current_weight || 0);
      rows.push([strategy.strategy_id, strategy.name, strategy.current_weight || 0, target, change, Math.abs(change) * artifact.initial_capital * .0005]);
    });
    downloadBlob(`allocation-simulation-${artifact.as_of_date}.csv`, "text/csv", rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n"));
  });
}

function operationalPanel(tab) {
  return document.querySelector(`[data-tab-panel="${tab}"]`);
}

function buildOperationalProductionShell() {
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    if (!tabs.includes(panel.dataset.tabPanel)) panel.remove();
  });
  document.getElementById("intradayRefreshStrip")?.remove();
  document.getElementById("riskDrawer")?.remove();

  operationalPanel("Portfolio Command Center").innerHTML = `
    <section id="combinedPortfolio" class="operational-page">
      <div id="operationalKpis"></div>
      <article class="panel v2-panel"><div class="panel-title">Combined Portfolio - Date-Effective ACTIVE Membership</div><div id="combinedMembership"></div></article>
      <section class="v2-grid command-v2-grid">
        <article class="panel v2-panel panel-span-6"><div class="panel-title">Current Strategy Allocation</div><div id="combinedAllocation" class="allocation-bars compact-bars"></div></article>
        <article class="panel v2-panel panel-span-3"><div class="panel-title">Top Contributors</div><table class="data-table dense" id="operationalContributors"></table></article>
        <article class="panel v2-panel panel-span-3"><div class="panel-title">Bottom Detractors</div><table class="data-table dense" id="operationalDetractors"></table></article>
        <article class="panel v2-panel panel-span-12"><div class="panel-title">Current Holdings Aggregated Across Underlying Strategies</div><div class="table-viewport"><div class="table-scroll"><table class="data-table dense sticky-head" id="combinedHoldings"></table></div></div></article>
        <article class="panel v2-panel panel-span-12"><div class="panel-title">Membership-Change Log</div><table class="data-table dense" id="membershipLog"></table></article>
      </section>
    </section>`;

  operationalPanel("Strategy Monitor").innerHTML = `
    <section class="operational-page">
      <article class="panel v2-panel"><div class="panel-title">Current Operational Strategy Registry</div>
        <p class="status-muted">Executed ACTIVE sleeves plus prospectively approved membership. Select a row for operational detail.</p>
        <div class="table-viewport"><div class="table-scroll"><table class="data-table dense sticky-head" id="operationalStrategies"></table></div></div>
      </article>
    </section>`;

  operationalPanel("Daily Performance").innerHTML = `
    <section class="operational-page">
      <article class="panel v2-panel"><div class="panel-title">Combined Portfolio Daily Performance</div><canvas id="operationalNavCanvas" width="900" height="260"></canvas></article>
      <article class="panel v2-panel"><div class="table-viewport"><div class="table-scroll"><table class="data-table dense sticky-head" id="dailyPortfolioLedger"></table></div></div></article>
      <article class="panel v2-panel"><div class="panel-title">Latest Strategy Daily Performance</div><div class="table-viewport"><div class="table-scroll"><table class="data-table dense sticky-head" id="dailyStrategyLedger"></table></div></div></article>
    </section>`;

  operationalPanel("Trade Log").innerHTML = `
    <section class="operational-page">
      <article class="panel v2-panel"><div class="monitor-heading"><div class="panel-title">Simulated Trade Log - NO LIVE FILL - <span id="tradeLogCount"></span></div>
        <div class="monitor-controls"><input id="tradeDateFrom" type="date"><input id="tradeDateTo" type="date"><input id="tradeStrategy" placeholder="Strategy"><input id="tradeTicker" placeholder="Ticker"><select id="tradeAction"><option value="">All actions</option><option>BUY</option><option>SELL</option><option>SHORT</option><option>COVER</option></select></div></div>
        <div class="table-viewport"><div class="table-scroll"><table class="data-table dense sticky-head" id="operationalTradeLog"></table></div></div>
      </article>
    </section>`;

  operationalPanel("Correlation & Diversification").innerHTML = `
    <section class="operational-page correlation-layout">
      <article class="panel v2-panel"><div class="panel-title">Research Correlation - Accepted Historical Returns</div><p class="empty-state">Research correlation remains separate and is not loaded into the operational production bundle.</p></article>
      <article class="panel v2-panel"><div class="panel-title">Shadow-Live Correlation - Operational Returns Only</div><div id="operationalCorrelation"></div></article>
    </section>`;

  operationalPanel("Backtesting & Research Lab").innerHTML = `
    <section class="operational-page">
      <article class="panel v2-panel"><div class="panel-title">Strategy Detail - Operational Source</div><div id="operationalStrategyDetail"><p class="empty-state">Select a current strategy from Strategies.</p></div></article>
    </section>`;
}

function canonicalOperationalArtifact(bundle) {
  if (!bundle?.shadow_live) throw new Error("Canonical shadow-live operational bundle is unavailable.");
  return {
    ...bundle,
    as_of_date: bundle.market_as_of,
    portfolio_series_live: bundle.portfolio_series_live,
    shadow_live: bundle.shadow_live,
  };
}

function latestPortfolioRow(shadow) {
  return (shadow.portfolio_ledger || []).at(-1) || {};
}

function currentEffectiveCount(shadow) {
  return Number(latestPortfolioRow(shadow).active_count || shadow.previous_active_count || 0);
}

function currentEffectiveWeight(shadow) {
  return Number(latestPortfolioRow(shadow).equal_strategy_weight || (currentEffectiveCount(shadow) ? 1 / currentEffectiveCount(shadow) : 0));
}

function operationalStrategyRows(shadow) {
  const executed = shadow.strategy_summary || [];
  const executedIds = new Set(executed.map((row) => row.strategy_id));
  const pending = Object.entries(shadow.strategy_details || {})
    .filter(([id]) => !executedIds.has(id))
    .map(([strategy_id, details]) => ({
      strategy_id,
      strategy_name: details.name || strategy_id,
      data_status: "PENDING_EFFECTIVE_DATE",
      validation_status: details.validation_status,
      membership_effective_date: details.membership_effective_date,
      sleeve_weight: 1 / Number(shadow.current_active_count || 1),
      daily_pnl: null,
      cumulative_pnl: null,
      cumulative_return: null,
      long_count: 0,
      short_count: 0,
      latest_signal_date: null,
    }));
  return [...executed, ...pending];
}

function renderOperationalHeader(artifact) {
  const shadow = artifact.shadow_live;
  const latest = latestPortfolioRow(shadow);
  document.getElementById("topbarMeta").innerHTML = `
    <span class="mode-badge">COMBINED PORTFOLIO</span>
    <span>As-of <strong>${escapeHtml(artifact.market_as_of)}</strong></span>
    <span>Current N <strong>${currentEffectiveCount(shadow)}</strong></span>
    <span>Equal sleeve <strong>${pct(currentEffectiveWeight(shadow), 4)}</strong></span>
    <span>NAV <strong>${money(latest.ending_nav)}</strong></span>`;
  document.getElementById("secondaryStatusStrip").innerHTML = `
    <span>RAW DATA SIGNAL RUNNER</span><span>RESEARCH ONLY</span><span>LIVE ALLOCATION 0%</span><span>EXECUTION DISABLED</span><span>NO LIVE FILL</span>`;
}

function renderOperationalCommandCenter(artifact) {
  const shadow = artifact.shadow_live;
  const latest = latestPortfolioRow(shadow);
  const cumulativeCost = (shadow.portfolio_ledger || []).reduce((sum, row) => sum + Number(row.transaction_cost || 0), 0);
  const alerts = shadow.alerts || [];
  document.getElementById("operationalKpis").innerHTML = compactKpiStrip([
    ["Continuous NAV", money(latest.ending_nav), `Since ${artifact.start_date}`, "positive"],
    ["Latest Net P&L", money(latest.net_pnl), latest.date || "", cls(latest.net_pnl)],
    ["Cumulative Net P&L", money(latest.cumulative_pnl), pct(latest.cumulative_return, 3), cls(latest.cumulative_pnl)],
    ["Transaction Costs", money(cumulativeCost), "Cumulative simulated cost", "warning-text"],
    ["Current Drawdown", pct(latest.current_drawdown, 3), "Combined Portfolio", "negative"],
    ["Current Membership", `N=${currentEffectiveCount(shadow)}`, `1/N = ${pct(currentEffectiveWeight(shadow), 4)}`, ""],
    ["Latest Signal", shadow.latest_valid_target_position_date || "n/a", "Target-position snapshot", ""],
    ["Latest Execution", shadow.latest_simulated_execution_date || "pending", `${shadow.trade_log_row_count || 0} simulated trades`, ""],
    ["Data Status", `${shadow.successful_strategy_count}/${shadow.configured_strategy_count}`, `${shadow.partial_strategy_count} partial - ${shadow.unavailable_strategy_count} unavailable - ${alerts.length} alerts`, ""],
  ]);
  document.getElementById("combinedMembership").innerHTML = `
    <div class="research-summary-strip">
      <span>Portfolio name <strong>Combined Portfolio</strong></span><span>Total research allocation <strong>100%</strong></span>
      <span>Live allocation <strong>0%</strong></span><span>Gross / net exposure <strong>${num(latest.gross_exposure, 2)} / ${num(latest.net_exposure, 2)}</strong></span>
      <span>Long / short exposure <strong>${num(latest.long_exposure, 2)} / ${num(latest.short_exposure, 2)}</strong></span>
    </div>
    <p><strong>Date-effective membership:</strong> before ${escapeHtml(shadow.membership_effective_date)}, N=${shadow.previous_active_count} at ${pct(shadow.previous_equal_weight, 2)} each. From ${escapeHtml(shadow.membership_effective_date)}, approved N=${shadow.current_active_count} at ${pct(shadow.current_equal_weight, 4)} each.</p>
    <p><strong>Pending WQ_ALPHA_018 execution:</strong> ${(shadow.pending_targets || []).filter((row) => row.strategy_id === "WQ_ALPHA_018").length} target rows; no fills or trades before a valid effective-date open.</p>`;
  const rows = shadow.strategy_summary || [];
  const allocation = document.getElementById("combinedAllocation");
  allocation.innerHTML = rows.map((row) => `<div class="allocation-bar-row"><span>${escapeHtml(row.strategy_id)}</span><div class="allocation-bar-track"><span class="allocation-bar-fill" style="width:100%"></span></div><strong>${pct(row.sleeve_weight, 2)}</strong></div>`).join("");
  const contributionRows = (items) => items.map((row) => `<tr><td>${escapeHtml(row.strategy_id)}</td><td class="${cls(row.daily_pnl)}">${money(row.daily_pnl)}</td><td>${pct(row.sleeve_weight, 2)}</td></tr>`).join("");
  document.getElementById("operationalContributors").innerHTML = `<tr><th>Strategy</th><th>Daily P&L</th><th>Weight</th></tr>${contributionRows([...rows].sort((a,b)=>b.daily_pnl-a.daily_pnl).slice(0,5))}`;
  document.getElementById("operationalDetractors").innerHTML = `<tr><th>Strategy</th><th>Daily P&L</th><th>Weight</th></tr>${contributionRows([...rows].sort((a,b)=>a.daily_pnl-b.daily_pnl).slice(0,5))}`;
  renderCombinedHoldings(shadow);
  document.getElementById("membershipLog").innerHTML = `<tr><th>Effective Date</th><th>Added</th><th>Previous N</th><th>New N</th><th>Previous Weight</th><th>New Weight</th><th>Status</th></tr>${(shadow.membership_timeline || []).map((row) => `<tr><td>${row.effective_date}</td><td>${row.strategy_added}</td><td>${row.previous_active_count}</td><td>${row.new_active_count}</td><td>${pct(row.previous_equal_weight,2)}</td><td>${pct(row.new_equal_weight,4)}</td><td>${row.validation_status}</td></tr>`).join("")}`;
}

function renderCombinedHoldings(shadow) {
  const sleeveWeight = currentEffectiveWeight(shadow);
  const byTicker = new Map();
  const latestHoldingsDate = (shadow.holdings || []).map((row) => row.date).sort().at(-1);
  (shadow.holdings || []).filter((row) => row.date === latestHoldingsDate).forEach((row) => {
    const current = byTicker.get(row.ticker) || { ticker: row.ticker, strategies: new Set(), weight: 0, notional: 0, quantity: 0 };
    current.strategies.add(row.strategy_id);
    current.weight += Number(row.target_weight || 0) * sleeveWeight;
    current.notional += Number(row.simulated_notional || 0);
    current.quantity += Number(row.simulated_quantity || 0);
    byTicker.set(row.ticker, current);
  });
  const rows = [...byTicker.values()].sort((a,b)=>Math.abs(b.weight)-Math.abs(a.weight)).slice(0,100);
  document.getElementById("combinedHoldings").innerHTML = `<caption>Latest accepted holdings date: ${escapeHtml(latestHoldingsDate || "n/a")}</caption><tr><th>Ticker</th><th>Underlying Strategies</th><th>Aggregate Weight</th><th>Aggregate Notional</th><th>Aggregate Quantity</th></tr>${rows.map((row)=>`<tr><td>${escapeHtml(row.ticker)}</td><td>${row.strategies.size}</td><td>${pct(row.weight,3)}</td><td>${money(row.notional)}</td><td>${num(row.quantity,2)}</td></tr>`).join("")}`;
}

function renderOperationalStrategies(artifact) {
  const shadow = artifact.shadow_live;
  const rows = operationalStrategyRows(shadow);
  document.getElementById("operationalStrategies").innerHTML = `<tr><th>ID</th><th>Name</th><th>Status</th><th>Effective Date</th><th>Sleeve Weight</th><th>Daily Return</th><th>Daily P&L</th><th>Cumulative Return</th><th>Cumulative P&L</th><th>Holdings</th><th>Latest Signal</th><th>Data</th><th>Action</th></tr>${rows.map((row)=>`<tr data-operational-strategy="${escapeHtml(row.strategy_id)}"><td>${escapeHtml(row.strategy_id)}</td><td>${escapeHtml(row.strategy_name)}</td><td>${row.data_status === "PENDING_EFFECTIVE_DATE" ? "APPROVED - PENDING" : "ACTIVE - EXECUTED"}</td><td>${escapeHtml(row.membership_effective_date || `Before ${shadow.membership_effective_date}`)}</td><td>${pct(row.sleeve_weight,4)}</td><td>${row.net_return == null ? "N/A" : pct(row.net_return,3)}</td><td>${row.daily_pnl == null ? "N/A" : money(row.daily_pnl)}</td><td>${row.cumulative_return == null ? "N/A" : pct(row.cumulative_return,3)}</td><td>${row.cumulative_pnl == null ? "N/A" : money(row.cumulative_pnl)}</td><td>${Number(row.long_count||0)+Number(row.short_count||0)}</td><td>${escapeHtml(row.latest_signal_date || "pending")}</td><td>${escapeHtml(row.data_status)}</td><td><button class="table-link" data-operational-strategy="${escapeHtml(row.strategy_id)}">View Details</button></td></tr>`).join("")}`;
  document.querySelectorAll("[data-operational-strategy]").forEach((node) => node.addEventListener("click", () => openOperationalStrategyDetail(node.dataset.operationalStrategy)));
}

function openOperationalStrategyDetail(strategyId) {
  const shadow = activeArtifact.shadow_live;
  const summary = operationalStrategyRows(shadow).find((row) => row.strategy_id === strategyId);
  const details = shadow.strategy_details?.[strategyId] || {};
  const latestHoldingsDate = (shadow.holdings || []).map((row) => row.date).sort().at(-1);
  const holdings = (shadow.holdings || []).filter((row) => row.strategy_id === strategyId && row.date === latestHoldingsDate);
  const trades = (shadow.trades || []).filter((row) => row.strategy_id === strategyId);
  document.getElementById("operationalStrategyDetail").innerHTML = `
    <div class="research-summary-strip"><span>ID <strong>${escapeHtml(strategyId)}</strong></span><span>Status <strong>${summary.data_status === "PENDING_EFFECTIVE_DATE" ? "APPROVED - PENDING" : "ACTIVE - EXECUTED"}</strong></span><span>Effective <strong>${escapeHtml(details.membership_effective_date || `Before ${shadow.membership_effective_date}`)}</strong></span><span>Current holdings <strong>${holdings.length}</strong></span><span>Trades <strong>${trades.length}</strong></span></div>
    <p><strong>Economic hypothesis:</strong> ${escapeHtml(details.rationale || "Stored in accepted research history; not duplicated in the operational ledger.")}</p>
    <p><strong>Signal definition:</strong> ${escapeHtml(details.formula || "Frozen registered strategy function.")}</p>
    <p><strong>Universe:</strong> CURRENT_LISTED_DIAGNOSTIC - SURVIVORSHIP_BIAS_PRESENT. <strong>Execution:</strong> NEXT_OPEN_TO_OPEN - simulated - NO LIVE FILL.</p>
    <p><strong>Shadow-live:</strong> daily P&L ${summary.daily_pnl == null ? "pending" : money(summary.daily_pnl)} - cumulative P&L ${summary.cumulative_pnl == null ? "pending" : money(summary.cumulative_pnl)} - data ${escapeHtml(summary.data_status)}.</p>
    <p><strong>Limitations:</strong> ${escapeHtml(details.limitations || "Research only; live allocation 0%; execution disabled.")}</p>`;
  setActiveTab("Backtesting & Research Lab");
}

function renderOperationalDailyPerformance(artifact) {
  const shadow = artifact.shadow_live;
  const ledger = shadow.portfolio_ledger || [];
  drawSingleMetricChart(document.getElementById("operationalNavCanvas"), ledger.map((row)=>row.ending_nav), { color: "#66d9ef", emptyMessage: "No completed portfolio intervals." });
  document.getElementById("dailyPortfolioLedger").innerHTML = `<tr><th>Date</th><th>Segment</th><th>Beginning NAV</th><th>Gross P&L</th><th>Cost</th><th>Net P&L</th><th>Daily Return</th><th>Ending NAV</th><th>Cumulative Return</th><th>Cumulative P&L</th><th>Drawdown</th><th>N</th><th>Weight</th></tr>${ledger.map((row)=>`<tr><td>${row.date}</td><td>${row.record_label}</td><td>${money(row.beginning_nav)}</td><td>${money(row.gross_pnl)}</td><td>${money(row.transaction_cost)}</td><td>${money(row.net_pnl)}</td><td>${pct(row.daily_return,3)}</td><td>${money(row.ending_nav)}</td><td>${pct(row.cumulative_return,3)}</td><td>${money(row.cumulative_pnl)}</td><td>${pct(row.current_drawdown,3)}</td><td>${row.active_count}</td><td>${pct(row.equal_strategy_weight,4)}</td></tr>`).join("")}`;
  const rows = shadow.strategy_summary || [];
  document.getElementById("dailyStrategyLedger").innerHTML = `<tr><th>Strategy</th><th>Interval</th><th>Daily Return</th><th>Daily P&L</th><th>Cumulative Return</th><th>Cumulative P&L</th><th>Cost</th><th>Segment</th></tr>${rows.map((row)=>`<tr><td>${row.strategy_id}</td><td>${row.open_to_open_interval}</td><td>${pct(row.net_return,3)}</td><td>${money(row.daily_pnl)}</td><td>${pct(row.cumulative_return,3)}</td><td>${money(row.cumulative_pnl)}</td><td>${money(row.transaction_cost)}</td><td>${row.record_label}</td></tr>`).join("")}`;
}

function renderOperationalTradeLog() {
  const shadow = activeArtifact.shadow_live;
  const from = document.getElementById("tradeDateFrom")?.value || "";
  const to = document.getElementById("tradeDateTo")?.value || "";
  const strategy = (document.getElementById("tradeStrategy")?.value || "").toUpperCase();
  const ticker = (document.getElementById("tradeTicker")?.value || "").toUpperCase();
  const action = document.getElementById("tradeAction")?.value || "";
  const rows = (shadow.trades || []).filter((row)=>(!from||row.execution_date>=from)&&(!to||row.execution_date<=to)&&(!strategy||row.strategy_id.includes(strategy))&&(!ticker||row.ticker.includes(ticker))&&(!action||row.action===action));
  document.getElementById("tradeLogCount").textContent = `${rows.length} rows`;
  document.getElementById("operationalTradeLog").innerHTML = `<tr><th>Date</th><th>Strategy</th><th>Ticker</th><th>Action</th><th>Previous Weight</th><th>Target Weight</th><th>Delta Weight</th><th>Quantity</th><th>Execution Price</th><th>Notional</th><th>Cost</th><th>Reason</th><th>Fill</th></tr>${rows.map((row)=>`<tr><td>${row.execution_date}</td><td>${row.strategy_id}</td><td>${row.ticker}</td><td>${row.action}</td><td>${pct(row.previous_weight,3)}</td><td>${pct(row.target_weight,3)}</td><td>${pct(row.delta_weight,3)}</td><td>${num(row.simulated_quantity,3)}</td><td>${money(row.simulated_execution_price)}</td><td>${money(row.simulated_notional)}</td><td>${money(row.transaction_cost_amount)}</td><td>${row.trade_reason}</td><td>${row.fill_status}</td></tr>`).join("")}`;
}

function renderOperationalCorrelation(artifact) {
  const correlation = artifact.shadow_live.correlation || {};
  document.getElementById("operationalCorrelation").innerHTML = `<div class="research-summary-strip"><span>Status <strong>${escapeHtml(correlation.status || "NOT ENOUGH LIVE HISTORY")}</strong></span><span>Observations <strong>${correlation.observations || 0}</strong></span><span>Minimum <strong>${correlation.minimum_observations || 20}</strong></span></div><p>${correlation.observations < correlation.minimum_observations ? "NOT ENOUGH LIVE HISTORY. Unavailable correlations are not filled with zero." : "Shadow-live correlation is available."}</p>`;
}

async function init() {
  renderTabs();
  buildOperationalProductionShell();
  document.body.classList.add("app-loading");
  const shadowBundle = await loadShadowLiveBundle();
  activeArtifact = canonicalOperationalArtifact(shadowBundle);
  renderOperationalHeader(activeArtifact);
  renderOperationalCommandCenter(activeArtifact);
  renderOperationalStrategies(activeArtifact);
  renderOperationalDailyPerformance(activeArtifact);
  renderOperationalTradeLog();
  renderOperationalCorrelation(activeArtifact);
  ["tradeDateFrom", "tradeDateTo", "tradeStrategy", "tradeTicker", "tradeAction"].forEach((id) => document.getElementById(id)?.addEventListener("input", renderOperationalTradeLog));
  document.body.classList.remove("app-loading");
}

init();
