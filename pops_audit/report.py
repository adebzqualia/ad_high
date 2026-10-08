"""Write a self-contained, offline workbook review report.

All workbook-derived data is JSON-encoded and rendered with textContent by the
embedded application. The generated report makes no network requests.
"""
from __future__ import annotations

import html
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
import tempfile
import os


def _embedded_json(payload: dict) -> str:
    return (json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _public_payload(payload: dict) -> dict:
    """Exclude internal diagnostics and their reviews from the public report."""
    public = deepcopy(payload)
    findings = [item for item in public.get("anomalies", []) if not item.get("baseline", False)]
    for item in findings:
        item.pop("baseline", None)
    public["anomalies"] = findings
    visible_ids = {str(item.get("id")) for item in findings}
    if "initial_reviews" in public:
        reviews = public["initial_reviews"]
        if isinstance(reviews, dict):
            reviews = reviews.get("reviews", [])
        public["initial_reviews"] = [item for item in reviews if str(item.get("anomaly_id")) in visible_ids]
    summary = public.setdefault("summary", {})
    summary.pop("template_issue_count", None)
    summary.update(anomaly_count=len(findings),
                   by_severity=dict(Counter(item.get("severity", "info") for item in findings)),
                   countries_with_issues=len({item.get("country_id") for item in findings if item.get("country_id") is not None}))
    for country in public.get("countries", []):
        selected = [item for item in findings if str(item.get("country_id")) == str(country.get("id"))]
        country.pop("template_issue_count", None)
        country.update(anomaly_count=len(selected), by_severity=dict(Counter(item.get("severity", "info") for item in selected)))
        for sheet in country.get("sheets", []):
            names = {sheet.get(key) for key in ("name", "sent_name", "received_name") if sheet.get(key)}
            sheet["anomaly_count"] = sum(item.get("sheet") in names for item in selected)
    return public


def write_report(payload: dict, output_path: str | Path) -> Path:
    """Create one portable HTML file with its data, styles and review tools."""
    if not isinstance(payload, dict):
        raise TypeError("The report payload must be a dictionary.")
    payload = _public_payload(payload)
    data = _embedded_json(payload)
    assets = Path(__file__).resolve().parent.parent / "assets"
    css = (assets / "report.css").read_text(encoding="utf-8")
    javascript = (assets / "report.js").read_text(encoding="utf-8")
    title = html.escape(str(payload.get("title") or "Workbook quality review"), quote=True)
    document = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to report</a>
<header class="masthead">
  <div class="brand"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><div><span class="eyebrow">POPS · WORKBOOK ASSURANCE</span><div class="brand-title">POPS return review</div></div></div>
  <div class="header-actions"><span class="offline-badge"><span aria-hidden="true">●</span> Offline report</span><button id="save-report" class="button light" type="button">Save reviewed report <span aria-hidden="true">↓</span></button></div>
</header>
<div id="storage-notice" class="storage-notice" role="status" hidden></div>
<div class="workspace">
  <aside class="sidebar" aria-label="Country navigation">
    <div class="sidebar-heading"><span class="eyebrow">YOUR COUNTRIES</span><span id="country-count" class="count-chip"></span></div>
    <button id="overview-button" class="country-button overview-button active" type="button"><span class="nav-icon" aria-hidden="true">▦</span><span>Overview</span></button>
    <label class="sr-only" for="country-search">Find a country</label><input id="country-search" class="input country-search" type="search" placeholder="Find a country…" autocomplete="off">
    <div id="country-list" class="country-list"></div>
    <div class="sidebar-foot"><span class="privacy-dot" aria-hidden="true"></span><p>Everything stays on this device.<br>No workbook or review is uploaded.</p></div>
  </aside>
  <main id="main-content" tabindex="-1">
    <div class="page-heading"><div><div id="breadcrumb" class="eyebrow"></div><h1 id="view-title"></h1><div id="view-subtitle" class="muted"></div><div class="heading-shortcuts"><a class="text-button jump-link" href="#findings-heading">Go to findings <span aria-hidden="true">↓</span></a><button id="save-country-report" class="text-button" type="button" hidden>Save country report <span aria-hidden="true">↓</span></button></div></div><div id="report-meta" class="report-meta"></div></div>
    <section id="metric-grid" class="metric-grid" aria-label="Review summary"></section>
    <section class="panel filling-panel" aria-labelledby="filling-heading">
      <div class="section-heading"><div><h2 id="filling-heading">Overall filling, before and after</h2><p id="filling-scope" class="muted small"></p></div><button id="filling-help-button" class="text-button" type="button" aria-expanded="false" aria-controls="filling-help">How is this measured?</button></div>
      <div id="filling-help" class="help-box" hidden>A filled cell contains a nonzero numeric value, including a rate. Blanks, zero, text, booleans and errors are invalid. A formula without a saved result is unknown. The overall rate is unknown whenever any expected cells are unknown; “known-cell rate” covers only the measurable cells. Coverage is the share we can measure. Totals use cell counts, not averages of percentages. Only matched, readable pairs enter the filling calculation.</div>
      <div id="filling-comparison" class="filling-comparison"></div>
      <div id="kpi-filling-summary" class="kpi-filling-summary" hidden></div>
    </section>
    <section id="inventory-panel" class="panel inventory-panel" aria-labelledby="inventory-heading"><div class="section-heading"><div><h2 id="inventory-heading">Workbook coverage</h2><p id="inventory-subtitle" class="muted small"></p></div></div><div id="inventory-content"></div></section>
    <section id="notes-panel" class="panel notes-panel" hidden><details><summary id="notes-heading">Run notes and exclusions</summary><div id="notes-content"></div></details></section>
    <section class="panel findings-panel" aria-labelledby="findings-heading">
      <div class="section-heading"><div><h2 id="findings-heading" tabindex="-1">Findings to review</h2><p class="muted small">Inspect the evidence, record a decision, and keep your review with the report.</p></div><button id="csv-export" class="button secondary" type="button">Export filtered CSV <span aria-hidden="true">↓</span></button></div>
      <div class="filter-grid">
        <label class="search-filter"><span>Search findings</span><input id="finding-search" class="input" type="search" placeholder="KPI, cell, message, or value…" autocomplete="off"></label>
        <label><span>Country</span><select id="filter-country" class="input"></select></label>
        <label><span>Sheet</span><select id="filter-sheet" class="input"></select></label>
        <label><span>Category</span><select id="filter-category" class="input"></select></label>
        <label><span>Severity</span><select id="filter-severity" class="input"></select></label>
        <label><span>Review status</span><select id="filter-status" class="input"></select></label>
      </div>
      <div class="results-toolbar"><div id="results-summary" aria-live="polite"></div><button id="reset-filters" class="text-button" type="button">Reset finding filters</button></div>
      <div class="table-scroll"><table class="findings-table"><thead><tr><th><button id="sort-severity" class="sort-button" type="button">Severity <span aria-hidden="true">↕</span></button></th><th>Country</th><th>Sheet / KPI</th><th>Finding</th><th>Review status</th><th><span class="sr-only">Open finding</span></th></tr></thead><tbody id="findings-body"></tbody></table></div>
      <div id="findings-empty" class="empty-state" hidden></div>
      <div class="pagination"><span id="page-summary"></span><div><label class="page-size-label">Rows <select id="page-size" class="input"><option>25</option><option selected>50</option><option>100</option></select></label><button id="previous-page" class="button secondary compact" type="button" aria-label="Previous page">←</button><button id="next-page" class="button secondary compact" type="button" aria-label="Next page">→</button></div></div>
    </section>
    <footer class="report-footer"><p id="review-storage-state">Review decisions are saved in this browser.</p><div><button id="reviews-export" class="text-button" type="button">Export reviews JSON</button><button id="reviews-import" class="text-button" type="button">Import reviews JSON</button><button id="print-report" class="text-button" type="button">Print report</button></div></footer>
  </main>
</div>
<input id="reviews-file" type="file" accept="application/json,.json" hidden>
<dialog id="detail-dialog" class="detail-dialog" aria-labelledby="detail-title"><div class="drawer-head"><span class="eyebrow">FINDING DETAILS</span><button id="close-detail" class="icon-button" type="button" aria-label="Close finding details">×</button></div><div id="detail-content"></div></dialog>
<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
<noscript><div class="noscript">This offline report needs JavaScript to display findings and review controls. No network access is required.</div></noscript>
<script id="report-payload" type="application/json">{data}</script>
<script>{javascript}</script>
</body>
</html>
'''
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", suffix=".tmp", dir=output.parent, delete=False) as handle:
            temporary_name = handle.name
            handle.write(document)
        os.replace(temporary_name, output)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return output
