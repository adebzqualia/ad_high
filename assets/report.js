(() => {
  "use strict";
  // Keep an unrendered shell: a country export must not retain other countries
  // inside old table rows, menus, or hidden drawer content.
  const documentTemplate = document.documentElement.cloneNode(true);
  const payload = JSON.parse(document.getElementById("report-payload").textContent);
  const countries = Array.isArray(payload.countries) ? payload.countries : [];
  const anomalies = Array.isArray(payload.anomalies) ? payload.anomalies : [];
  const summary = payload.summary || {};
  const severityOrder = {critical: 0, high: 1, medium: 2, low: 3, info: 4};
  const statuses = {unreviewed: "Unreviewed", accepted: "Accepted", investigating: "Investigating", needs_correction: "Needs correction"};
  const statusKeys = new Set(Object.keys(statuses));
  const STORAGE_KEY = "pops-audit-reviews:v1";
  const countryById = new Map(countries.map(country => [String(country.id), country]));
  const anomalyById = new Map(anomalies.map(anomaly => [String(anomaly.id), anomaly]));
  const reviews = new Map();
  const state = {country: countryById.has(String(payload.initial_country)) ? String(payload.initial_country) : "", search: "", sheet: "", category: "", severity: "", status: "", page: 1, pageSize: 50, descending: false, printing: false};
  let storageAvailable = true;
  let activeDetail = null;
  let toastTimer;
  const $ = id => document.getElementById(id);
  const text = value => value === null || value === undefined ? "" : String(value);
  const list = value => Array.isArray(value) ? value : [];
  const number = value => typeof value === "number" && Number.isFinite(value);
  const count = value => number(value) ? value.toLocaleString() : "—";
  const percent = value => number(value) ? value.toLocaleString(undefined, {style: "percent", maximumFractionDigits: 1}) : "Unknown";
  const humanize = value => text(value).replace(/[_-]+/g, " ").replace(/^./, letter => letter.toUpperCase());
  const filename = value => text(value).split(/[\\/]/).pop() || "—";
  const displayLabel = value => typeof value === "object" && value !== null ? text(value.identifier ?? value.name ?? value.kpi ?? value.message ?? value.details ?? JSON.stringify(value)) : text(value);
  function el(tag, attributes, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") element.className = value;
      else if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === "value" || key === "checked" || key === "selected" || key === "disabled") element[key] = value;
      else element.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === undefined || child === null || child === false) continue;
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return element;
  }
  function replace(id, ...children) { $(id).replaceChildren(...children.flat(Infinity).filter(child => child !== null && child !== undefined && child !== false)); }
  function dateLabel(value) {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString(undefined, {year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"}) : text(value) || "Date unavailable";
  }
  function severity(value) {
    const level = Object.prototype.hasOwnProperty.call(severityOrder, value) ? value : "info";
    return el("span", {class: "severity " + level}, humanize(level));
  }
  function selectedCountry() { return countryById.get(state.country) || null; }
  function countryFindings() { return state.country ? anomalies.filter(anomaly => String(anomaly.country_id) === state.country) : anomalies; }
  function reviewFor(anomaly) {
    return reviews.get(String(anomaly.id)) || {anomaly_id: String(anomaly.id), status: statusKeys.has(anomaly.status) ? anomaly.status : "unreviewed", notes: "", updated_at: ""};
  }
  function validReview(record) {
    if (!record || typeof record !== "object" || typeof record.anomaly_id !== "string" || record.anomaly_id.length > 512 || !statusKeys.has(record.status)) return null;
    if (typeof record.notes !== "string" || record.notes.length > 10000) return null;
    const stamp = typeof record.updated_at === "string" && Number.isFinite(Date.parse(record.updated_at)) ? new Date(record.updated_at).toISOString() : "";
    return {anomaly_id: record.anomaly_id, status: record.status, notes: record.notes, updated_at: stamp};
  }
  function reviewRecords(value) { return Array.isArray(value) ? value : value && Array.isArray(value.reviews) ? value.reviews : []; }
  function mergeReviews(records, onlyCurrent = false, force = false) {
    let matched = 0, ignored = 0;
    for (const raw of records.slice(0, 100000)) {
      const record = validReview(raw);
      if (!record || (onlyCurrent && !anomalyById.has(record.anomaly_id))) { ignored++; continue; }
      const previous = reviews.get(record.anomaly_id);
      if (force || !previous || (Date.parse(record.updated_at) || 0) >= (Date.parse(previous.updated_at) || 0)) reviews.set(record.anomaly_id, record);
      if (anomalyById.has(record.anomaly_id)) matched++;
    }
    return {matched, ignored};
  }
  function showStorageState() {
    $("storage-notice").hidden = storageAvailable;
    $("storage-notice").textContent = "This browser cannot keep reviews for local files. Use “Save reviewed report” or “Export reviews JSON” to keep your decisions and notes.";
    $("review-storage-state").textContent = storageAvailable ? "Decisions save in this browser. Save a reviewed report to carry or share them." : "Decisions are held in this open tab. Save a reviewed report to keep them.";
  }
  function persistReviews() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({schema_version: 1, reviews: [...reviews.values()]})); }
    catch (_) { storageAvailable = false; }
    showStorageState();
  }
  function saveReview(anomaly, changes) {
    const updated = {...reviewFor(anomaly), ...changes, anomaly_id: String(anomaly.id), updated_at: new Date().toISOString()};
    reviews.set(updated.anomaly_id, updated);
    persistReviews();
    renderMetrics();
    renderFindings();
    const saved = $("detail-save-state");
    if (saved) saved.textContent = (storageAvailable ? "Saved on this device · " : "Saved in this open tab · ") + dateLabel(updated.updated_at);
  }
  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").className = "toast" + (error ? " error" : "");
    $("toast").hidden = false;
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5500);
  }
  mergeReviews(reviewRecords(payload.initial_reviews), true);
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) mergeReviews(reviewRecords(JSON.parse(stored)));
    localStorage.setItem(STORAGE_KEY, JSON.stringify({schema_version: 1, reviews: [...reviews.values()]}));
  } catch (_) { storageAvailable = false; }
  showStorageState();

  function inventoryLabel(value) {
    const normalized = text(value).toLowerCase();
    const labels = {matched: "Compared", compared: "Compared", ok: "Compared", present: "Present", missing_received: "Return missing", not_received: "Return missing", unexpected_received: "No matching sent file", unexpected: "No matching sent file", ambiguous_pair: "Match unresolved", ambiguous: "Match unresolved", read_error: "Could not read", missing_sent: "Sent workbook missing", missing: "Missing", excluded: "Excluded", optional_absent: "Optional · absent", inventory_only: "Inventory only", absent: "Not present", added: "Added in return"};
    return labels[normalized] || humanize(value) || "Not assessed";
  }
  function inventoryStatus(value) {
    const normalized = text(value).toLowerCase();
    const good = /^(matched|compared|ok|present)$/.test(normalized);
    const bad = /error|missing|unreadable|not_received/.test(normalized);
    return el("span", {class: "status-chip " + (good ? "good" : bad ? "bad" : "warn")}, inventoryLabel(value));
  }
  function renderSidebar() {
    $("country-count").textContent = countries.length;
    $("overview-button").classList.toggle("active", !state.country);
    const search = $("country-search").value.toLocaleLowerCase().trim();
    const matching = countries.filter(country => [country.name, country.file_key, country.sent_file, country.received_file].some(value => text(value).toLocaleLowerCase().includes(search)));
    replace("country-list", matching.length ? matching.map(country => {
      const findingCount = anomalies.filter(anomaly => String(anomaly.country_id) === String(country.id)).length;
      return el("button", {type: "button", class: "country-button" + (state.country === String(country.id) ? " active" : ""), "aria-current": state.country === String(country.id) ? "page" : null, onclick: () => navigateCountry(String(country.id))},
        el("span", {class: "country-label"}, country.name || country.file_key || "Unnamed country", el("small", {class: "muted"}, inventoryLabel(country.status))),
        el("span", {class: "nav-count", title: "Received-workbook findings"}, findingCount));
    }) : el("p", {class: "empty-note"}, "No countries match this search."));
  }
  function navigateCountry(id) {
    state.country = id;
    state.page = 1;
    state.sheet = "";
    state.category = "";
    renderAll();
  }
  function renderHeading() {
    const country = selectedCountry();
    $("save-country-report").hidden = !country;
    $("breadcrumb").textContent = country ? "COUNTRY REVIEW" : "REPORT OVERVIEW";
    $("view-title").textContent = country ? country.name || country.file_key : payload.title || "Workbook quality review";
    replace("view-subtitle", country ? [el("span", {}, "Sent workbook compared with the returned workbook."), el("div", {class: "file-pair"}, el("span", {}, "Sent: ", country.sent_file || "Not available"), el("span", {}, "Received: ", country.received_file || "Not available"))] : "A clear view of completeness, workbook changes, and the items that need a decision.");
    replace("report-meta", payload.demo ? el("span", {class: "demo-badge"}, "Sample data") : null, el("div", {}, "Generated ", dateLabel(payload.generated_at)), country ? el("div", {style: "margin-top:7px"}, inventoryStatus(country.status)) : null);
  }
  function metric(label, value, note, style = "") {
    return el("article", {class: "metric-card " + style}, el("div", {class: "metric-label"}, label), el("div", {class: "metric-number"}, value), el("div", {class: "metric-note"}, note));
  }
  function renderMetrics() {
    const country = selectedCountry();
    const scoped = countryFindings();
    const urgent = scoped.filter(anomaly => ["critical", "high"].includes(anomaly.severity)).length;
    const corrections = scoped.filter(anomaly => reviewFor(anomaly).status === "needs_correction").length;
    const recorded = scoped.filter(anomaly => reviewFor(anomaly).status !== "unreviewed").length;
    const inventoryMetrics = country ? [
      metric("SHEETS SENT", count(country.sent_sheet_count), "All sheets in the sent workbook"),
      metric("SHEETS RECEIVED", count(country.received_sheet_count), "All sheets in the returned workbook"),
      metric("SHEETS IN REVIEW", list(country.sheets).length ? count(country.sheets.length) : number(country.sent_sheet_count) || number(country.received_sheet_count) ? "0" : "—", "Presence and completeness below")
    ] : [
      metric("FILES SENT", count(summary.sent_files), "Country workbooks sent out"),
      metric("FILES RECEIVED", count(summary.received_files), `${count(summary.missing_received)} returns missing · ${count(summary.unexpected_received)} without a sent workbook`),
      metric("MATCHED PAIRS", count(summary.matched_pairs), `${count(summary.analysed_pairs)} analysed · ${count(summary.read_errors)} read error(s)`)
    ];
    replace("metric-grid", ...inventoryMetrics,
      metric("COUNTRY FINDINGS", count(scoped.length), `${count(urgent)} high priority`, urgent ? "caution" : ""),
      metric("NEEDS CORRECTION", count(corrections), "Flagged during review"),
      metric("REVIEW DECISIONS RECORDED", [count(recorded), el("span", {class: "unit"}, "/ ", count(scoped.length))], "Includes items under investigation", "accent"));
  }
  function fillingRate(filling) {
    if (!filling || !number(filling.expected)) return "Not available";
    if (filling.expected === 0) return "Not applicable";
    if (number(filling.unknown) && filling.unknown > 0) return "Unknown";
    return number(filling.rate) ? percent(filling.rate) : "Unknown";
  }
  function fillingCard(label, filling) {
    const available = filling && number(filling.expected);
    const expected = available ? filling.expected : null;
    const mainRate = fillingRate(filling);
    const incomplete = !available || !number(filling.rate) || filling.unknown > 0 || expected === 0;
    const bar = el("div", {class: "filling-bar", role: "img", "aria-label": available ? `${count(filling.filled)} filled, ${count(filling.invalid)} invalid, ${count(filling.unknown)} unknown out of ${count(expected)} expected cells` : "Filling measurement unavailable"});
    if (expected > 0) for (const key of ["filled", "invalid", "unknown"]) {
      const width = number(filling[key]) ? Math.max(0, Math.min(100, filling[key] / expected * 100)) : 0;
      bar.append(el("span", {class: key, style: `width:${width}%`}));
    }
    let explanation;
    if (!available) explanation = "This workbook pair is excluded from filling totals, or no measurement was produced.";
    else if (expected === 0) explanation = "No expected cells are in scope for this measurement.";
    else if (filling.unknown > 0) explanation = [el("strong", {}, "Known-cell rate: ", percent(filling.known_rate)), " · Coverage: ", percent(filling.coverage), ". Unknown cells prevent an overall rate."];
    else explanation = ["Measurement coverage: ", el("strong", {}, percent(filling.coverage)), ". All expected cells are measurable."];
    return el("article", {class: "filling-side"},
      el("div", {class: "filling-top"}, el("div", {}, el("div", {class: "filling-period"}, label), el("div", {class: "filling-rate" + (incomplete ? " unknown" : "")}, mainRate)), el("div", {class: "filling-expected"}, count(expected), " expected cells")), bar,
      available ? el("div", {class: "filling-counts"}, ...[["filled", "Filled"], ["invalid", "Invalid / empty"], ["unknown", "Unknown"]].map(([key, title]) => el("span", {}, el("i", {class: "legend-dot " + key, "aria-hidden": "true"}), title, " ", el("strong", {}, count(filling[key]))))) : null,
      el("p", {class: "coverage-note"}, explanation));
  }
  function renderFilling() {
    const country = selectedCountry();
    const source = country ? ["matched", "compared", "ok"].includes(text(country.status).toLowerCase()) ? country : {} : summary;
    $("filling-scope").textContent = `${country ? "This country" : "All matched, readable pairs"} · Selected business sheets, excluding KPI. Finding filters do not change this denominator.`;
    replace("filling-comparison", fillingCard("Sent workbook · before", source.filling_before), fillingCard("Received workbook · after", source.filling_after));
    const hasKpi = Object.prototype.hasOwnProperty.call(source, "kpi_filling_before") || Object.prototype.hasOwnProperty.call(source, "kpi_filling_after");
    $("kpi-filling-summary").hidden = !hasKpi;
    replace("kpi-filling-summary", el("div", {}, el("strong", {}, "KPI sheet filling"), el("p", {class: "small muted"}, "Separate measure · excluded from overall filling")),
      el("div", {}, el("span", {class: "small muted"}, "Before "), rateCell(source.kpi_filling_before)),
      el("div", {}, el("span", {class: "small muted"}, "After "), rateCell(source.kpi_filling_after)));
  }
  function rateCell(filling) {
    const value = fillingRate(filling);
    return el("span", {class: "rate-text"}, value, filling && filling.unknown > 0 ? el("span", {class: "rate-sub"}, "Known: ", percent(filling.known_rate), " · coverage: ", percent(filling.coverage)) : null);
  }
  function amount(value) { return Array.isArray(value) ? count(value.length) : count(value); }
  function chips(values, style = "", empty = "None") {
    return el("div", {class: "presence-chips"}, list(values).length ? list(values).map(value => el("span", {class: "presence-chip " + style}, displayLabel(value))) : el("span", {class: "small muted"}, empty));
  }
  function sheetCard(sheet) {
    if (sheet.detailed_checks === false || sheet.status === "inventory_only") {
      return el("details", {class: "sheet-card"},
        el("summary", {}, el("span", {class: "sheet-name"}, sheet.name || sheet.received_name || sheet.sent_name || "Unnamed sheet"), inventoryStatus(sheet.status)),
        el("div", {class: "sheet-body"}, el("p", {class: "inventory-only-note"}, "This sheet is listed for presence only. Its KPIs, columns and filling have not been assessed."),
          el("div", {class: "presence-grid"}, el("div", {}, el("h4", {}, "KPI / identifier presence"), "—"), el("div", {}, el("h4", {}, "Column presence"), "—"))));
    }
    return el("details", {class: "sheet-card"},
      el("summary", {}, el("span", {class: "sheet-name"}, sheet.name || sheet.received_name || sheet.sent_name || "Unnamed sheet"), el("span", {class: "sheet-summary-meta"}, count(sheet.anomaly_count), " finding(s)"), inventoryStatus(sheet.status)),
      el("div", {class: "sheet-body"},
        el("div", {class: "presence-grid"},
          el("div", {}, el("h4", {}, "KPI / identifier presence"), el("p", {}, "Expected: ", amount(sheet.expected_kpis), " · Sent: ", amount(sheet.sent_kpis), " · Received: ", amount(sheet.received_kpis)), el("div", {class: "presence-label"}, "Missing in received workbook"), chips(sheet.missing_kpis, "missing", "No missing identifiers reported"), list(sheet.unexpected_kpis).length ? [el("div", {class: "presence-label"}, "Additional identifiers"), chips(sheet.unexpected_kpis, "extra")] : null),
          el("div", {}, el("h4", {}, "Column presence"), el("div", {class: "presence-label"}, "Expected"), chips(sheet.expected_columns, "", "No expected columns"), el("div", {class: "presence-label"}, "Present in sent workbook"), chips(sheet.sent_columns, "", "No columns located"), el("div", {class: "presence-label"}, "Present in received workbook"), chips(sheet.received_columns, "", "No columns located"), list(sheet.missing_columns).length ? [el("div", {class: "presence-label"}, "Missing in received workbook"), chips(sheet.missing_columns, "missing")] : null)),
        el("div", {class: "sheet-filling"}, el("span", {}, "Before", el("strong", {}, rateCell(sheet.filling_before))), el("span", {}, "After", el("strong", {}, rateCell(sheet.filling_after))))));
  }
  function renderInventory() {
    const country = selectedCountry();
    $("inventory-heading").textContent = country ? "Sheets, KPIs and columns" : "Workbook coverage";
    $("inventory-subtitle").textContent = country ? "Open a sheet to inspect expected content and missing items." : "Unmatched or unreadable workbooks stay visible here and are excluded from filling totals.";
    if (country) {
      replace("inventory-content", el("div", {class: "sheet-inventory"}, list(country.sheets).length ? country.sheets.map(sheetCard) : el("div", {class: "empty-state"}, "No sheet comparison is available for this country.")));
      return;
    }
    const table = el("table", {class: "inventory-table"}, el("thead", {}, el("tr", {}, ...["Country", "Comparison", "Before", "After", "Findings"].map(title => el("th", {}, title)))), el("tbody", {}, ...countries.map(item => el("tr", {},
      el("td", {}, el("button", {class: "country-link", type: "button", onclick: () => navigateCountry(String(item.id))}, item.name || item.file_key || "Unnamed country"), el("span", {class: "file-note"}, filename(item.received_file || item.sent_file))),
      el("td", {}, inventoryStatus(item.status)), el("td", {}, rateCell(["matched", "compared", "ok"].includes(text(item.status).toLowerCase()) ? item.filling_before : null)), el("td", {}, rateCell(["matched", "compared", "ok"].includes(text(item.status).toLowerCase()) ? item.filling_after : null)), el("td", {}, count(item.anomaly_count))))));
    replace("inventory-content", countries.length ? el("div", {class: "table-scroll"}, table) : el("div", {class: "empty-state"}, "No workbook inventory was produced. Check the run notes below."));
  }
  function renderNotes() {
    const country = selectedCountry();
    const notes = country ? list(country.notes) : list(payload.notices);
    $("notes-panel").hidden = notes.length === 0;
    $("notes-heading").textContent = country ? `Country notes · ${notes.length}` : `Run notes and exclusions · ${notes.length}`;
    replace("notes-content", el("ul", {}, ...notes.map(note => el("li", {}, displayLabel(note)))));
  }
  function options(id, entries, value, emptyLabel) {
    replace(id, el("option", {value: ""}, emptyLabel), entries.map(([key, label]) => el("option", {value: text(key)}, label)));
    $(id).value = value;
    if ($(id).value !== value) {
      $(id).append(el("option", {value, selected: true}, value));
    }
  }
  function uniqueEntries(items, getter, label = getter) {
    const found = new Map();
    for (const item of items) { const key = text(getter(item)); if (key) found.set(key, text(label(item)) || key); }
    return [...found.entries()].sort((a, b) => a[1].localeCompare(b[1], undefined, {numeric: true}));
  }
  function renderFilters() {
    const scoped = countryFindings();
    options("filter-country", countries.map(country => [country.id, country.name || country.file_key]), state.country, "All countries");
    options("filter-sheet", uniqueEntries(scoped, anomaly => anomaly.sheet), state.sheet, "All sheets");
    options("filter-category", uniqueEntries(scoped, anomaly => anomaly.category, anomaly => anomaly.category_label || humanize(anomaly.category)), state.category, "All categories");
    const visibleLevels = Object.keys(severityOrder).filter(key => ["high", "medium", "low"].includes(key) || scoped.some(anomaly => anomaly.severity === key));
    options("filter-severity", visibleLevels.map(key => [key, humanize(key)]), state.severity, "All severities");
    options("filter-status", Object.entries(statuses), state.status, "All review statuses");
    $("finding-search").value = state.search;
  }
  function filteredFindings() {
    const query = state.search.toLocaleLowerCase().trim();
    return countryFindings().filter(anomaly => {
      if (state.sheet && text(anomaly.sheet) !== state.sheet) return false;
      if (state.category && text(anomaly.category) !== state.category) return false;
      if (state.severity && anomaly.severity !== state.severity) return false;
      if (state.status && reviewFor(anomaly).status !== state.status) return false;
      if (!query) return true;
      return [anomaly.country, anomaly.workbook, anomaly.sheet, anomaly.kpi, anomaly.column, anomaly.title, anomaly.message, anomaly.category, anomaly.category_label, anomaly.sent_cell, anomaly.received_cell, JSON.stringify(anomaly.before), JSON.stringify(anomaly.after), reviewFor(anomaly).notes].some(value => text(value).toLocaleLowerCase().includes(query));
    }).sort((a, b) => ((severityOrder[a.severity] ?? 4) - (severityOrder[b.severity] ?? 4)) * (state.descending ? -1 : 1) || text(a.country).localeCompare(text(b.country)) || text(a.sheet).localeCompare(text(b.sheet)) || text(a.id).localeCompare(text(b.id)));
  }
  function reviewSelect(anomaly, extraClass = "") {
    const current = reviewFor(anomaly);
    const select = el("select", {class: "review-select " + current.status + " " + extraClass, "aria-label": `Review status for ${anomaly.title || anomaly.kpi || anomaly.id}`, onchange: event => saveReview(anomaly, {status: event.target.value})}, ...Object.entries(statuses).map(([key, label]) => el("option", {value: key}, label)));
    select.value = current.status;
    return select;
  }
  function renderFindings() {
    const filtered = filteredFindings();
    const pages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    state.page = Math.min(state.page, pages);
    const offset = (state.page - 1) * state.pageSize;
    const visible = state.printing ? filtered : filtered.slice(offset, offset + state.pageSize);
    const unreviewed = filtered.filter(anomaly => reviewFor(anomaly).status === "unreviewed").length;
    const urgent = filtered.filter(anomaly => ["critical", "high"].includes(anomaly.severity)).length;
    replace("results-summary", el("strong", {}, count(filtered.length)), " finding(s) shown · ", count(unreviewed), " unreviewed · ", count(urgent), " high priority");
    replace("findings-body", visible.map(anomaly => el("tr", {},
      el("td", {}, severity(anomaly.severity)),
      el("td", {}, el("div", {class: "cell-primary"}, anomaly.country || "Not specified")),
      el("td", {}, el("div", {class: "cell-primary"}, anomaly.sheet || "Workbook"), el("div", {class: "cell-secondary"}, anomaly.kpi || "—"), anomaly.column ? el("div", {class: "cell-secondary"}, "Column: ", anomaly.column) : null),
      el("td", {}, el("button", {class: "finding-title", type: "button", onclick: () => openDetail(String(anomaly.id))}, anomaly.title || anomaly.category_label || humanize(anomaly.category)), el("div", {class: "finding-description"}, anomaly.message || ""), el("div", {class: "finding-category"}, anomaly.category_label || humanize(anomaly.category))),
      el("td", {}, reviewSelect(anomaly), reviewFor(anomaly).notes ? el("div", {class: "notes-indicator"}, "Note added") : null),
      el("td", {}, el("button", {class: "open-button", type: "button", "aria-label": `Inspect ${anomaly.title || "finding"}`, onclick: () => openDetail(String(anomaly.id))}, "↗")))));
    $("findings-empty").hidden = filtered.length > 0;
    replace("findings-empty", el("strong", {}, "No findings in this view"), "Try another country or filter combination.");
    $("page-summary").textContent = filtered.length ? `${count(offset + 1)}–${count(Math.min(offset + state.pageSize, filtered.length))} of ${count(filtered.length)}` : "0 findings";
    $("previous-page").disabled = state.page <= 1;
    $("next-page").disabled = state.page >= pages;
    $("sort-severity").parentElement.setAttribute("aria-sort", state.descending ? "ascending" : "descending");
  }
  function rawValue(cell) {
    if (!cell) return "No cell to compare";
    if (cell.formula && cell.cache_available === false) return "Unknown · saved result unavailable";
    if (cell.value === null || cell.value === undefined || cell.value === "") return "Blank";
    if (typeof cell.value === "boolean") return cell.value ? "TRUE" : "FALSE";
    return text(cell.value);
  }
  function evidence(label, address, cell, after = false) {
    return el("article", {class: "evidence-card"}, el("div", {class: "evidence-head" + (after ? " after" : "")}, label, el("span", {class: "evidence-address"}, address || "No location")),
      el("div", {class: "evidence-body"}, cell && cell.formula && cell.cache_available === false ? el("div", {class: "cache-warning"}, "The formula is present, but no saved result is available. Its filling state is unknown.") : null,
        el("div", {class: "evidence-label"}, "Saved value"), el("div", {class: "evidence-value"}, rawValue(cell)), el("div", {class: "evidence-label"}, "Formula"), el("pre", {class: "evidence-formula"}, cell && cell.formula ? cell.formula : "No formula")));
  }
  function openDetail(id) {
    const anomaly = anomalyById.get(id);
    if (!anomaly) return;
    activeDetail = id;
    const review = reviewFor(anomaly);
    const detailStatus = reviewSelect(anomaly, "input");
    detailStatus.id = "detail-review-status";
    detailStatus.addEventListener("change", () => { detailStatus.className = "review-select input " + detailStatus.value; });
    const notes = el("textarea", {class: "input", id: "detail-review-notes", rows: "5", maxlength: "10000", placeholder: "Record context, a question, or the action to take…", oninput: event => saveReview(anomaly, {notes: event.target.value})});
    notes.value = review.notes;
    replace("detail-content", el("div", {class: "drawer-body"},
      el("div", {class: "detail-badges"}, severity(anomaly.severity)),
      el("h2", {id: "detail-title"}, anomaly.title || anomaly.category_label || humanize(anomaly.category)), el("p", {class: "detail-message"}, anomaly.message || ""),
      el("dl", {class: "detail-meta"}, ...[["Country", anomaly.country], ["Sheet", anomaly.sheet], ["KPI / identifier", anomaly.kpi], ["Column", anomaly.column], ["Category", anomaly.category_label || humanize(anomaly.category)]].map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value || "—")))),
      el("div", {class: "evidence-grid"}, evidence("Sent workbook · before", anomaly.sent_cell, anomaly.before), evidence("Received workbook · after", anomaly.received_cell, anomaly.after, true)),
      el("section", {class: "review-form"}, el("h3", {}, "Your review"), el("p", {class: "small muted"}, "Accepted records your decision to accept this change. Investigating keeps it open; Needs correction flags a follow-up."), el("label", {for: "detail-review-status"}, "Review status", detailStatus), el("label", {for: "detail-review-notes"}, "Review notes", notes), el("p", {class: "review-save-state", id: "detail-save-state"}, review.updated_at ? "Last reviewed · " + dateLabel(review.updated_at) : "Changes save automatically in this browser when local storage is available.")),
      el("p", {class: "detail-id"}, "Finding ID · ", id)));
    if (!$("detail-dialog").open) $("detail-dialog").showModal();
  }
  function renderAll() { renderSidebar(); renderHeading(); renderMetrics(); renderFilling(); renderInventory(); renderNotes(); renderFilters(); renderFindings(); }

  function download(content, mime, name) {
    const blob = new Blob([content], {type: mime});
    const url = URL.createObjectURL(blob);
    const anchor = el("a", {href: url, download: name});
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  function safeFilename(value) { return text(value).replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 120) || "report"; }
  function safeJSON(value) {
    return JSON.stringify(value).replace(/&/g, "\\u0026").replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
  }
  function currentReviews() { return [...reviews.values()].filter(review => anomalyById.has(review.anomaly_id)); }
  function reviewBundle() { return {schema_version: 1, tool: "pops-audit-reviews", report_id: payload.report_id, exported_at: new Date().toISOString(), reviews: currentReviews()}; }
  function downloadReport(report, name) {
    const clone = documentTemplate.cloneNode(true);
    clone.querySelector("#report-payload").textContent = safeJSON(report);
    clone.querySelector("title").textContent = report.title || "Workbook review";
    download("<!doctype html>\n" + clone.outerHTML, "text/html;charset=utf-8", safeFilename(name) + ".html");
  }
  function saveReviewedReport() {
    downloadReport({...payload, initial_reviews: currentReviews()}, (payload.title || "Workbook review") + " - reviewed");
    toast("Reviewed report saved with your decisions and notes embedded.");
  }
  function saveCountryReport() {
    const country = selectedCountry();
    if (!country) return;
    const selected = countryFindings();
    const selectedIds = new Set(selected.map(anomaly => String(anomaly.id)));
    const status = text(country.status).toLowerCase();
    const paired = ["matched", "compared", "ok", "read_error"].includes(status);
    const analysed = ["matched", "compared", "ok"].includes(status);
    const bySeverity = {};
    for (const anomaly of selected) bySeverity[anomaly.severity] = (bySeverity[anomaly.severity] || 0) + 1;
    const scopedSummary = {
      sent_files: country.sent_file ? 1 : status === "ambiguous" ? null : 0,
      received_files: country.received_file ? 1 : status === "ambiguous" ? null : 0,
      matched_pairs: Number(paired), analysed_pairs: Number(analysed),
      missing_received: Number(["not_received", "missing_received"].includes(status)),
      unexpected_received: Number(["unexpected", "unexpected_received"].includes(status)),
      ambiguous_pairs: Number(["ambiguous", "ambiguous_pair"].includes(status)),
      read_errors: Number(status === "read_error"),
      countries_with_issues: Number(selected.length > 0),
      anomaly_count: selected.length,
      by_severity: bySeverity, filling_before: analysed ? country.filling_before : null,
      filling_after: analysed ? country.filling_after : null,
      kpi_filling_before: analysed ? country.kpi_filling_before : null,
      kpi_filling_after: analysed ? country.kpi_filling_after : null
    };
    const title = (country.name || country.file_key || "Country") + " · POPS return review";
    downloadReport({schema_version: payload.schema_version, report_id: text(payload.report_id) + ":" + country.id,
      generated_at: payload.generated_at, title, demo: payload.demo === true, settings: payload.settings,
      summary: scopedSummary, countries: [country], anomalies: selected, notices: ["This report contains only the selected country's workbook comparison and review decisions."],
      initial_country: String(country.id), initial_reviews: currentReviews().filter(review => selectedIds.has(review.anomaly_id))}, title);
    toast("Country report saved with only this country's data, decisions and notes.");
  }
  function csvCell(value) {
    if (number(value)) return String(value);
    let string = text(value);
    if (/^[\s\u0000-\u001f]*[=+\-@]/.test(string) || /^[\t\r\n]/.test(string)) string = "'" + string;
    return '"' + string.replace(/"/g, '""') + '"';
  }
  function exportCSV() {
    const header = ["Review status", "Review notes", "Severity", "Country", "Sheet", "Category", "KPI", "Column", "Sent cell", "Received cell", "Before value", "After value", "Before formula", "After formula", "Finding", "Message"];
    const records = filteredFindings();
    const rows = records.map(anomaly => {
      const review = reviewFor(anomaly);
      const cellValue = cell => cell && !(cell.formula && cell.cache_available === false) ? cell.value : cell ? "Unknown: saved result unavailable" : "";
      return [statuses[review.status], review.notes, anomaly.severity, anomaly.country, anomaly.sheet, anomaly.category_label || anomaly.category, anomaly.kpi, anomaly.column, anomaly.sent_cell, anomaly.received_cell, cellValue(anomaly.before), cellValue(anomaly.after), anomaly.before && anomaly.before.formula, anomaly.after && anomaly.after.formula, anomaly.title, anomaly.message];
    });
    download("\ufeff" + [header, ...rows].map(row => row.map(csvCell).join(",")).join("\r\n"), "text/csv;charset=utf-8", "pops-findings-" + safeFilename(selectedCountry()?.name || "all-countries") + ".csv");
    toast(`${records.length.toLocaleString()} filtered finding(s) exported.`);
  }
  async function importReviews(event) {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error("Review files must be smaller than 10 MB.");
      const imported = JSON.parse(await file.text());
      if (!imported || imported.schema_version !== 1 || !Array.isArray(imported.reviews)) throw new Error("Choose a POPS review JSON file with schema_version 1 and a reviews list.");
      const result = mergeReviews(imported.reviews, true, false);
      persistReviews(); renderMetrics(); renderFindings();
      if (activeDetail && $("detail-dialog").open) openDetail(activeDetail);
      toast(`${result.matched.toLocaleString()} matching review record(s) loaded; ${result.ignored.toLocaleString()} unmatched or invalid record(s) ignored. Newer decisions are kept.`);
    } catch (error) { toast("Could not import reviews: " + error.message, true); }
    finally { event.target.value = ""; }
  }

  $("overview-button").addEventListener("click", () => navigateCountry(""));
  $("country-search").addEventListener("input", renderSidebar);
  $("finding-search").addEventListener("input", event => { state.search = event.target.value; state.page = 1; renderFindings(); });
  $("filter-country").addEventListener("change", event => navigateCountry(event.target.value));
  for (const key of ["sheet", "category", "severity", "status"]) $("filter-" + key).addEventListener("change", event => { state[key] = event.target.value; state.page = 1; renderFindings(); });
  $("reset-filters").addEventListener("click", () => { for (const key of ["search", "sheet", "category", "severity", "status"]) state[key] = ""; state.page = 1; renderFilters(); renderFindings(); });
  $("previous-page").addEventListener("click", () => { state.page--; renderFindings(); });
  $("next-page").addEventListener("click", () => { state.page++; renderFindings(); });
  $("page-size").addEventListener("change", event => { state.pageSize = Number(event.target.value); state.page = 1; renderFindings(); });
  $("sort-severity").addEventListener("click", () => { state.descending = !state.descending; renderFindings(); });
  $("close-detail").addEventListener("click", () => $("detail-dialog").close());
  $("detail-dialog").addEventListener("click", event => { if (event.target === $("detail-dialog") && event.clientX < $("detail-dialog").getBoundingClientRect().left) $("detail-dialog").close(); });
  $("filling-help-button").addEventListener("click", () => { $("filling-help").hidden = !$("filling-help").hidden; $("filling-help-button").setAttribute("aria-expanded", String(!$("filling-help").hidden)); });
  $("save-report").addEventListener("click", saveReviewedReport);
  $("save-country-report").addEventListener("click", saveCountryReport);
  $("csv-export").addEventListener("click", exportCSV);
  $("reviews-export").addEventListener("click", () => { download(JSON.stringify(reviewBundle(), null, 2), "application/json;charset=utf-8", "pops-review-decisions.json"); toast("Review decisions exported. Import this file into a later report with the same findings."); });
  $("reviews-import").addEventListener("click", () => $("reviews-file").click());
  $("reviews-file").addEventListener("change", importReviews);
  $("print-report").addEventListener("click", () => window.print());
  window.addEventListener("beforeprint", () => { state.printing = true; renderFindings(); });
  window.addEventListener("afterprint", () => { state.printing = false; renderFindings(); });
  renderAll();
})();
