# POPS Anomaly Detection

Compare the Excel workbooks sent to countries with the workbooks they return, then review structural changes, formulas, values and filling in a self-contained HTML report. The tool reads the workbooks without changing or recalculating them.

**Author:** Adnane El Bouhali  
**Team:** Value Chain team — BNP Paribas Personal Finance

## Place in the POPS process

```text
Sent templates + returned country workbooks
                    |
             POPS_AD comparison
                    |
        Value Chain review of the report
                    |
       Country correction and recheck, if needed
                    |
  Reviewed country workbooks -> POPS_CONSO
                            -> POPS_Tables_Inter
                            -> POPS_Synthese
```

POPS_AD provides evidence for the team's review before consolidation. The handoff to consolidation is the selected country workbooks; the HTML report is a review document. The tool does not send correction requests, approve workbooks or launch the downstream projects. Review statuses and severity do not automatically block consolidation.

## Requirements

- Python 3.10 or later.
- The packages in [requirements.txt](requirements.txt): `openpyxl` and `PyYAML`.
- Readable, unencrypted `.xlsx` or `.xlsm` input files.
- A browser with JavaScript enabled to use the report and its review controls.

Desktop Excel is not required to run the comparison. Formula results are read from values saved in the workbooks; use Excel to calculate and save them beforehand when necessary. Report generation and viewing work offline after dependencies are installed.

## Installation

Open PowerShell in the `POPS_AD` folder. Create a local environment and install the supplied requirements:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The Python selected by `py -3` must be version 3.10 or later. If the Python launcher is unavailable, use your Python executable in the first command. Dependency installation needs access to the packages, usually through the internet. The commands below use the environment's interpreter directly, so environment activation is unnecessary.

## Quick start

1. Put the original sent workbooks in `data/sent`.
2. Put the returned workbooks in `data/received`, keeping the same filenames.
3. Review the paths, selected sheets and periods in [config/settings.yaml](config/settings.yaml).
4. Validate the configuration, then generate and open the report:

```powershell
.\.venv\Scripts\python.exe main.py --validate-config
.\.venv\Scripts\python.exe main.py --open
```

Each run creates two self-contained reports: the full report at `output/report.html` and a simplified high-priority report at `output/report_high_priority.html`. A later run using the same output paths replaces those reports, so save any reviewed copy you need to retain.

To open the simplified report directly after generation:

```powershell
.\.venv\Scripts\python.exe main.py --open-high-priority
```

Files are paired by their complete filename, including the extension, ignoring letter case and equivalent Unicode spelling. For example, `France.xlsx` does not match `France revised.xlsx`. Only files directly inside the input directories are examined; subdirectories are not searched. Excel lock files beginning with `~$` are ignored. Missing, unexpected, ambiguous and unreadable files are reported separately; ambiguous matches are not guessed.

The file inventory also recognises `.xls` and `.xlsb`, but the reader cannot analyse those formats or encrypted workbooks. Save them as readable, unencrypted `.xlsx` or `.xlsm` files before comparison.

To select a configuration and a different output location for one run:

```powershell
.\.venv\Scripts\python.exe main.py --config .\config\settings.yaml --output .\output\report_review.html --open
```

`--output` must end in `.html` or `.htm`. A relative command-line output path is resolved from the current working directory. The companion report adds `_high_priority` before that extension; for example, `report_review.html` also creates `report_review_high_priority.html`. Use either `--open` for the full report or `--open-high-priority` for the simplified report.

## Configuration

### Routine settings

[config/settings.yaml](config/settings.yaml) contains the run settings. [config/catalog.yaml](config/catalog.yaml) contains the sheet definitions, aliases and ordered business KPI labels. Both use `version: 1` for their configuration schema; this is not a reporting year.

| Setting | Purpose |
| --- | --- |
| `sent_dir`, `received_dir` | Separate folders containing the sent and returned workbooks. |
| `output_report` | Default HTML output path. |
| `report_title` | Report title. |
| `catalog_file` | Catalogue used to define the sheets and their business labels. |
| `sheets_to_check` | Catalogue sheet names or aliases selected for detailed checks. |
| `common_columns` | Periods shared by business/layout sheets unless a sheet defines its own `columns`. |
| `kpi_columns` | Periods for identifier-mode sheets, including `KPI`. |
| `historical_columns` | Periods where changes or clearing of prefilled constants are checked. |

