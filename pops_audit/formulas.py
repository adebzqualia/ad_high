"""Conservative formula comparisons; this module never evaluates formulas.

Tokenisation: https://openpyxl.readthedocs.io/en/stable/formula.html
Whitespace used as Excel's intersection operator and quoted string contents
remain significant. References are remapped only through proven KPI alignment.
"""
import re
import unicodedata
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", str(value if value is not None else "")).split()).casefold()


_CELL = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)([1-9][0-9]*)$")


def _sheet_name(value):
    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1].replace("''", "'")
    # Excel ignores case in sheet references, but internal whitespace and
    # Unicode compatibility characters can distinguish two different sheets.
    return value.casefold()


def _position(coordinate):
    match = _CELL.fullmatch(coordinate)
    column = 0
    for letter in match.group(2).upper():
        column = column * 26 + ord(letter) - 64
    return column, int(match.group(4))


def _reference(value, current_sheet, references, ignore_case=True):
    raw = value.casefold() if ignore_case else value
    if "[" in value:  # Structured/external references must not become local A1.
        return ("range", raw)
    qualifier, separator, address = value.rpartition("!")
    sheet = _sheet_name(qualifier) if separator else str(current_sheet).casefold()
    address = address if separator else value
    endpoints = address.split(":")
    if len(endpoints) > 2 or not all(_CELL.fullmatch(item) for item in endpoints):
        return ("range", raw)
    parsed = []
    for endpoint in endpoints:
        match = _CELL.fullmatch(endpoint)
        absolute_column, letters, absolute_row, row = match.groups()
        coordinate = letters.upper() + row
        mapped_sheet, mapped_cell = references.get((sheet, coordinate), (sheet, coordinate))
        parsed.append((str(mapped_sheet).casefold(), mapped_cell.upper(), bool(absolute_column), bool(absolute_row)))
    if len(endpoints) == 2 and references:
        left, top = _position(endpoints[0])
        right, bottom = _position(endpoints[1])
        source_cells = [(coordinate, target) for (name, coordinate), target in references.items()
                        if name == sheet and left <= _position(coordinate)[0] <= right
                        and top <= _position(coordinate)[1] <= bottom]
        moved = [(coordinate, target) for coordinate, target in source_cells
                 if str(target[0]).casefold() != sheet or target[1].upper() != coordinate]
        if moved:
            new_left, new_top = _position(parsed[0][1])
            new_right, new_bottom = _position(parsed[1][1])
            offset = new_left - left, new_top - top
            complete = (len(source_cells) == (right - left + 1) * (bottom - top + 1)
                        and right - left == new_right - new_left and bottom - top == new_bottom - new_top
                        and parsed[0][0] == parsed[1][0])
            for coordinate, (target_sheet, target_coordinate) in source_cells:
                column, row = _position(coordinate)
                target_column, target_row = _position(target_coordinate)
                complete = complete and (str(target_sheet).casefold() == parsed[0][0]
                                         and (target_column - column, target_row - row) == offset)
            if not complete:
                # Matching endpoints alone cannot prove that a SUM/COUNT/etc.
                # still contains the same business cells after layout changes.
                return ("unconfirmed-range-move", raw)
    return ("reference", tuple(parsed))


def signature(formula, current_sheet, references=None, *, ignore_case=True):
    """Return None for unsupported syntax instead of claiming equivalence."""
    try:
        tokens = Tokenizer(formula).items
    except (TokenizerError, ValueError, IndexError, TypeError):
        return None
    result = []
    for index, token in enumerate(tokens):
        if token.type == "WHITE-SPACE":
            before = tokens[index - 1] if index else None
            after = tokens[index + 1] if index + 1 < len(tokens) else None
            # A range/closing expression followed by a range/opening expression
            # can be an intersection. Retaining these spaces is conservative.
            left = before and (before.subtype == "RANGE" or before.subtype == "CLOSE")
            right = after and (after.subtype == "RANGE" or after.subtype == "OPEN")
            if left and right:
                result.append(("intersection",))
            continue
        if token.type == "OPERAND" and token.subtype == "RANGE":
            result.append(_reference(token.value, current_sheet, references or {}, ignore_case))
        else:
            text = token.value
            if ignore_case and token.subtype != "TEXT":
                text = text.casefold()
            result.append((token.type, token.subtype, text))
    return tuple(result)


def same_formula(before, after, sent_sheet, received_sheet, references=None, *, ignore_case=True):
    first = signature(before, sent_sheet, references, ignore_case=ignore_case)
    second = signature(after, received_sheet, ignore_case=ignore_case)
    if first is None or second is None:
        return before == after
    return first == second


def _qualified_address(value):
    """Split an operand at a sheet separator outside quotes/table brackets."""
    quoted, depth, separator, index = False, 0, -1, 0
    while index < len(value):
        char = value[index]
        if char == "'" and not depth:
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            if char == "[":
                depth += 1
            elif char == "]":
                depth = max(0, depth - 1)
            elif char == "!" and not depth and value[max(0, index - 4):index].upper() != "#REF":
                separator = index
        index += 1
    return (value[:separator], value[separator + 1:]) if separator >= 0 else ("", value)


def external_link_indices(formula):
    """Return workbook-link indices used by references, never string literals.

    XLSX formulas identify external workbooks by their one-based position in
    workbook.xml/externalReferences, not the order of package relationships.
    Structured table references and explicit workbook filenames are excluded.
    """
    if not formula:
        return set()
    try:
        tokens = Tokenizer(formula).items
    except (TokenizerError, ValueError, IndexError, TypeError):
        return set()
    result = set()
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        qualifier, address = _qualified_address(token.value)
        if not qualifier:
            continue  # [1] by itself can be a local table column named '1'.
        external = _sheet_name(qualifier)
        match = re.match(r"^\[([1-9][0-9]*)\]", external)
        if match:
            result.add(int(match.group(1)))
    return result


def _broken_range(value):
    # Bracketed text names table columns, so even a column literally named
    # '#REF!' is not a broken cell reference. Quoted sheets and strings are
    # excluded even when newer formula syntax defeats the tokenizer.
    depth, quote, outside, index = 0, None, [], 0
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in {"'", '"'} and not depth:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif not depth:
            outside.append(char)
        index += 1
    return "#REF!" in "".join(outside).upper()


def has_broken_reference(formula):
    if not formula:
        return False
    try:
        return any(token.subtype == "ERROR" and token.value.upper() == "#REF!"
                   or token.subtype == "RANGE" and _broken_range(token.value)
                   for token in Tokenizer(formula).items)
    except (TokenizerError, ValueError, IndexError, TypeError):
        return _broken_range(formula)
