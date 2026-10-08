(() => {
  "use strict";
  // Saved HTML starts from this pristine shell, never from rendered rows or notes.
  const documentTemplate = document.documentElement.cloneNode(true);
  const payload = JSON.parse(document.getElementById("report-payload").textContent);
  const list = value => Array.isArray(value) ? value : [];
  const text = value => value === null || value === undefined ? "" : String(value);
  const humanize = value => text(value).replace(/[_-]+/g, " ").replace(/^./, letter => letter.toUpperCase());
  const $ = id => document.getElementById(id);
  const anomalies = list(payload.anomalies).filter(item => !item.baseline && ["high", "critical"].includes(item.severity));
  const countries = new Map(list(payload.countries).map(country => [String(country.id), country]));
  const anomalyById = new Map(anomalies.map(anomaly => [String(anomaly.id), anomaly]));
  const rowIndex = new Map(anomalies.map((anomaly, index) => [String(anomaly.id), index]));
  const statuses = {unreviewed: "Unreviewed", accepted: "Accepted", investigating: "Needs investigation", needs_correction: "Needs correction"};
  const statusKeys = new Set(Object.keys(statuses));
  const STORAGE_KEY = "pops-audit-reviews:v1";
  const reviews = new Map();
  const expanded = new Set();
  const state = {country: countries.has(String(payload.initial_country)) ? String(payload.initial_country) : "", sheet: "", category: "", status: "", search: "", page: 1, pageSize: 50};
  let storageAvailable = true;
  let toastTimer;

  function el(tag, attributes, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") element.className = value;
      else if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2).toLowerCase(), value);
      else if (["value", "disabled", "selected", "checked"].includes(key)) element[key] = value;
      else element.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === undefined || child === null || child === false) continue;
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return element;
  }
  function replace(id, ...children) { $(id).replaceChildren(...children.flat(Infinity)); }
  function toast(message, error = false) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").className = "toast" + (error ? " error" : "");
    $("toast").hidden = false;
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5500);
  }
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
  function mergeReviews(records, onlyCurrent = false) {
    let matched = 0, ignored = 0;
    for (const raw of records) {
      const record = validReview(raw);
      if (!record || (onlyCurrent && !anomalyById.has(record.anomaly_id))) { ignored++; continue; }
      const previous = reviews.get(record.anomaly_id);
      if (!previous || (Date.parse(record.updated_at) || 0) > (Date.parse(previous.updated_at) || 0)) reviews.set(record.anomaly_id, record);
      if (anomalyById.has(record.anomaly_id)) matched++;
    }
    return {matched, ignored};
  }
  function showStorageState() {
    $("storage-notice").hidden = storageAvailable;
    $("storage-notice").textContent = "This browser cannot save reviews locally. Use “Save reviewed report” or “Export reviews JSON” to keep your decisions and notes.";
    $("review-storage-state").textContent = storageAvailable
      ? "Decisions save in this browser. Save a reviewed report to carry them with the file."
      : "Decisions are held in this open tab. Save a reviewed report to keep them.";
  }
  function readStoredReviews() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        // Do not replace an unreadable or unknown storage format with a partial review.
        if (!Array.isArray(parsed) && (!parsed || parsed.schema_version !== 1 || !Array.isArray(parsed.reviews))) throw new Error("Unknown review storage format");
        mergeReviews(reviewRecords(parsed));
      }
      return true;
    } catch (_) { storageAvailable = false; return false; }
  }
  function persistReviews() {
    // Re-read before every write: a filtered report must retain other reports' reviews,
    // including decisions saved in another tab since this report was opened.
    if (readStoredReviews()) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({schema_version: 1, reviews: [...reviews.values()]}));
        storageAvailable = true;
      } catch (_) { storageAvailable = false; }
    }
    showStorageState();
  }
  function savedLabel(review) {
    if (!review.updated_at) return "Notes and decisions save automatically.";
    const date = new Date(review.updated_at);
    return (storageAvailable ? "Saved in this browser · " : "Saved in this tab · ") + date.toLocaleString(undefined, {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
  }
  function saveReview(anomaly, changes, redraw = true) {
    readStoredReviews();
    const previous = reviewFor(anomaly);
    // Keep a deliberate new decision newer even if an imported clock was ahead.
    const timestamp = new Date(Math.max(Date.now(), (Date.parse(previous.updated_at) || 0) + 1)).toISOString();
    const updated = {...previous, ...changes, anomaly_id: String(anomaly.id), updated_at: timestamp};
    reviews.set(updated.anomaly_id, updated);
    persistReviews();
    if (redraw) renderFindings();
    else {
      const index = rowIndex.get(String(anomaly.id));
      const noteIndicator = $("notes-indicator-" + index);
      if (noteIndicator) noteIndicator.hidden = !updated.notes;
      const saved = $("saved-" + index);
      if (saved) saved.textContent = savedLabel(updated);
    }
  }

  function countryName(anomaly) { return anomaly.country || countries.get(String(anomaly.country_id))?.name || "Not specified"; }
  function options(id, values, allLabel, selected) {
    const entries = [...values.entries()].sort((a, b) => text(a[1]).localeCompare(text(b[1])));
    replace(id, el("option", {value: ""}, allLabel), entries.map(([value, label]) => el("option", {value}, label)));
    $(id).value = values.has(selected) ? selected : "";
    return $(id).value;
  }
  function renderFilters() {
    const countryOptions = new Map(anomalies.map(anomaly => [String(anomaly.country_id), countryName(anomaly)]));
    state.country = options("filter-country", countryOptions, "All countries", state.country);
    const selected = state.country ? anomalies.filter(anomaly => String(anomaly.country_id) === state.country) : anomalies;
    state.sheet = options("filter-sheet", new Map(selected.filter(item => item.sheet).map(item => [item.sheet, item.sheet])), "All sheets", state.sheet);
    state.category = options("filter-category", new Map(selected.filter(item => item.category).map(item => [item.category, item.category_label || humanize(item.category)])), "All categories", state.category);
    replace("filter-status", el("option", {value: ""}, "All statuses"), Object.entries(statuses).map(([value, label]) => el("option", {value}, label)));
    $("filter-status").value = state.status;
    $("finding-search").value = state.search;
  }
  function filteredFindings() {
    const query = state.search.trim().toLocaleLowerCase();
    return anomalies.filter(anomaly => {
      if (state.country && String(anomaly.country_id) !== state.country) return false;
      if (state.sheet && anomaly.sheet !== state.sheet) return false;
      if (state.category && anomaly.category !== state.category) return false;
      const review = reviewFor(anomaly);
      if (state.status && review.status !== state.status) return false;
      if (!query) return true;
      return [countryName(anomaly), anomaly.workbook, anomaly.sheet, anomaly.kpi, anomaly.column, anomaly.title, anomaly.message, anomaly.category, anomaly.category_label, anomaly.sent_cell, anomaly.received_cell, JSON.stringify(anomaly.before), JSON.stringify(anomaly.after), review.notes].some(value => text(value).toLocaleLowerCase().includes(query));
    }).sort((a, b) => Number(b.severity === "critical") - Number(a.severity === "critical") || text(countryName(a)).localeCompare(text(countryName(b))) || text(a.sheet).localeCompare(text(b.sheet)) || text(a.id).localeCompare(text(b.id)));
  }
  function rawValue(cell) {
    if (!cell) return "No cell to compare";
    if (cell.formula && cell.cache_available === false) return "Unknown · saved result unavailable";
    if (cell.value === undefined || cell.value === null || cell.value === "") return "Blank";
    if (typeof cell.value === "boolean") return cell.value ? "TRUE" : "FALSE";
    return text(cell.value);
  }
  function evidence(label, address, cell, after = false) {
    return el("section", {class: "evidence" + (after ? " after" : "")},
      el("h2", {}, label, el("span", {class: "address"}, address || "No cell location")),
      el("p", {class: "evidence-value"}, rawValue(cell)),
      cell && cell.formula ? el("pre", {class: "formula"}, cell.formula) : null);
  }
  function detailsRow(anomaly, index, isExpanded) {
    const review = reviewFor(anomaly);
    const country = countries.get(String(anomaly.country_id)) || {};
    const notes = el("textarea", {id: "notes-" + index, class: "review-notes", rows: "4", maxlength: "10000", placeholder: "Context, reason for acceptance, or next action…", oninput: event => saveReview(anomaly, {notes: event.target.value}, false)});
    notes.value = review.notes;
    return el("tr", {id: "detail-" + index, class: "detail-row", hidden: !isExpanded}, el("td", {colspan: "5"},
      el("div", {class: "detail-panel"},
        el("div", {},
          anomaly.message ? el("p", {class: "detail-description"}, anomaly.message) : null,
          el("div", {class: "evidence-grid"}, evidence("Sent · before", anomaly.sent_cell, anomaly.before), evidence("Received · after", anomaly.received_cell, anomaly.after, true)),
          el("div", {class: "files"},
            country.sent_file ? el("div", {}, "Sent file: ", country.sent_file) : null,
            country.received_file ? el("div", {}, "Received file: ", country.received_file) : null,
            !country.sent_file && !country.received_file && anomaly.workbook ? el("div", {}, "Workbook: ", anomaly.workbook) : null),
          el("p", {class: "finding-id"}, "Finding ID: ", anomaly.id)),
        el("div", {}, el("label", {class: "notes-label", for: "notes-" + index}, "Review notes"), notes, el("p", {id: "saved-" + index, class: "save-state"}, savedLabel(review))))));
  }
  function findingRows(anomaly) {
    const index = rowIndex.get(String(anomaly.id));
    const review = reviewFor(anomaly);
    const isExpanded = expanded.has(String(anomaly.id));
    const status = el("select", {id: "status-" + index, class: "review-select " + review.status, "aria-label": `Review status for ${countryName(anomaly)}: ${anomaly.title || anomaly.kpi || anomaly.id}`, onchange: event => saveReview(anomaly, {status: event.target.value})}, Object.entries(statuses).map(([key, label]) => el("option", {value: key}, label)));
    status.value = review.status;
    const toggle = el("button", {id: "toggle-" + index, type: "button", class: "text-button detail-toggle", "aria-expanded": String(isExpanded), "aria-controls": "detail-" + index, "aria-label": `Evidence and notes for ${anomaly.title || anomaly.id}`, onclick: event => {
      const id = String(anomaly.id);
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      const open = expanded.has(id);
      $("detail-" + index).hidden = !open;
      $("row-" + index).classList.toggle("expanded", open);
      event.currentTarget.setAttribute("aria-expanded", String(open));
      event.currentTarget.textContent = open ? "Close ↑" : "Details ↓";
    }}, isExpanded ? "Close ↑" : "Details ↓");
    return [el("tr", {id: "row-" + index, class: "finding-row" + (isExpanded ? " expanded" : "")},
      el("td", {}, el("div", {class: "country-name"}, countryName(anomaly))),
      el("td", {}, el("div", {class: "sheet-name"}, anomaly.sheet || "Workbook"), anomaly.kpi ? el("div", {class: "secondary-text"}, anomaly.kpi) : null,
        anomaly.column ? el("div", {class: "secondary-text"}, "Column: ", anomaly.column) : null),
      el("td", {}, el("div", {class: "finding-title"}, anomaly.severity === "critical" ? el("span", {class: "critical"}, "Critical") : null, anomaly.title || anomaly.category_label || humanize(anomaly.category)),
        el("div", {class: "finding-message"}, anomaly.message || ""),
        anomaly.title && anomaly.title !== (anomaly.category_label || humanize(anomaly.category)) ? el("div", {class: "category"}, anomaly.category_label || humanize(anomaly.category)) : null),
      el("td", {}, status, el("div", {id: "notes-indicator-" + index, class: "notes-indicator", hidden: !review.notes}, "Note added")),
      el("td", {}, toggle)), detailsRow(anomaly, index, isExpanded)];
  }
  function renderFindings() {
    const focused = document.activeElement;
    const focusedId = focused?.id;
    const selection = focused?.tagName === "TEXTAREA" ? [focused.selectionStart, focused.selectionEnd] : null;
    const records = filteredFindings();
    const pages = Math.max(1, Math.ceil(records.length / state.pageSize));
    state.page = Math.min(state.page, pages);
    const offset = (state.page - 1) * state.pageSize;
    replace("results-summary", el("strong", {}, records.length.toLocaleString()), ` of ${anomalies.length.toLocaleString()} high-criticality anomalies`);
    replace("findings-body", records.slice(offset, offset + state.pageSize).flatMap(findingRows));
    $("findings-empty").hidden = records.length > 0;
    replace("findings-empty", el("strong", {}, anomalies.length ? "No matching anomalies" : "No high-criticality anomalies"), el("p", {}, anomalies.length ? "Change or clear the filters to see more findings." : "This audit has no high or critical findings to review."));
    $("page-summary").textContent = records.length ? `${(offset + 1).toLocaleString()}–${Math.min(offset + state.pageSize, records.length).toLocaleString()} of ${records.length.toLocaleString()}` : "0 anomalies";
    $("previous-page").disabled = state.page <= 1;
    $("next-page").disabled = state.page >= pages;
    if (focusedId && focused !== document.activeElement) {
      const target = $(focusedId) || $("filter-status");
      target.focus({preventScroll: true});
      if (selection && target.tagName === "TEXTAREA") target.setSelectionRange(...selection);
    }
  }

  function currentReviews() { return [...reviews.values()].filter(review => anomalyById.has(review.anomaly_id)); }
  function download(content, mime, name) {
    const url = URL.createObjectURL(new Blob([content], {type: mime}));
    const anchor = el("a", {href: url, download: name});
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  function safeJSON(value) {
    return JSON.stringify(value).replace(/&/g, "\\u0026").replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
  }
  function safeFilename(value) { return text(value).replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 120) || "pops-high-priority"; }
  function saveReviewedReport() {
    readStoredReviews(); showStorageState();
    const report = {...payload, initial_reviews: currentReviews()};
    const clone = documentTemplate.cloneNode(true);
    clone.querySelector("#report-payload").textContent = safeJSON(report);
    download("<!doctype html>\n" + clone.outerHTML, "text/html;charset=utf-8", safeFilename(payload.title || "POPS high-criticality anomalies") + " - reviewed.html");
    toast("Reviewed report saved with all high-criticality findings, decisions and notes.");
  }
  async function importReviews(event) {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error("Review files must be smaller than 10 MB.");
      const imported = JSON.parse(await file.text());
      if (!imported || imported.schema_version !== 1 || !Array.isArray(imported.reviews)) throw new Error("Choose a POPS review JSON file with schema_version 1 and a reviews list.");
      readStoredReviews();
      const result = mergeReviews(imported.reviews, true);
      persistReviews(); renderFindings();
      toast(`${result.matched.toLocaleString()} matching review record(s) loaded; ${result.ignored.toLocaleString()} unmatched or invalid record(s) ignored. Newer decisions are kept.`);
    } catch (error) { toast("Could not import reviews: " + error.message, true); }
    finally { event.target.value = ""; }
  }

  mergeReviews(reviewRecords(payload.initial_reviews), true);
  readStoredReviews(); showStorageState();
  $("demo-badge").hidden = payload.demo !== true;
  $("finding-search").addEventListener("input", event => { state.search = event.target.value; state.page = 1; renderFindings(); });
  $("filter-country").addEventListener("change", event => { state.country = event.target.value; state.page = 1; renderFilters(); renderFindings(); });
  for (const key of ["sheet", "category", "status"]) $("filter-" + key).addEventListener("change", event => { state[key] = event.target.value; state.page = 1; renderFindings(); });
  $("reset-filters").addEventListener("click", () => { for (const key of ["country", "sheet", "category", "status", "search"]) state[key] = ""; state.page = 1; renderFilters(); renderFindings(); });
  $("previous-page").addEventListener("click", () => { state.page--; renderFindings(); });
  $("next-page").addEventListener("click", () => { state.page++; renderFindings(); });
  $("page-size").addEventListener("change", event => { state.pageSize = Number(event.target.value); state.page = 1; renderFindings(); });
  $("save-report").addEventListener("click", saveReviewedReport);
  $("reviews-export").addEventListener("click", () => {
    readStoredReviews(); showStorageState();
    const bundle = {schema_version: 1, tool: "pops-audit-reviews", report_id: payload.report_id, exported_at: new Date().toISOString(), reviews: currentReviews()};
    download(JSON.stringify(bundle, null, 2), "application/json;charset=utf-8", "pops-high-priority-review-decisions.json");
    toast("Review decisions exported. Import this file into a full or focused POPS report with the same findings.");
  });
  $("reviews-import").addEventListener("click", () => $("reviews-file").click());
  $("reviews-file").addEventListener("change", importReviews);
  window.addEventListener("storage", event => {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try { mergeReviews(reviewRecords(JSON.parse(event.newValue))); renderFindings(); } catch (_) { /* Leave this tab's decisions intact. */ }
  });
  renderFilters(); renderFindings();
})();
