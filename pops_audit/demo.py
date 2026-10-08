"""Synthetic examples run through the actual reader, locator and comparison.

The temporary sample XLSX files are minimal test packages, not user workbooks.
No production files are read or changed by --demo.
"""
from copy import deepcopy
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from .reader import Book, Sheet, Cell, coordinate, position
from .engine import analyse

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
C = "http://schemas.openxmlformats.org/package/2006/content-types"


def _xml(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def write_fixture(book, path):
    """Write explicit typed values/caches for deterministic software fixtures."""
    parts = {}
    workbook = ET.Element(f"{{{S}}}workbook")
    tabs = ET.SubElement(workbook, f"{{{S}}}sheets")
    relations = ET.Element(f"{{{P}}}Relationships")
    types = ET.Element(f"{{{C}}}Types")
    ET.SubElement(types, f"{{{C}}}Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    ET.SubElement(types, f"{{{C}}}Default", Extension="xml", ContentType="application/xml")
    ET.SubElement(types, f"{{{C}}}Override", PartName="/xl/workbook.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
    root_rel = ET.Element(f"{{{P}}}Relationships")
    ET.SubElement(root_rel, f"{{{P}}}Relationship", Id="r1", Type=R + "/officeDocument", Target="xl/workbook.xml")
    table_count = 0
    for index, name in enumerate(book.sheetnames, 1):
        sheet = book.sheets[name]
        ET.SubElement(tabs, f"{{{S}}}sheet", name=name, sheetId=str(index), attrib={f"{{{R}}}id": f"r{index}"})
        ET.SubElement(relations, f"{{{P}}}Relationship", Id=f"r{index}", Type=R + "/worksheet", Target=f"worksheets/sheet{index}.xml")
        ET.SubElement(types, f"{{{C}}}Override", PartName=f"/xl/worksheets/sheet{index}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
        tree = ET.Element(f"{{{S}}}worksheet")
        data = ET.SubElement(tree, f"{{{S}}}sheetData")
        row_nodes = {}
        for (row, column), cell in sorted(sheet.cells.items()):
            if row not in row_nodes:
                row_nodes[row] = ET.SubElement(data, f"{{{S}}}row", r=str(row))
            attributes = {"r": coordinate(row, column)}
            if cell.kind in {"s", "e", "b", "d"}:
                attributes["t"] = "str" if cell.formula and cell.kind == "s" else "inlineStr" if cell.kind == "s" else cell.kind
            node = ET.SubElement(row_nodes[row], f"{{{S}}}c", attributes)
            if cell.formula:
                ET.SubElement(node, f"{{{S}}}f").text = cell.formula.removeprefix("=")
            if cell.cache_available and cell.value is not None:
                if attributes.get("t") == "inlineStr":
                    inline = ET.SubElement(node, f"{{{S}}}is")
                    ET.SubElement(inline, f"{{{S}}}t").text = str(cell.value)
                else:
                    ET.SubElement(node, f"{{{S}}}v").text = str(int(cell.value)) if cell.kind == "b" else str(cell.value)
            elif cell.formula and cell.cache_available and cell.kind == "s":
                ET.SubElement(node, f"{{{S}}}v")
        if sheet.merges:
            merges = ET.SubElement(tree, f"{{{S}}}mergeCells", count=str(len(sheet.merges)))
            for reference in sheet.merges:
                ET.SubElement(merges, f"{{{S}}}mergeCell", ref=reference)
        if sheet.tables:
            table_parts = ET.SubElement(tree, f"{{{S}}}tableParts", count=str(len(sheet.tables)))
            sheet_rels = ET.Element(f"{{{P}}}Relationships")
            for table in sheet.tables:
                table_count += 1
                ET.SubElement(table_parts, f"{{{S}}}tablePart", attrib={f"{{{R}}}id": f"table{table_count}"})
                ET.SubElement(sheet_rels, f"{{{P}}}Relationship", Id=f"table{table_count}", Type=R + "/table", Target=f"../tables/table{table_count}.xml")
                table_node = ET.Element(f"{{{S}}}table", id=str(table_count), name=table["name"], displayName=table["name"], ref=table["ref"], totalsRowShown="0")
                columns = ET.SubElement(table_node, f"{{{S}}}tableColumns", count=str(len(table["columns"])))
                for number, column in enumerate(table["columns"], 1):
                    ET.SubElement(columns, f"{{{S}}}tableColumn", id=str(number), name=column["name"])
                parts[f"xl/tables/table{table_count}.xml"] = _xml(table_node)
                ET.SubElement(types, f"{{{C}}}Override", PartName=f"/xl/tables/table{table_count}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml")
            parts[f"xl/worksheets/_rels/sheet{index}.xml.rels"] = _xml(sheet_rels)
        parts[f"xl/worksheets/sheet{index}.xml"] = _xml(tree)
    parts.update({"xl/workbook.xml": _xml(workbook), "xl/_rels/workbook.xml.rels": _xml(relations),
                  "_rels/.rels": _xml(root_rel), "[Content_Types].xml": _xml(types)})
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


def sample_book(config, factor=1):
    book = Book()
    for rule in config["sheets"]:
        if not rule["enabled"]:
            continue
        sheet = Sheet(rule["name"])
        sheet.cells[2, 2] = Cell("Operational planning", kind="s")
        sheet.merges.append("B2:J2")
        sheet.cells[1500, 40] = Cell("Explanatory notes outside the tables", kind="s")
        sheet.cells[1048576, 16384] = Cell()  # Decorative used-range inflation.
        if rule["mode"] == "identifiers":
            headers = ["KPI", "Description", "Actual 2024", "Actual 2025", "PLAN 2026"]
            for index, name in enumerate(headers, 5):
                sheet.cells[7, index] = Cell(name, kind="s")
            for index in range(18):
                row = index + 8
                sheet.cells[row, 5] = Cell(f"OPS_{index + 1:03}", kind="s")
                sheet.cells[row, 6] = Cell(f"Operating metric {index + 1}", kind="s")
                sheet.cells[row, 7] = Cell((index + 3) * 12 * factor)
                sheet.cells[row, 8] = Cell((index + 3) * 14 * factor)
            sheet.tables = [{"name": "InputKPIs", "ref": "E7:I25", "columns": [{"name": name} for name in headers]}]
        else:
            for name, column in [("2024", 6), ("2025", 7), ("PLAN 2026", 10)]:
                sheet.cells[4, column] = Cell(name, kind="s")
            for index, kpi in enumerate(rule["kpis"]):
                row = index + 7
                sheet.cells[row, 2] = Cell(kpi["name"], kind="s")
                for column, source_column, multiplier in [(6, "G", 12), (7, "H", 14), (10, "I", 0)]:
                    source_row = index % 18 + 8
                    sheet.cells[row, column] = Cell((index % 18 + 3) * multiplier * factor, f"=KPI!{source_column}{source_row}")
        book.sheets[sheet.name] = sheet
        book.sheetnames.append(sheet.name)
    return book


def demo_report(settings, *, progress=None):
    config = deepcopy(settings)
    if not any(rule["name"].casefold() == "kpi" for rule in config["sheets"]):
        config["sheets"].append({"name": "KPI", "mode": "identifiers", "identifier_header": "KPI", "aliases": [], "enabled": True,
                               "required": True, "columns": [{"name": name, "aliases": aliases, "required": True}
                                   for name, aliases in [("2024", ["Actual 2024"]), ("2025", ["Actual 2025"]), ("PLAN 2026", [])]],
                               "historical_columns": ["2024", "2025"]})
    periods = {"2024", "2025", "PLAN 2026"}
    for rule in config["sheets"]:
        if rule["name"].casefold() == "kpi":
            rule["name"], rule["enabled"] = "KPI", True
        rule["columns"] = [column for column in rule["columns"] if column["name"] in periods]
        rule["historical_columns"] = [name for name in rule.get("historical_columns", []) if name in periods]
    with tempfile.TemporaryDirectory(prefix="pops-review-demo-") as directory:
        root = Path(directory)
        config["sent_dir"], config["received_dir"] = root / "sent", root / "received"
        config["sent_dir"].mkdir()
        config["received_dir"].mkdir()
        for number, country in enumerate(("France", "Belgium", "Spain"), 1):
            before = sample_book(config, number)
            after = deepcopy(before)
            for index in range(18):
                if country != "Belgium" or index < 8:
                    after.sheets["KPI"].cells[index + 8, 9] = Cell((index + 3) * 16 * number)
            for sheet in after.sheets.values():
                if sheet.name == "KPI":
                    continue
                for (row, column), cell in list(sheet.cells.items()):
                    if column == 10 and cell.formula:
                        source_row = (row - 7) % 18 + 8
                        sheet.cells[row, column] = Cell(after.sheets["KPI"].cell(source_row, 9).value or 0, cell.formula)
            if country == "France":
                after.sheets["KPI"].cells[10, 7] = Cell(999)
                if "ID Card" in after.sheets:
                    after.sheets["ID Card"].cells[7, 6] = Cell(36)
                    after.sheets["ID Card"].cells[8, 7] = Cell(112, "=KPI!H9*2")
                if "OBS KPI" in after.sheets:
                    after.sheets["OBS KPI"].cells[7, 7] = Cell()
                after.sheets["KPI"].cells[11, 8] = Cell(84, "=42*2")
                for column in range(5, 10):
                    after.sheets["KPI"].cells.pop((15, column), None)
                after.sheets["KPI"].cells[26, 5] = Cell("OPS_NEW", kind="s")
                after.sheets["KPI"].cells[26, 9] = Cell(350)
                after.sheets["KPI"].tables[0]["ref"] = "E7:I26"
            if country == "Belgium":
                after.sheets["KPI"].cells[13, 9] = Cell("Pending", kind="s")
                after.sheets["KPI"].cells[14, 9] = Cell(0)
                if "CORE" in after.sheets:
                    after.sheets["CORE"].cells[9, 10] = Cell("#REF!", "=#REF!", kind="e")
                if "FTE" in after.sheets:
                    after.sheets["FTE"].cells.pop((4, 7), None)
                if "NPL SALES" in after.sheets:
                    after.sheets.pop("NPL SALES")
                    after.sheetnames.remove("NPL SALES")
                after.sheets["Country notes"] = Sheet("Country notes", {(1, 1): Cell("Please review", kind="s")})
                after.sheetnames.append("Country notes")
            # Deterministic caches for these simple synthetic direct references;
            # production code never evaluates or changes a workbook formula.
            for sheet in after.sheets.values():
                for point, cell in list(sheet.cells.items()):
                    match = re.fullmatch(r"=KPI!([A-Z]+[0-9]+)", cell.formula or "")
                    if match and cell.cache_available:
                        source = after.sheets["KPI"].cell(*position(match[1]))
                        sheet.cells[point] = Cell(source.value if source.value is not None else 0,
                                                 cell.formula, source.kind, source.cache_available)
            write_fixture(before, config["sent_dir"] / f"{country}.xlsx")
            write_fixture(after, config["received_dir"] / f"{country}.xlsx")
        write_fixture(sample_book(config), config["sent_dir"] / "Portugal.xlsx")
        write_fixture(sample_book(config), config["received_dir"] / "Italy.xlsx")
        payload = analyse(config, progress=progress)
    payload.update(demo=True, report_id="pops-anomaly-demo-v1", title="POPS return review · Example")
    payload["notices"].insert(0, "DEMONSTRATION — Synthetic country files generated for this example. No real country workbook was read.")
    return payload