With the supplied folder layout, configuration paths are relative to the project root. More precisely, the loader resolves relative paths from the parent of the configuration file's directory. Keep alternative settings files inside `config` or use absolute paths deliberately.

The supplied selection is `ID Card`, `OBS KPI`, `FTE`, `CVC`, `GRANTING 2027-2030`, `CUSTOMER SERVICES 2027-2030`, `CORE 2027-2030`, `NPL SALES` and `KPI`. The period lists cover the configured 2024–2030 headings, and historical protection covers 2024 and 2025. Check these against the actual sent templates before each campaign.

Removing a sheet from `sheets_to_check` stops its detailed checks. Added and removed tabs remain in the workbook inventory. An empty list (`sheets_to_check: []`) requests inventory-only reporting.

New input in previously blank cells is allowed. Prefilled constants outside the historical periods may change, while supplied formulas remain checked. Use `prefilled_changes: all` only when changes to prefilled constants should be monitored in every configured period.

### Sheet definitions and KPI labels

Business sheets use `mode: layout` by default. Their `kpis` lists contain the expected labels in occurrence order. Repeated labels are intentional: several rows can be named `GRANTING`, for example. Keep those repetitions and their order. When sent and returned occurrence counts differ, the tool does not guess which repeated rows correspond.

The sheet named `KPI` uses `mode: identifiers`. Its expected identifiers come from the sent workbook, rather than a configured list of display labels. Identifier omissions, duplicates, additions and lookup-sensitive changes are checked. Extra whitespace and a number-to-text conversion can matter; ordinary case-only differences and numeric `1` versus `1.0` are normalised.

Sheet `aliases` support genuine alternative tab names. `column_aliases` maps the configured period names to alternative physical headers, such as `F3 2026` to `Forecast 3 2026`. An alias does not add a period to the selected column list. The catalogue includes commented placeholders for `NPL SALES2`, `CREDIT BUREAU`, `MBS (OPEX)` and `PROCUREMENT`; define their actual KPI labels before selecting them.

### Preparing a new reporting cycle

There is no single year parameter or automatic rollover. Update the configuration to match the new sent templates:

1. Set the input and output paths for the intended campaign. Preserve the original sent files as the comparison baseline.
2. Update `common_columns` and `kpi_columns` to the exact required period headings. Set `historical_columns` to the periods whose prefilled values must remain protected.
3. Check any year-bearing sheet names in the catalogue and `sheets_to_check`. Update catalogue names and genuine aliases as needed; `sheet_overrides` cannot rename a catalogue entry.
4. Update the relevant `column_aliases`, especially the `Actual`, `Forecast` and `Budget` headers on `KPI`. Check any sheet-specific `columns` lists, because they take precedence over the shared lists.
5. Compare business KPI labels and their repeated occurrences with the new templates. Check the identifier header and any explicit location constraints on `KPI`.
6. Run configuration validation, then compare representative sent/returned pairs. Inspect located sheets, periods, findings and filling before processing the full campaign. Validation alone does not open workbooks.

The following are **partial examples**, only appropriate if the future templates use these headings. Edit the corresponding existing mappings; do not replace the full files or add duplicate keys. Retain every period needed for the actual campaign.

Partial `config/settings.yaml`:

```yaml
common_columns: ['2026', 'F3 2027']
kpi_columns: ['2026', 'F3 2027']
historical_columns: ['2026']
```

Partial `config/catalog.yaml`, showing the existing `KPI` entry:

```yaml
version: 1
sheets:
  KPI:
    mode: identifiers
    column_aliases:
      '2026': Actual 2026
      F3 2027: Forecast 3 2027
```

The projects do not synchronise their settings automatically. Review the corresponding sheet and period expectations in consolidation, intermediary tables and synthesis when the templates change.

### Targeted adjustments

Bare period names and KPI labels default to `required: true`. Use an object when an alias or specific flag is needed. For example, this partial settings excerpt excludes 2024 from filling counts while retaining its configured checks:

