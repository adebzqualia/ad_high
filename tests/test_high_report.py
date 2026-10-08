"""Contract checks for the focused report and its command-line integration.

Run from the POPS_AD folder with ``python -m unittest discover -s tests``.
The fixtures are synthetic; these tests never read country workbooks.
"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import main as cli
from pops_audit.high_report import write_high_report


class PayloadParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.in_payload = False
        self.parts = []
        self.payload_count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "report-payload":
            self.in_payload = True
            self.payload_count += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False

    def handle_data(self, data):
        if self.in_payload:
            self.parts.append(data)


def extract_payload(document):
    parser = PayloadParser()
    parser.feed(document)
    if parser.payload_count != 1:
        raise AssertionError("Expected one embedded report payload")
    return json.loads("".join(parser.parts))


def fixture_payload():
    def anomaly(identifier, severity, country_id="fr", **changes):
        return {
            "id": identifier, "country_id": country_id,
            "country": "France" if country_id == "fr" else "Belgium",
            "workbook": "France.xlsx" if country_id == "fr" else "Belgium.xlsx",
            "sheet": "FTE", "category": "KPI_MISSING",
            "category_label": "Required KPI missing", "severity": severity,
            "title": "Required KPI missing", "message": "A configured KPI was removed.",
            "kpi": "FTE total", "column": "2025", "sent_cell": "B7",
            "received_cell": "", "before": {"value": 42, "formula": None,
            "kind": "n", "cache_available": True}, "after": None,
            "status": "unreviewed", **changes,
        }

    findings = [
        anomaly("high-id", "high"),
        anomaly("critical-id", "critical"),
        anomaly("medium-id", "medium", "be", message="MEDIUM_EVIDENCE_SECRET"),
        anomaly("low-id", "low", "be", message="LOW_EVIDENCE_SECRET"),
        anomaly("info-id", "info", "be", message="INFO_EVIDENCE_SECRET"),
        anomaly("baseline-id", "high", baseline=True, message="BASELINE_EVIDENCE_SECRET"),
    ]
    reviews = [{"anomaly_id": finding["id"], "status": "accepted",
                "notes": finding["id"] + " review note", "updated_at": "2026-10-09T10:00:00Z"}
               for finding in findings]
    return {
        "schema_version": 1, "report_id": "synthetic-run", "demo": True,
        "title": "Synthetic high-priority check", "generated_at": "2026-10-09T09:00:00Z",
        "settings": {"internal_setting": "UNRELATED_SETTING_SECRET"},
        "notices": ["UNRELATED_RUN_NOTICE_SECRET"],
        "summary": {"sent_files": 2, "received_files": 2, "matched_pairs": 2,
                    "anomaly_count": len(findings), "filling_before": {"expected": 500},
                    "template_issue_count": 1},
        "countries": [
            {"id": "fr", "name": "France", "file_key": "France.xlsx", "status": "matched",
             "sent_file": "France.xlsx", "received_file": "France.xlsx",
             "notes": ["UNRELATED_FR_NOTE_SECRET"],
             "sheets": [{"name": "FTE", "sent_name": "FTE", "received_name": "FTE",
                         "inventory_detail": "UNRELATED_SHEET_INVENTORY_SECRET"}],
             "filling_before": {"expected": 500}},
            {"id": "be", "name": "Belgium", "file_key": "Belgium.xlsx", "status": "matched",
             "notes": ["UNRELATED_BE_NOTE_SECRET"],
             "sheets": [{"name": "LOW_ONLY_SHEET_SECRET"}]},
        ],
        "anomalies": findings,
        "initial_reviews": {"schema_version": 1, "reviews": reviews},
    }


class HighReportContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pops-high-tests-")
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "nested" / "focused.html"

    def render(self, payload):
        result = write_high_report(payload, self.output)
        self.assertEqual(result, self.output.resolve())
        self.assertTrue(self.output.is_file())
        document = self.output.read_text(encoding="utf-8")
        return document, extract_payload(document)

    def test_only_high_and_critical_findings_and_matching_reviews_are_embedded(self):
        document, payload = self.render(fixture_payload())
        self.assertEqual({item["id"] for item in payload["anomalies"]}, {"high-id", "critical-id"})
        self.assertEqual({item["severity"] for item in payload["anomalies"]}, {"high", "critical"})
        self.assertFalse(any(item.get("baseline") for item in payload["anomalies"]))
        reviews = payload["initial_reviews"]
        if isinstance(reviews, dict):
            reviews = reviews["reviews"]
        self.assertEqual({item["anomaly_id"] for item in reviews}, {"high-id", "critical-id"})
        for excluded in ("MEDIUM_EVIDENCE_SECRET", "LOW_EVIDENCE_SECRET", "INFO_EVIDENCE_SECRET",
                         "BASELINE_EVIDENCE_SECRET", "medium-id review note", "baseline-id review note"):
            self.assertNotIn(excluded, document)

    def test_list_form_initial_reviews_is_supported(self):
        original = fixture_payload()
        original["initial_reviews"] = original["initial_reviews"]["reviews"]
        _, payload = self.render(original)
        reviews = payload["initial_reviews"]
        if isinstance(reviews, dict):
            reviews = reviews["reviews"]
        self.assertEqual({item["anomaly_id"] for item in reviews}, {"high-id", "critical-id"})

    def test_original_payload_and_finding_identifiers_are_preserved(self):
        original = fixture_payload()
        snapshot = deepcopy(original)
        _, focused = self.render(original)
        self.assertEqual(original, snapshot)
        original_by_id = {item["id"]: item for item in snapshot["anomalies"]}
        for item in focused["anomalies"]:
            self.assertEqual(item, original_by_id[item["id"]])

    def test_unrelated_country_metadata_and_inventory_are_not_embedded(self):
        document, payload = self.render(fixture_payload())
        self.assertEqual({item["id"] for item in payload.get("countries", [])}, {"fr"})
        for excluded in ("UNRELATED_SETTING_SECRET", "UNRELATED_RUN_NOTICE_SECRET",
                         "UNRELATED_FR_NOTE_SECRET", "UNRELATED_SHEET_INVENTORY_SECRET",
                         "UNRELATED_BE_NOTE_SECRET", "LOW_ONLY_SHEET_SECRET"):
            self.assertNotIn(excluded, document)
        self.assertNotIn("filling_before", payload)
        self.assertNotIn("filling_before", payload.get("summary", {}))
        self.assertTrue(all("sheets" not in country and "filling_before" not in country
                            for country in payload.get("countries", [])))

    def test_workbook_strings_cannot_terminate_embedded_json(self):
        original = fixture_payload()
        hostile = '</script><script id="injected-script">alert("unsafe")</script>&\u2028\u2029'
        original["anomalies"][0]["message"] = hostile
        original["title"] = '<img src=x onerror="alert(1)">'
        document, payload = self.render(original)
        self.assertEqual(payload["anomalies"][0]["message"], hostile)
        self.assertNotIn('<script id="injected-script">', document)
        self.assertNotIn('<img src=x onerror="alert(1)">', document)
        self.assertIn("\\u003c", document)

    def test_no_high_findings_produces_a_valid_empty_report(self):
        original = fixture_payload()
        original["anomalies"] = [item for item in original["anomalies"] if item["severity"] == "medium"]
        _, payload = self.render(original)
        self.assertEqual(payload["anomalies"], [])
        self.assertEqual(payload.get("countries", []), [])
        self.assertEqual(payload.get("initial_reviews", []), [])


class HighReportCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pops-high-cli-tests-")
        self.addCleanup(self.directory.cleanup)
        self.default_output = Path(self.directory.name) / "output" / "report.html"
        self.config = {"output_report": self.default_output,
                       "sheets": [{"enabled": True}, {"enabled": False}]}
        self.payload = fixture_payload()

    def run_cli(self, *arguments):
        with ExitStack() as stack:
            mocks = SimpleNamespace()
            mocks.config = stack.enter_context(patch.object(cli, "load_config", return_value=self.config))
            mocks.analyse = stack.enter_context(patch.object(cli, "analyse", return_value=self.payload))
            mocks.demo = stack.enter_context(patch("pops_audit.demo.demo_report", return_value=self.payload))
            mocks.full = stack.enter_context(patch.object(cli, "write_report"))
            mocks.focused = stack.enter_context(patch.object(cli, "write_high_report"))
            mocks.browser = stack.enter_context(patch.object(cli.webbrowser, "open"))
            stack.enter_context(patch.object(cli.sys, "argv", ["main.py", *map(str, arguments)]))
            mocks.stdout, mocks.stderr = io.StringIO(), io.StringIO()
            stack.enter_context(redirect_stdout(mocks.stdout))
            stack.enter_context(redirect_stderr(mocks.stderr))
            mocks.result = cli.main()
        return mocks

    def assert_reports(self, mocks, full_path):
        self.assertEqual(mocks.result, 0, mocks.stderr.getvalue())
        full_path = full_path.resolve()
        high_path = full_path.with_name(full_path.stem + "_high_priority" + full_path.suffix)
        mocks.full.assert_called_once_with(self.payload, full_path)
        mocks.focused.assert_called_once_with(self.payload, high_path)
        self.assertIs(mocks.full.call_args.args[0], mocks.focused.call_args.args[0])
        return high_path

    def test_default_run_generates_both_reports_from_one_analysis(self):
        mocks = self.run_cli()
        self.assert_reports(mocks, self.default_output)
        mocks.analyse.assert_called_once()
        mocks.demo.assert_not_called()
        mocks.browser.assert_not_called()

    def test_demo_run_generates_both_reports_without_country_analysis(self):
        mocks = self.run_cli("--demo")
        self.assert_reports(mocks, self.default_output.with_name("demo_report.html"))
        mocks.demo.assert_called_once()
        mocks.analyse.assert_not_called()

    def test_custom_htm_destination_also_controls_companion_path(self):
        destination = Path(self.directory.name) / "custom" / "country review.htm"
        mocks = self.run_cli("--output", destination)
        self.assert_reports(mocks, destination)

    def test_demo_custom_destination_overrides_demo_filename(self):
        destination = Path(self.directory.name) / "custom-demo.html"
        mocks = self.run_cli("--demo", "--output", destination)
        self.assert_reports(mocks, destination)
        mocks.analyse.assert_not_called()

    def test_invalid_extension_is_rejected_before_any_workbook_reads_or_writes(self):
        for extra_args in ((), ("--demo",)):
            with self.subTest(arguments=extra_args):
                mocks = self.run_cli(*extra_args, "--output", Path(self.directory.name) / "invalid.txt")
                self.assertEqual(mocks.result, 2)
                self.assertIn(".html or .htm", mocks.stderr.getvalue())
                for mock in (mocks.analyse, mocks.demo, mocks.full, mocks.focused, mocks.browser):
                    mock.assert_not_called()

    def test_validate_config_performs_no_analysis_or_report_generation(self):
        mocks = self.run_cli("--validate-config")
        self.assertEqual(mocks.result, 0)
        self.assertIn("1 enabled sheets", mocks.stdout.getvalue())
        for mock in (mocks.analyse, mocks.demo, mocks.full, mocks.focused, mocks.browser):
            mock.assert_not_called()

    def test_open_keeps_opening_the_full_report(self):
        mocks = self.run_cli("--open")
        self.assert_reports(mocks, self.default_output)
        mocks.browser.assert_called_once_with(self.default_output.resolve().as_uri())

    def test_open_high_priority_opens_the_companion(self):
        destination = Path(self.directory.name) / "review.HTM"
        mocks = self.run_cli("--output", destination, "--open-high-priority")
        high_path = self.assert_reports(mocks, destination)
        mocks.browser.assert_called_once_with(high_path.as_uri())

    def test_browser_options_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("--open", "--open-high-priority")
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
