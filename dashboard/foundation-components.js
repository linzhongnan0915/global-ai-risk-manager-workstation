/* Reusable Phase 1 institutional workstation components. */

const UI = (() => {
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

  const displayNumber = (value, options = {}) => {
    if (value == null || !Number.isFinite(Number(value))) return "Unavailable";
    const normalized = Object.is(Number(value), -0) ? 0 : Number(value);
    return normalized.toLocaleString("en-US", options);
  };
  const money = (value) => value == null ? "Unavailable" : displayNumber(value, {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  });
  const percent = (value, digits = 2) => value == null ? "Unavailable"
    : `${displayNumber(Number(value) * 100, { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
  const toneForNumber = (value) => value == null ? "unavailable" : Number(value) >= 0 ? "positive" : "negative";

  const StatusBadge = ({ label, tone = "warning", dot = false }) =>
    `<span class="status-badge ${escapeHtml(tone)}">${dot ? '<i aria-hidden="true"></i>' : ""}${escapeHtml(label)}</span>`;

  const SectionHeader = ({ title, meta = "", action = "" }) => `
    <header class="section-header"><div><strong>${escapeHtml(title)}</strong>${meta ? `<span>${escapeHtml(meta)}</span>` : ""}</div>${action}</header>`;

  const spark = (tone = "info", variant = 0) => {
    const paths = [
      "M1 19 L8 17 L15 18 L22 13 L29 15 L36 10 L43 12 L50 7 L57 9 L64 4 L71 8 L78 5 L85 11 L92 8 L99 10",
      "M1 12 L8 14 L15 9 L22 11 L29 7 L36 13 L43 10 L50 15 L57 12 L64 16 L71 11 L78 13 L85 8 L92 10 L99 5",
      "M1 7 L8 9 L15 8 L22 13 L29 11 L36 15 L43 12 L50 17 L57 13 L64 18 L71 16 L78 20 L85 17 L92 19 L99 15",
    ];
    return `<svg class="sparkline tone-${escapeHtml(tone)}" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden="true">
      <path class="spark-fill" d="${paths[variant % paths.length]} L99 22 L1 22 Z"></path><path class="spark-stroke" d="${paths[variant % paths.length]}"></path>
    </svg>`;
  };

  const MetricCard = ({ label, value, detail = "", tone = "info", status = "", values = null }) => `
    <article class="metric-card"><div class="metric-head"><span class="metric-label">${escapeHtml(label)}</span>${status ? `<b class="metric-status tone-${escapeHtml(tone)}">${escapeHtml(status)}</b>` : ""}</div>
      <div class="metric-main"><strong class="metric-value tone-${escapeHtml(tone)}">${escapeHtml(value)}</strong>${Array.isArray(values) && values.length > 1 ? spark(tone, 0) : ""}</div><span class="metric-detail">${escapeHtml(detail)}</span></article>`;

  const AlertBanner = ({ title, message }) => `
    <section class="alert-banner" role="status">${StatusBadge({ label: title, tone: "warning", dot: true })}<p>${escapeHtml(message)}</p><span class="alert-action">Human review required</span></section>`;

  const Panel = ({ title, meta = "", body, className = "", action = "" }) =>
    `<section class="panel ${escapeHtml(className)}">${SectionHeader({ title, meta, action })}${body}</section>`;

  const ChartPanel = ({ title, meta = "", canvasId, className = "" }) =>
    Panel({ title, meta, className: `chart-panel ${className}`, body: `<div class="panel-body chart-body"><canvas id="${escapeHtml(canvasId)}" width="1000" height="260"></canvas></div>` });

  const FilterBar = ({ count }) => `
    <div class="filter-bar"><button type="button" class="tool-button">All strategies</button>
      <label class="search-control"><span aria-hidden="true">&#9906;</span><input id="strategyFilter" type="search" placeholder="Search strategy" aria-label="Filter strategies" /></label>
      <select id="stateFilter" aria-label="Filter membership state"><option value="">All states</option><option value="executed">Executed</option><option value="approved_pending">Approved pending</option></select>
      <span class="filter-count" id="filterCount">${escapeHtml(count)} strategies</span><button type="button" class="icon-button" aria-label="Table settings">&#9881;</button></div>`;

  const DataTable = ({ columns, rows, rowId = "internal_id", selectedId = "" }) => `
    <div class="table-wrap"><table class="data-table"><thead><tr>${columns.map((column, index) => `<th>${escapeHtml(column.label)}${index === 0 ? '<span class="sort-indicator"> &#9650;</span>' : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((row) => `<tr class="${row[rowId] === selectedId ? "selected" : ""}" data-row-id="${escapeHtml(row[rowId])}">${columns.map((column) => `<td>${column.render ? column.render(row) : escapeHtml(row[column.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;

  const Tabs = ({ labels, active, drawer = false }) => `
    <div class="${drawer ? "drawer-tabs" : "tabs"}">${labels.map((label) => `<button type="button" class="tab ${label === active ? "active" : ""}" data-drawer-tab="${drawer ? escapeHtml(label) : ""}">${escapeHtml(label)}</button>`).join("")}</div>`;

  const DetailDrawer = () => `
    <aside class="detail-drawer" id="detailDrawer" aria-hidden="true" aria-label="Strategy detail">
      <header class="drawer-header"><div><div class="drawer-kicker">Strategy detail</div><h2 id="drawerTitle">Strategy detail</h2><p id="drawerSubtitle"></p></div>
      <button class="icon-button" id="closeDrawer" type="button" aria-label="Close strategy detail">&times;</button></header><div id="drawerTabs"></div><div class="drawer-body" id="drawerBody"></div></aside>`;

  const EmptyState = ({ title, message }) => `<div class="empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span></div>`;
  const PageHeader = ({ title, subtitle = "" }) => `<header class="page-header"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(subtitle)}</span></header>`;
  const SplitPanel = ({ main, side }) => `<div class="split-panel"><div>${main}</div><aside>${side}</aside></div>`;

  return { AlertBanner, ChartPanel, DataTable, DetailDrawer, EmptyState, FilterBar, MetricCard, PageHeader, Panel, SectionHeader, SplitPanel, StatusBadge, Tabs, displayNumber, escapeHtml, money, percent, spark, toneForNumber };
})();
