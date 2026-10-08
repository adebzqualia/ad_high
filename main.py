"""Generate an offline POPS anomaly report without modifying workbooks."""
import argparse
from pathlib import Path
import sys
import webbrowser

from pops_audit.config import load_config
from pops_audit.engine import analyse
from pops_audit.report import write_report
from pops_audit.high_report import write_high_report


def main():
    parser = argparse.ArgumentParser(description="Compare sent and received POPS workbooks and create an offline HTML review.")
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "config" / "settings.yaml")
    parser.add_argument("--demo", action="store_true", help="Create a clearly marked synthetic report without reading your country files")
    open_options = parser.add_mutually_exclusive_group()
    open_options.add_argument("--open", action="store_true", help="Open the full report in your default browser")
    open_options.add_argument("--open-high-priority", action="store_true", help="Open the simplified high-priority report in your default browser")
    parser.add_argument("--validate-config", action="store_true", help="Check the configuration without reading workbooks")
    parser.add_argument("--output", type=Path, help="Use a different HTML output path for this run")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.validate_config:
            print(f"Configuration is valid: {sum(rule['enabled'] for rule in config['sheets'])} enabled sheets.")
            return 0
        output = config["output_report"].with_name("demo_report.html") if args.demo else config["output_report"]
        output = (args.output or output).expanduser().resolve()
        if output.suffix.casefold() not in {".html", ".htm"}:
            raise ValueError("The output filename must end in .html or .htm.")
        high_output = output.with_name(f"{output.stem}_high_priority{output.suffix}")
        if args.demo:
            from pops_audit.demo import demo_report
            payload = demo_report(config, progress=lambda message: print(message, flush=True))
        else:
            payload = analyse(config, progress=lambda message: print(message, flush=True))
        write_report(payload, output)
        write_high_report(payload, high_output)
    except Exception as exc:
        print(f"Cannot generate the report: {exc}", file=sys.stderr)
        return 2
    summary = payload["summary"]
    print(f"Report created: {output}")
    print(f"High-priority report created: {high_output}")
    print(f"Files sent: {summary['sent_files']} | Received: {summary['received_files']} | Matched pairs: {summary['matched_pairs']}")
    print(f"Findings to review: {summary['anomaly_count']}. Review the report before consolidation.")
    if args.open:
        webbrowser.open(output.as_uri())
    elif args.open_high_priority:
        webbrowser.open(high_output.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
