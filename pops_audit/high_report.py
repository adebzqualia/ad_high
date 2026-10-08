"""Write the focused, offline report containing only high-criticality findings."""
from __future__ import annotations

from copy import deepcopy
import html
import os
from pathlib import Path
import tempfile

from .report import _embedded_json


def _high_payload(payload: dict) -> dict:
    """Keep findings and review context only; do not embed the full audit."""
    findings = [deepcopy(item) for item in payload.get("anomalies", [])
                if not item.get("baseline", False)
                and item.get("severity") in {"high", "critical"}]
    for finding in findings:
        finding.pop("baseline", None)
    visible_ids = {str(item.get("id")) for item in findings}
    country_ids = {str(item.get("country_id")) for item in findings}
    country_keys = ("id", "name", "file_key", "sent_file", "received_file")
    countries = [{key: deepcopy(country[key]) for key in country_keys if key in country}
                 for country in payload.get("countries", [])
                 if str(country.get("id")) in country_ids]
    reviews = payload.get("initial_reviews", [])
    if isinstance(reviews, dict):
        reviews = reviews.get("reviews", [])
    result = {key: deepcopy(payload[key]) for key in
              ("schema_version", "report_id", "generated_at", "demo") if key in payload}
    result.update(title="POPS · High-criticality anomalies", report_view="high_criticality",
                  anomalies=findings, countries=countries,
                  initial_reviews=[deepcopy(item) for item in reviews
                                   if isinstance(item, dict) and str(item.get("anomaly_id")) in visible_ids])
    if str(payload.get("initial_country")) in country_ids:
        result["initial_country"] = payload["initial_country"]
    return result


def write_high_report(payload: dict, output_path: str | Path) -> Path:
    """Create one portable HTML file for reviewing high and critical anomalies."""
    if not isinstance(payload, dict):
        raise TypeError("The report payload must be a dictionary.")
    focused = _high_payload(payload)
    assets = Path(__file__).resolve().parent.parent / "assets"
    css = (assets / "high_report.css").read_text(encoding="utf-8")
    javascript = (assets / "high_report.js").read_text(encoding="utf-8")
    title = html.escape(focused["title"], quote=True)
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
<a class="skip-link" href="#main-content">Skip to anomalies</a>
<header class="masthead">
  <div class="heading"><span class="brand">POPS</span><h1>High-criticality anomalies</h1><span id="demo-badge" class="demo-badge" hidden>Example data</span></div>
  <button id="save-report" class="button primary" type="button">Save reviewed report <span aria-hidden="true">↓</span></button>
</header>
<main id="main-content" tabindex="-1">
  <div id="storage-notice" class="storage-notice" role="status" hidden></div>
  <section class="findings" aria-label="High-criticality anomalies to review">
    <div class="filter-grid" role="search" aria-label="Filter anomalies">
      <label class="search-filter" for="finding-search"><span>Search</span><input id="finding-search" type="search" placeholder="KPI, cell, anomaly or note…" autocomplete="off"></label>
      <label for="filter-country"><span>Country</span><select id="filter-country"></select></label>
      <label for="filter-sheet"><span>Sheet</span><select id="filter-sheet"></select></label>
      <label for="filter-category"><span>Category</span><select id="filter-category"></select></label>
      <label for="filter-status"><span>Review status</span><select id="filter-status"></select></label>
    </div>
    <div class="results-toolbar"><p id="results-summary" role="status" aria-live="polite"></p><button id="reset-filters" class="text-button" type="button">Clear filters</button></div>
    <div class="table-scroll" tabindex="0" role="region" aria-label="Anomaly table">
      <table><caption class="sr-only">High and critical anomalies with review decisions</caption><thead><tr><th scope="col">Country</th><th scope="col">Sheet / KPI</th><th scope="col">Anomaly</th><th scope="col">Review status</th><th scope="col"><span class="sr-only">Evidence and notes</span></th></tr></thead><tbody id="findings-body"></tbody></table>
    </div>
    <div id="findings-empty" class="empty-state" hidden></div>
    <div class="pagination"><span id="page-summary"></span><div><label for="page-size">Rows <select id="page-size"><option>25</option><option selected>50</option><option>100</option></select></label><button id="previous-page" class="button secondary compact" type="button" aria-label="Previous page">←</button><button id="next-page" class="button secondary compact" type="button" aria-label="Next page">→</button></div></div>
  </section>
  <footer><p id="review-storage-state"></p><div><button id="reviews-export" class="text-button" type="button">Export reviews JSON</button><button id="reviews-import" class="text-button" type="button">Import reviews JSON</button></div></footer>
</main>
<input id="reviews-file" type="file" accept="application/json,.json" hidden>
<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
<noscript><p class="noscript">Enable JavaScript to display this offline report and its review controls. No network access is required.</p></noscript>
<script id="report-payload" type="application/json">{_embedded_json(focused)}</script>
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
