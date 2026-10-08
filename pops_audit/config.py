"""Load the editable anomaly-detector configuration without opening workbooks."""
from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
import re
import unicodedata

import yaml


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("Configuration keys must be text")
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _normal(value):
    return " ".join(value.split()).casefold()


def _text(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be nonempty text")
    return value.strip()


def _object(value, context):
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return dict(value)


def _known(settings, allowed, context):
    unknown = set(settings) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {context} setting(s): {', '.join(sorted(unknown))}")


def _boolean(settings, key, default, context):
    value = settings.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{key} must be true or false")
    settings[key] = value


def _strings(value, context):
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    result = [_text(item, context) for item in value]
    if len({_normal(item) for item in result}) != len(result):
        raise ValueError(f"{context} contains duplicate names")
    return result


def _period_text(value, context):
    return str(value) if type(value) is int else _text(value, context)


def _period_names(value, context):
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list of column names")
    return _strings([_period_text(item, context) for item in value], context)


def _named(settings, context):
    settings["name"] = _text(settings.get("name"), f"{context}.name")
    settings["aliases"] = _strings(settings.get("aliases", []), f"{context}.aliases")
    names = [settings["name"], *settings["aliases"]]
    if len({_normal(name) for name in names}) != len(names):
        raise ValueError(f"{context} aliases must differ from the canonical name")
    _boolean(settings, "required", True, context)


def _positive(value, context, maximum=1048576):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{context} must be an integer from 1 to {maximum}")
    return value


def _column(value, context):
    value = _text(value, context).upper()
    if not re.fullmatch(r"[A-Z]{1,3}", value):
        raise ValueError(f"{context} must be an Excel column letter, for example B")
    number = 0
    for letter in value:
        number = number * 26 + ord(letter) - 64
    if number > 16384:
        raise ValueError(f"{context} exceeds Excel column XFD")
    return value


def _range(value, context):
    value = _text(value, context).replace("$", "").upper()
    points = value.split(":")
    if len(points) not in (1, 2):
        raise ValueError(f"{context} must be a bounded A1 cell range, for example B4:D8")
    positions = []
    for point in points:
        match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", point)
        if match is None:
            raise ValueError(f"{context} must be a bounded A1 cell range, for example B4:D8")
        letters = _column(match.group(1), context)
        number = 0
        for letter in letters:
            number = number * 26 + ord(letter) - 64
        positions.append((number, _positive(int(match.group(2)), context)))
    if positions[0][0] > positions[-1][0] or positions[0][1] > positions[-1][1]:
        raise ValueError(f"{context} has reversed cell coordinates")
    return value


def _sheet(rule, historical):
    rule = _object(rule, "sheet")
    _known(rule, {"name", "aliases", "required", "enabled", "mode", "columns", "historical_columns",
                  "kpis", "identifier_header", "table_name", "header_row", "identifier_column",
                  "data_range", "label_columns", "header_rows", "ignore_ranges"}, "sheet")
    _named(rule, "sheet")
    for name in [rule["name"], *rule["aliases"]]:
        if len(name) > 31 or re.search(r"[\\/*?:\[\]]", name) or name.startswith("'") or name.endswith("'"):
            raise ValueError(f"Invalid worksheet name: {name!r}")
    _boolean(rule, "enabled", True, "sheet")
    rule.setdefault("mode", "layout")
    if rule["mode"] not in ("layout", "identifiers"):
        raise ValueError("sheet.mode must be layout or identifiers")
    if not isinstance(rule.get("columns"), list) or not rule["columns"]:
        raise ValueError("sheet.columns must be a nonempty list")
    columns, column_names = [], {}
    for raw in rule["columns"]:
        column = {"name": _period_text(raw, "column name")} if isinstance(raw, str) or type(raw) is int else _object(raw, "column")
        _known(column, {"name", "aliases", "required", "include_in_filling"}, "column")
        column["name"] = _period_text(column.get("name"), "column.name")
        column["aliases"] = _period_names(column.get("aliases", []), "column.aliases")
        _named(column, "column")
        _boolean(column, "include_in_filling", True, "column")
        for name in [column["name"], *column["aliases"]]:
            key = _normal(name)
            if key in column_names:
                raise ValueError(f"Ambiguous column name or alias: {name!r}")
            column_names[key] = column["name"]
        columns.append(column)
    rule["columns"] = columns
    requested_history = _period_names(rule.get("historical_columns", historical), "sheet.historical_columns")
    if "historical_columns" in rule:
        unknown = [name for name in requested_history if _normal(name) not in column_names]
        if unknown:
            raise ValueError(f"Historical columns are not configured on {rule['name']}: {', '.join(unknown)}")
    # A sheet may intentionally have a smaller period set than the global default.
    rule["historical_columns"] = list(dict.fromkeys(
        column_names[_normal(name)] for name in requested_history if _normal(name) in column_names))
    for key in ("data_range",):
        if rule.get(key) is not None:
            rule[key] = _range(rule[key], f"sheet.{key}")
    ignored = rule.get("ignore_ranges", [])
    if not isinstance(ignored, list):
        raise ValueError("sheet.ignore_ranges must be a list")
    rule["ignore_ranges"] = [_range(value, "sheet.ignore_ranges") for value in ignored]
    if rule["mode"] == "identifiers":
        if "kpis" in rule or "label_columns" in rule or "header_rows" in rule:
            raise ValueError("Identifier mode uses existing identifiers; kpis, label_columns and header_rows are not allowed")
        rule["identifier_header"] = _text(rule.get("identifier_header", "KPI"), "sheet.identifier_header")
        if rule.get("identifier_column") is not None:
            rule["identifier_column"] = _column(rule["identifier_column"], "sheet.identifier_column")
        if rule.get("header_row") is not None:
            _positive(rule["header_row"], "sheet.header_row")
        if rule.get("table_name") is not None:
            rule["table_name"] = _text(rule["table_name"], "sheet.table_name")
    else:
        if any(key in rule for key in ("identifier_header", "identifier_column", "header_row", "table_name")):
            raise ValueError("Identifier settings require mode: identifiers")
        if rule.get("label_columns") is not None:
            if not isinstance(rule["label_columns"], list) or not rule["label_columns"]:
                raise ValueError("sheet.label_columns must be a nonempty list or null")
            rule["label_columns"] = [_column(value, "sheet.label_columns") for value in rule["label_columns"]]
        if rule.get("header_rows") is not None:
            if not isinstance(rule["header_rows"], list) or not rule["header_rows"]:
                raise ValueError("sheet.header_rows must be a nonempty list or null")
            for value in rule["header_rows"]:
                _positive(value, "sheet.header_rows")
        if not isinstance(rule.get("kpis"), list):
            raise ValueError("Layout mode requires a kpis list")
        kpis, counts, seen, aliases = [], {}, set(), {}
        for raw in rule["kpis"]:
            kpi = {"name": raw} if isinstance(raw, str) else _object(raw, "KPI")
            _known(kpi, {"name", "aliases", "occurrence", "required"}, "KPI")
            _named(kpi, "KPI")
            key = _normal(kpi["name"])
            occurrence = kpi.get("occurrence", counts.get(key, 0) + 1)
            _positive(occurrence, "KPI.occurrence")
            if (key, occurrence) in seen:
                raise ValueError(f"Duplicate KPI occurrence: {kpi['name']!r} #{occurrence}")
            for name in [kpi["name"], *kpi["aliases"]]:
                normalized = _normal(name)
                if normalized in aliases and aliases[normalized] != key:
                    raise ValueError(f"Ambiguous KPI name or alias: {name!r}")
                aliases[normalized] = key
            seen.add((key, occurrence))
            counts[key] = max(counts.get(key, 0), occurrence)
            kpi["occurrence"] = occurrence
            kpis.append(kpi)
        rule["kpis"] = kpis
    return rule


def _read_yaml(path, context):
    with path.open(encoding="utf-8") as handle:
        return _object(yaml.load(handle, Loader=_UniqueLoader), context)


def _expanded_rules(settings, path):
    """Expand a compact catalogue into the same sheet rules used by legacy files."""
    compact = "sheets" not in settings
    if compact:
        raw = Path(_text(settings.get("catalog_file", str(path.parent / "catalog.yaml")), "catalog_file")).expanduser()
        catalog_path = (raw if raw.is_absolute() else path.parent.parent / raw).resolve()
        settings["catalog_file"] = catalog_path
        catalog = _read_yaml(catalog_path, "catalogue")
        _known(catalog, {"version", "sheets"}, "catalogue")
        if type(catalog.get("version")) is not int or catalog["version"] != 1:
            raise ValueError("catalog.yaml requires version: 1")
        entries = _object(catalog.get("sheets"), "catalogue.sheets")
        if not entries:
            raise ValueError("catalogue.sheets must not be empty")
        raw_rules = []
        for name, entry in entries.items():
            rule = {"kpis": entry} if isinstance(entry, list) else _object(entry, f"catalogue sheet {name}")
            if "name" in rule:
                raise ValueError("Catalogue sheet names are the keys; omit nested name settings")
            raw_rules.append({"name": name, **rule})
    else:
        if not isinstance(settings["sheets"], list) or not settings["sheets"]:
            raise ValueError("sheets must be a nonempty list")
        raw_rules = [_object(rule, "sheet") for rule in settings["sheets"]]
    by_name = {}
    for index, rule in enumerate(raw_rules):
        for name in [_text(rule.get("name"), "sheet.name"), *_strings(rule.get("aliases", []), "sheet.aliases")]:
            key = _normal(name)
            if key in by_name and by_name[key] != index:
                raise ValueError(f"Sheet names/aliases overlap: {name!r}")
            by_name[key] = index
    overrides = _object(settings.get("sheet_overrides", {}), "sheet_overrides")
    overridden = set()
    for name, override in overrides.items():
        index = by_name.get(_normal(_text(name, "sheet_overrides name")))
        if index is None:
            raise ValueError(f"Unknown sheet_overrides sheet: {name!r}")
        if index in overridden:
            raise ValueError(f"Duplicate sheet override through aliases: {name!r}")
        override = _object(override, f"sheet_overrides.{name}")
        if "name" in override:
            raise ValueError("sheet_overrides cannot rename a catalogue sheet")
        raw_rules[index].update(override)
        overridden.add(index)
    result = []
    for source in raw_rules:
        rule = deepcopy(source)
        identifier_mode = rule.get("mode", "layout") == "identifiers"
        if "columns" not in rule:
            key = "kpi_columns" if identifier_mode else "common_columns"
            rule["columns"] = deepcopy(settings.get(key, settings.get("common_columns")))
            if rule["columns"] is None:
                raise ValueError(f"Provide {key} in settings.yaml or columns on sheet {rule['name']!r}")
        aliases = _object(rule.pop("column_aliases", {}), f"{rule['name']}.column_aliases")
        alias_map = {_normal(_period_text(name, "column_aliases name")):
                     _period_names(value if isinstance(value, list) else [value], "column_aliases")
                     for name, value in aliases.items()}
        if alias_map and isinstance(rule["columns"], list):
            columns = []
            for raw in rule["columns"]:
                column = {"name": _period_text(raw, "column name")} if isinstance(raw, str) or type(raw) is int else _object(raw, "column")
                name = _period_text(column.get("name"), "column.name")
                existing = _period_names(column.get("aliases", []), "column.aliases")
                seen = {_normal(name), *(_normal(alias) for alias in existing)}
                for alias in alias_map.get(_normal(name), []):
                    if _normal(alias) not in seen:
                        existing.append(alias)
                        seen.add(_normal(alias))
                column["aliases"] = existing
                columns.append(column)
            rule["columns"] = columns
        result.append(_sheet(rule, settings["historical_columns"]))
    if "sheets_to_check" in settings:
        requested = _strings(settings["sheets_to_check"], "sheets_to_check")
        selected = []
        for name in requested:
            matches = [rule for rule in result if _normal(name) in {_normal(item) for item in [rule["name"], *rule["aliases"]]}]
            if len(matches) != 1:
                raise ValueError(f"Unknown or ambiguous sheets_to_check entry: {name!r}")
            canonical = matches[0]["name"]
            if canonical in selected:
                raise ValueError(f"Duplicate sheets_to_check entry through aliases: {canonical!r}")
            if compact and matches[0]["mode"] == "layout" and not matches[0]["kpis"]:
                raise ValueError(f"Add KPI labels to catalog.yaml before selecting sheet {canonical!r}")
            selected.append(canonical)
        for rule in result:
            rule["enabled"] = rule["name"] in selected
    else:
        selected = [rule["name"] for rule in result if rule["enabled"]]
    settings["sheets_to_check"] = selected
    return result


def load_config(path) -> dict:
    """Return validated settings, with paths relative to the config folder's parent."""
    path = Path(path).expanduser().resolve()
    settings = _read_yaml(path, "configuration")
    _known(settings, {"version", "sent_dir", "received_dir", "output_report", "report_title", "filling_scope",
                      "ignore_sheets", "checks", "severity_overrides", "sheets", "relative_tolerance",
                      "absolute_tolerance", "historical_columns", "prefilled_changes", "ignore_formula_case",
                      "country_names", "catalog_file", "sheets_to_check", "common_columns", "kpi_columns",
                      "sheet_overrides"}, "top-level")
    if type(settings.get("version")) is not int or settings["version"] != 1:
        raise ValueError("settings.yaml requires version: 1")
    root = path.parent.parent
    for key, default in (("sent_dir", "data/sent"), ("received_dir", "data/received"),
                         ("output_report", "output/report.html")):
        raw = Path(_text(settings.get(key, default), key)).expanduser()
        settings[key] = (raw if raw.is_absolute() else root / raw).resolve()
    if settings["sent_dir"] == settings["received_dir"]:
        raise ValueError("sent_dir and received_dir must differ")
    if settings["output_report"].suffix.lower() not in {".html", ".htm"}:
        raise ValueError("output_report must be an HTML file (.html or .htm)")
    if settings["output_report"] in {settings["sent_dir"], settings["received_dir"]}:
        raise ValueError("output_report must differ from the input directories")
    settings["report_title"] = _text(settings.get("report_title", "POPS workbook anomaly report"), "report_title")
    # Retain old files, but the current reporting rules always keep KPI apart
    # from overall business-sheet filling and use the fixed severity scheme.
    settings["filling_scope"] = "non_kpi"
    settings["severity_overrides"] = {}
    settings["ignore_sheets"] = _strings(settings.get("ignore_sheets", []), "ignore_sheets")
    countries = _object(settings.get("country_names", {}), "country_names")
    settings["country_names"] = {}
    for filename, display in countries.items():
        _text(filename, "country_names filename")
        if "/" in filename or "\\" in filename or filename in (".", ".."):
            raise ValueError("country_names keys must be filenames, not paths")
        key = unicodedata.normalize("NFC", filename).casefold()
        if key in settings["country_names"]:
            raise ValueError(f"Duplicate country_names filename: {filename!r}")
        settings["country_names"][key] = _text(display, "country_names display name")
    settings["historical_columns"] = _period_names(settings.get("historical_columns", ["2024", "2025"]), "historical_columns")
    settings.setdefault("prefilled_changes", "historical")
    if settings["prefilled_changes"] not in ("historical", "all"):
        raise ValueError("prefilled_changes must be historical or all")
    _boolean(settings, "ignore_formula_case", True, "settings")
    for key in ("relative_tolerance", "absolute_tolerance"):
        value = settings.get(key, 1e-9)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
        settings[key] = float(value)
    for key in ("checks", "severity_overrides"):
        settings[key] = _object(settings.get(key, {}), key)
        for code, value in settings[key].items():
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
                raise ValueError(f"{key} keys must be uppercase anomaly category codes")
            if key == "checks" and not isinstance(value, bool):
                raise ValueError(f"checks.{code} must be true or false")
            if key == "severity_overrides" and value not in ("critical", "high", "medium", "low", "info"):
                raise ValueError(f"severity_overrides.{code} must be critical, high, medium, low or info")
    rules, sheet_names = [], set()
    for rule in _expanded_rules(settings, path):
        names = {_normal(name) for name in [rule["name"], *rule["aliases"]]}
        if names & sheet_names:
            raise ValueError(f"Sheet names/aliases overlap: {rule['name']!r}")
        sheet_names.update(names)
        rules.append(rule)
    settings["sheets"] = rules
    return settings