```yaml
common_columns:
  - name: '2024'
    include_in_filling: false
  - '2025'
  - PLAN 2026
```

`required: false` allows a configured column or KPI to be absent from the sent template; it does not suppress a removal finding when that item existed in the sent workbook. Optional periods present in the template can still contribute to filling.

Use `sheet_overrides` for a targeted sheet rule. This illustrative partial excerpt excludes two areas and restricts historical protection on `FTE`:

```yaml
sheet_overrides:
  FTE:
    ignore_ranges: ['B4:D8', 'G12']
    historical_columns: ['2024']
```

An override replaces each specified setting; a `columns` or `kpis` override replaces the entire inherited list. `data_range` and `ignore_ranges` accept bounded A1 ranges. Layout rules can use `label_columns` and `header_rows` to constrain discovery. Identifier rules instead accept `identifier_header` (default `KPI`), `table_name`, `header_row` and `identifier_column`. Do not mix layout-only and identifier-only keys.

Other supported adjustments include:

- `country_names`: map full workbook filenames to report display names; otherwise the filename without its extension supplies the label.
- `checks: {FORMULA_MODIFIED: false}`: suppress that anomaly category without changing filling calculations.
- `relative_tolerance` and `absolute_tolerance`: numeric comparison tolerances, both defaulting to `1e-9`.
- `ignore_formula_case`: defaults to `true`.

The loader rejects duplicate YAML keys and unknown settings. It also accepts an inline top-level `sheets` list, which bypasses the separate catalogue; keep the supplied catalogue-based structure unless intentionally using that alternative format. `filling_scope` and `severity_overrides` are accepted compatibility keys whose values are ignored: overall filling excludes `KPI`, and the fixed severity rules apply.

## Outputs and review

### Simplified high-priority report

`report_high_priority.html` opens directly on a compact list of high-priority anomalies, with no overview, filling measures or inventory. Filter by country, sheet, category or review status, and search the findings. Choose **Unreviewed**, **Accepted**, **Needs investigation** or **Needs correction** for each anomaly, and record notes alongside its evidence.

This report uses the same severity rules as the full report: currently missing configured business KPI occurrences and selected required sheets. It also includes `critical` findings if supplied by a future producer. Medium and low findings and internal baseline issues are excluded from the file itself. An empty list means no high-priority findings in the analysed scope; the full report may still contain other issues.

Decisions save in the browser where storage is available. Use **Save reviewed report** to download a portable HTML copy containing the decisions, or export/import reviews JSON to transfer them between the full and simplified reports. Findings retain the same identifiers and review status codes in both reports; **Needs investigation** corresponds to **Investigating** in the full report. Browser storage for local HTML files can differ by file or browser, so use a saved copy or JSON transfer when moving between reports or devices.

### Full report

The HTML contains the file and sheet inventory, filling measures, findings and comparison evidence. Findings show sent and returned addresses, with values and formulas where available. Filter by country, sheet, category, severity or review status, or search for a KPI.

| Priority | Meaning in the implemented checks |
| --- | --- |
| **High** | Loss of a configured business KPI occurrence found in the sent workbook, or removal of a selected required sheet. |
| **Medium** | Other anomalies, including file-pairing issues, structural changes, formula/value changes, identifier issues and Excel errors. Missing identifiers within the sheet named `KPI` are in this category. |
| **Low** | Newly invalid numeric input or saved results, such as numeric-looking text, Boolean values and zeros. |

Severity is a review priority, not a guarantee of downstream failure or proof of country responsibility. Untouched blanks and zero placeholders affect filling without producing a separate change finding. A newly invalid saved formula result can produce a low-priority finding even when the formula itself is unchanged.

Record a status — **Unreviewed**, **Accepted**, **Investigating** or **Needs correction** — and add notes. Reviews persist in local browser storage when available. If storage is unavailable, the report warns that decisions remain in the open tab until saved or exported.

Available actions are:

- **Save reviewed report:** download an HTML copy with review decisions embedded.
- **Save country report:** download the selected country's data and decisions.
- **Export reviews JSON / Import reviews JSON:** carry decisions between reports with matching findings. Unmatched records are ignored; materially changed findings may have different identifiers.
- **Export filtered CSV:** download the displayed subset of findings and review notes.
- **Print report:** use the browser's printing function.

