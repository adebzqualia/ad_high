"""Conservative sparse layout discovery for decorated and identifier sheets."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math

from .reader import Sheet, bounds, coordinate, position


def normalize(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return " ".join(str(value).replace("\u00a0", " ").split()).casefold()


@dataclass
class Row:
    key: tuple | str
    identifier: str
    occurrence: int
    row: int
    label_column: int
    columns: dict[str, int] = field(default_factory=dict)
    ambiguous: bool = False

    def coordinate(self, period):
        return coordinate(self.row, self.columns[period]) if period in self.columns else None


@dataclass
class Layout:
    rows: list[Row] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    header_coordinates: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


def _problem(layout, code, message, positions=(), **extra):
    layout.problems.append({"code": code, "message": message,
                            "coordinates": [coordinate(*item) for item in positions], **extra})


def _column(value):
    if isinstance(value, bool):
        raise ValueError("Column must be a letter or a positive integer")
    if isinstance(value, int):
        coordinate(1, value)
        return value
    return position(str(value) + "1")[1]


def _inside(point, rectangle):
    row, column = point
    top, left, bottom, right = rectangle
    return top <= row <= bottom and left <= column <= right


class _View:
    def __init__(self, sheet, rule):
        self.sheet, self.rule = sheet, rule
        self.limit = bounds(rule["data_range"]) if rule.get("data_range") else (1, 1, 1048576, 16384)
        self.ignored = [bounds(reference) for reference in rule.get("ignore_ranges", [])]
        self.merges = [bounds(reference) for reference in sheet.merges]
        self.cells = {point: cell for point, cell in sheet.cells.items()
                      if not any(_inside(point, rectangle) for rectangle in self.ignored)
                      and not any(_inside(point, rectangle) and point != rectangle[:2] for rectangle in self.merges)}
        self.text = {point: normalize(cell.value) for point, cell in self.cells.items()
                     if cell.cache_available and normalize(cell.value)}
        self.periods = list(rule.get("columns", []))
        self.aliases = {item["name"]: {normalize(item["name"]), *(normalize(alias) for alias in item.get("aliases", []))}
                        for item in self.periods}

    def body(self, point):
        return _inside(point, self.limit)

    def label_right(self, point):
        return max((rectangle[3] for rectangle in self.merges if _inside(point, rectangle)), default=point[1])

    def header_refs(self, canonical):
        return [point for point, value in self.text.items()
                if value in self.aliases[canonical]
                and self.limit[1] <= point[1] <= self.limit[3] and point[0] <= self.limit[2]]


def _headers_for_label(view, point, all_labels):
    row, column = point
    peers = [other_column for other_row, other_column in all_labels if other_row == row]
    right = min((other for other in peers if other > column), default=view.limit[3] + 1)
    left = column if any(other < column for other in peers) else view.limit[1]
    label_right = view.label_right(point)
    body_rows = sorted({r for r, c in all_labels if r < row and left <= c < right})
    pinned = set(view.rule.get("header_rows") or [])
    candidates = {name: [p for p in view.header_refs(name)
                         if p[0] < row and label_right < p[1] < right and p[0] not in body_rows
                         and (not pinned or p[0] in pinned)] for name in view.aliases}
    header_rows = sorted({r for refs in candidates.values() for r, _ in refs})
    if not header_rows:
        return {name: [] for name in candidates}, []
    start = previous = header_rows[0]
    for header_row in header_rows[1:]:
        if bisect_right(body_rows, previous) < bisect_right(body_rows, header_row):
            start = header_row
        previous = header_row
    selected = {}
    for name, refs in candidates.items():
        refs = [p for p in refs if p[0] >= start]
        latest = max((p[0] for p in refs), default=-1)
        selected[name] = [p for p in refs if p[0] == latest]
    return selected, sorted({point for refs in selected.values() for point in refs})


def _resolve_columns(layout, view, refs, identifier=None, unknown_refs=None):
    result = {}
    for rule in view.periods:
        name = rule["name"]
        matches = refs.get(name, [])
        unknown = (unknown_refs or {}).get(name, [])
        if unknown:
            _problem(layout, "AMBIGUOUS_COLUMN", f"Period {name!r} has a header formula without a saved value. Table metadata identifies the affected period, but cannot verify its visible header.",
                     [*matches, *unknown], identifier=identifier, column=name)
        elif len(matches) == 1:
            result[name] = matches[0][1]
        elif len(matches) > 1:
            _problem(layout, "AMBIGUOUS_COLUMN", f"Period {name!r} has multiple headers in the same section.", matches,
                     identifier=identifier, column=name)
        elif rule.get("required", True):
            _problem(layout, "MISSING_COLUMN", f"Period {name!r} is missing from this section.",
                     identifier=identifier, column=name)
    return result


def _layout_mode(sheet, rule):
    layout, view = Layout(), _View(sheet, rule)
    configured = list(rule.get("kpis", []))
    if not configured:
        _problem(layout, "LAYOUT_UNRESOLVED", "No KPI labels were configured for this layout sheet.")
        return layout
    aliases, definitions = defaultdict(set), {}
    for item in configured:
        canonical = normalize(item["name"])
        definitions.setdefault(canonical, item["name"])
        for alias in [item["name"], *item.get("aliases", [])]:
            if normalize(alias):
                aliases[normalize(alias)].add(canonical)
    label_columns = {_column(value) for value in rule.get("label_columns", [])}
    locations = defaultdict(list)
    for point, value in sorted(view.text.items()):
        if not view.body(point) or label_columns and point[1] not in label_columns:
            continue
        candidates = aliases.get(value, set())
        if len(candidates) > 1:
            _problem(layout, "AMBIGUOUS_KPI", "One label matches aliases of multiple configured KPIs.", [point], identifier=sheet.cell(*point).value)
        elif candidates:
            locations[next(iter(candidates))].append(point)
    all_refs = sorted(point for refs in locations.values() for point in refs)
    # A matching page title above the period headings is not a body occurrence.
    for canonical, refs in locations.items():
        contextual = [point for point in refs if _headers_for_label(view, point, all_refs)[1]]
        if contextual:
            locations[canonical] = contextual
    all_refs = sorted(point for refs in locations.values() for point in refs)
    header_points, discovered_columns = set(), set()
    for canonical, display in definitions.items():
        refs = locations.get(canonical, [])
        definitions_for_name = [item for item in configured if normalize(item["name"]) == canonical]
        expected = {item.get("occurrence", index) for index, item in enumerate(definitions_for_name, 1)}
        required = {item.get("occurrence", index) for index, item in enumerate(definitions_for_name, 1)
                    if item.get("required", True)}
        for occurrence, point in enumerate(refs, 1):
            # Keep every observed occurrence. Hiding an unconfigured duplicate
            # would defeat the engine's sent/received count-mismatch safeguard.
            matches, found = _headers_for_label(view, point, all_refs)
            columns = _resolve_columns(layout, view, matches, display)
            header_points.update(found)
            discovered_columns.update(name for name, positions in matches.items() if positions)
            layout.rows.append(Row((canonical, occurrence), display, occurrence, *point, columns))
            if occurrence not in expected:
                _problem(layout, "EXTRA_KPI", "An additional occurrence of a configured KPI is present.", [point], identifier=display)
        for occurrence in sorted(value for value in required if value > len(refs)):
            _problem(layout, "MISSING_KPI", f"KPI {display!r}, occurrence {occurrence}, was not found.", identifier=display)
    # Unconfigured text, even beside a number, can be a margin note. Only exact
    # configured labels establish layout KPI rows; identifier tables can discover
    # arbitrary new identifiers because their table/header defines that scope.
    if not layout.rows:
        # Headers remain useful for inventory when every expected KPI is absent.
        for name in view.aliases:
            refs = view.header_refs(name)
            if refs:
                discovered_columns.add(name)
                header_points.update(refs)
    layout.rows.sort(key=lambda item: (item.row, item.label_column))
    layout.header_coordinates = [coordinate(*point) for point in sorted(header_points)]
    layout.columns = [item["name"] for item in view.periods if item["name"] in discovered_columns]
    return layout


def _identifier_mode(sheet, rule):
    layout, view = Layout(), _View(sheet, rule)
    expected = normalize(rule.get("identifier_header", "KPI"))
    pinned_column = _column(rule["identifier_column"]) if rule.get("identifier_column") is not None else None
    pinned_row = rule.get("header_row")
    matching_tables = []
    for table in sheet.tables:
        if rule.get("table_name") and normalize(rule["table_name"]) not in {normalize(table.get("name")), normalize(table.get("display_name"))}:
            continue
        top, left, bottom, right = bounds(table["ref"])
        if pinned_row is not None and top != pinned_row:
            continue
        identifiers = [left + index for index, column in enumerate(table.get("columns", []))
                       if normalize(column.get("name")) == expected]
        if pinned_column is not None:
            identifiers = [pinned_column] if left <= pinned_column <= right else []
        identifiers = [column for column in identifiers
                       if not any(_inside((top, column), rectangle) for rectangle in view.ignored)]
        if len(identifiers) == 1:
            matching_tables.append((table, top, identifiers[0], bottom, right))
        elif len(identifiers) > 1:
            _problem(layout, "AMBIGUOUS_LAYOUT", "The identifier table contains repeated identifier headers.")
            return layout
    if len(matching_tables) > 1:
        _problem(layout, "AMBIGUOUS_LAYOUT", "Multiple structured tables match the identifier layout; configure table_name.")
        return layout
    if rule.get("table_name") and not matching_tables:
        _problem(layout, "LAYOUT_UNRESOLVED", f"Configured identifier table {rule['table_name']!r} was not found unambiguously.")
        return layout
    table = None
    if matching_tables:
        table, header_row, identifier_column, bottom, right = matching_tables[0]
        data_start = header_row + table.get("header_row_count", 1)
        data_end = bottom - table.get("totals_row_count", 0)
        identifier_point = header_row, identifier_column
        identifier_header = view.cells.get(identifier_point)
        if identifier_header is not None and identifier_header.formula is not None and not identifier_header.cache_available:
            _problem(layout, "AMBIGUOUS_COLUMN", "The identifier header formula has no saved value. Table metadata locates the identifier column, but its visible header cannot be verified.",
                     [identifier_point], column=rule.get("identifier_header", "KPI"))
        elif view.text.get(identifier_point) != expected:
            _problem(layout, "MISSING_COLUMN", "The visible identifier header is missing or changed. Table metadata locates the identifier column, so its existing identifiers can still be compared.",
                     [identifier_point], column=rule.get("identifier_header", "KPI"))
    else:
        candidates = [point for point, value in view.text.items() if value == expected
                      and (pinned_column is None or point[1] == pinned_column)
                      and (pinned_row is None or point[0] == pinned_row)
                      and view.limit[1] <= point[1] <= view.limit[3] and point[0] <= view.limit[2]]
        if pinned_row is not None and pinned_column is not None:
            candidates = [(pinned_row, pinned_column)] if (pinned_row, pinned_column) in view.cells else []
        contextual = [point for point in candidates if any(
            r == point[0] and c > point[1] and text in period_aliases
            for (r, c), text in view.text.items() for period_aliases in view.aliases.values())]
        if contextual:
            candidates = contextual
        if len(candidates) != 1:
            _problem(layout, "AMBIGUOUS_LAYOUT" if candidates else "LAYOUT_UNRESOLVED",
                     "The identifier header could not be located uniquely; configure table_name/header_row/identifier_column.", candidates)
            return layout
        header_row, identifier_column = candidates[0]
        data_start, data_end, right = header_row + 1, view.limit[2], view.limit[3]
    # Table column names establish geometry, never replace deleted or changed
    # worksheet header cells. Sparse absence is a blank header too.
    header_text = {point: text for point, text in view.text.items() if point[0] == header_row}
    header_left = max(bounds(table["ref"])[1], view.limit[1]) if table else identifier_column + 1
    refs = {name: [point for point, value in header_text.items()
                   if value in aliases and header_left <= point[1] <= min(right, view.limit[3])
                   and point[1] != identifier_column
                   and not any(_inside(point, rectangle) for rectangle in view.ignored)]
            for name, aliases in view.aliases.items()}
    unknown_refs = defaultdict(list)
    if table:
        table_left = bounds(table["ref"])[1]
        for index, metadata in enumerate(table.get("columns", [])):
            point = header_row, table_left + index
            cell = view.cells.get(point)
            if (point[1] == identifier_column or not header_left <= point[1] <= min(right, view.limit[3])
                    or cell is None or cell.formula is None or cell.cache_available):
                continue
            for name, aliases in view.aliases.items():
                if normalize(metadata.get("name")) in aliases:
                    unknown_refs[name].append(point)
    columns = _resolve_columns(layout, view, refs, unknown_refs=unknown_refs)
    layout.columns = [item["name"] for item in view.periods if refs[item["name"]]]
    layout.header_coordinates = [coordinate(*point) for point in sorted({
        (header_row, identifier_column),
        *(point for positions in refs.values() for point in positions),
        *(point for positions in unknown_refs.values() for point in positions),
    })]
    data_start, data_end = max(data_start, view.limit[0]), min(data_end, view.limit[2])
    inspected_columns = {identifier_column, *columns.values()}
    body_rows = sorted({row for row, column in view.cells if data_start <= row <= data_end and column in inspected_columns})
    occurrences = Counter()
    for row in body_rows:
        point = row, identifier_column
        identifier = view.cells.get(point)
        if identifier is not None and identifier.formula is not None and not identifier.cache_available:
            _problem(layout, "AMBIGUOUS_LAYOUT", "An identifier formula has no saved value; this row cannot be aligned.", [point])
            continue
        normalized = normalize(identifier.value) if identifier is not None else ""
        if not normalized or identifier.kind in {"b", "e"}:
            if any(view.cells.get((row, col)) is not None and
                   (view.cells[row, col].value is not None or view.cells[row, col].formula is not None)
                   for col in columns.values()):
                _problem(layout, "MISSING_IDENTIFIER", "A populated table row has no usable KPI identifier.", [point])
            continue
        occurrences[normalized] += 1
        layout.rows.append(Row(normalized, str(identifier.value), occurrences[normalized], row, identifier_column, dict(columns)))
    for identifier, count in occurrences.items():
        if count < 2:
            continue
        duplicates = [row for row in layout.rows if row.key == identifier]
        for row in duplicates:
            row.ambiguous = True
        _problem(layout, "DUPLICATE_IDENTIFIER", "This KPI identifier appears more than once; none of its rows can be aligned safely.",
                 [(row.row, row.label_column) for row in duplicates], identifier=duplicates[0].identifier)
    return layout


def _resolve_merged_data(layout, view):
    """A merged value can represent one confirmed logical slot, never several."""
    slots = [(row, period, (row.row, column)) for row in layout.rows
             for period, column in row.columns.items()]
    labels = [(row.row, row.label_column) for row in layout.rows]
    for rectangle in view.merges:
        affected = [(row, period, point) for row, period, point in slots if _inside(point, rectangle)]
        if not affected:
            continue
        anchor = rectangle[:2]
        overlaps_label = any(_inside(point, rectangle) for point in labels)
        for row, period, point in affected:
            if len(affected) == 1 and row.row == anchor[0] and not overlaps_label:
                row.columns[period] = anchor[1]
            else:
                row.columns.pop(period, None)
                _problem(layout, "AMBIGUOUS_COLUMN",
                         "The merged value crosses multiple KPI/period positions or cannot be assigned to this KPI row's anchor. Its value is unknown for this comparison.",
                         list(dict.fromkeys([anchor, point])), identifier=row.identifier, column=period)
    return layout


def locate(sheet: Sheet, rule: dict) -> Layout:
    if not rule.get("enabled", True):
        return Layout()
    try:
        layout = _identifier_mode(sheet, rule) if rule.get("mode", "layout") == "identifiers" else _layout_mode(sheet, rule)
        return _resolve_merged_data(layout, _View(sheet, rule))
    except (ValueError, TypeError, KeyError) as exc:
        layout = Layout()
        _problem(layout, "LAYOUT_UNRESOLVED", f"Cannot apply layout configuration: {exc}")
        return layout