Review actions do not rewrite the original HTML or the source workbooks. Nothing is uploaded by the report. Accepting a finding records a decision; it does not change the filling rate or repair the workbook.

### Interpreting filling

A filled cell contains a saved, finite, nonzero numeric value. Negative numbers and numeric percentages qualify. Blanks, zero, text, Boolean values and Excel errors do not. Numeric-looking text is not converted into a number.

Expected cells come from confirmed sent-template KPI/period intersections. A definitively missing returned row, column or sheet does not shrink that denominator; extra returned rows cannot improve the rate. Unlocatable sent intersections are excluded. Missing saved formula results and ambiguous returned locations are **unknown**.

- **Exact filling rate:** filled / expected, available when there are expected cells and no unknowns.
- **Known-cell rate:** filled / (expected − unknown), when that denominator is positive.
- **Coverage:** (expected − unknown) / expected, when there are expected cells.

Coverage describes whether the confirmed expected cells can be measured; it does not measure all workbook content. Overall filling uses selected business sheets excluding `KPI`, which has a separate result. Country and overall totals combine cell counts rather than averaging percentages; unmatched or unreadable pairs do not enter matched-country filling. Finding filters do not redefine the selected country's filling denominator.

A numeric cell can be filled while containing an incorrect calculation. A legitimate business zero still does not count as filled under this convention. Filling is therefore separate from correctness and the decision to proceed.

## Project structure

```text
POPS_AD/
|-- main.py                 Command-line entry point
|-- requirements.txt        Python dependencies
|-- config/
|   |-- settings.yaml        Paths, selected sheets and periods
|   `-- catalog.yaml         Sheet rules, aliases and business KPI labels
|-- pops_audit/
|   |-- config.py            Configuration loading and validation
|   |-- reader.py            Read workbook XML and saved formula results
|   |-- locator.py           Locate labels, identifiers and period headings
|   |-- formulas.py          Formula normalisation and reference analysis
|   |-- engine.py            Comparisons, findings and filling calculations
|   |-- report.py            Self-contained HTML generation
|   |-- high_report.py       Simplified high-priority HTML generation
|   `-- demo.py              Synthetic demonstration workbooks
|-- assets/
|   |-- report.css           Report presentation
|   |-- report.js            Full report filters, reviews and exports
|   |-- high_report.css      Simplified report presentation
|   `-- high_report.js       Simplified report filters and reviews
|-- tests/                  Report generation and CLI regression checks
|-- data/
|   |-- sent/                Original templates
|   `-- received/            Country returns
`-- output/                 Generated HTML reports
```

## Validation and demonstration

Show supported command-line options:

```powershell
.\.venv\Scripts\python.exe main.py --help
```

Validate the settings and catalogue without reading country workbooks:

```powershell
.\.venv\Scripts\python.exe main.py --validate-config
```

Generate a clearly marked synthetic report without reading the country input folders:

```powershell
.\.venv\Scripts\python.exe main.py --demo --open
```

The demonstration uses the actual reader and comparison engine with generated workbooks. By default it writes `demo_report.html` and `demo_report_high_priority.html` beside the configured output report; `--output` can override that destination. Use `--demo --open-high-priority` to open the simplified example. It demonstrates behaviour but does not validate the real templates.

Run the report generation and command-line regression checks with the standard Python test runner:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Scope and limits

Detailed checks cover selected KPI/period cells, formulas, historical constants, identifiers, Excel errors and relevant names/external-link targets used by compared formulas. For a uniquely confirmed KPI structured table, the complete visible header list is checked, including non-period columns. Unused names and links are not a general dependency audit, and external target availability is not tested.

The tool normalises harmless formula spacing, case and sheet quoting and accounts for confirmed moved references. It does not establish arbitrary mathematical equivalence. Formatting, charts, VBA and freeform margin comments are outside the detailed business-cell checks.

Problems identified as already present in the sent template or configuration are excluded from the public findings. The report is therefore not a complete template audit. Saved formula results may be missing or stale, and the tool cannot recalculate them. Review the configured scope and the evidence before deciding whether a returned workbook can proceed to consolidation.
