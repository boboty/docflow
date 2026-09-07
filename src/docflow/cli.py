"""CLI entry point. Headless-first: this is the only operator interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docflow.adapters.batch_input import BatchFileError
from docflow.application.generation import generate_batch
from docflow.renderers.xlsx import TemplatePreflightError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Batch-generate contracts and delivery notes")
    generate.add_argument("--input", required=True, type=Path, help="Batch JSON file")
    generate.add_argument("--contract-template", required=True, type=Path, help="Real 采购合同 xlsx template")
    generate.add_argument("--delivery-template", required=True, type=Path, help="Real 送货单 xlsx template")
    generate.add_argument("--output", required=True, type=Path, help="Output directory")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        try:
            summary = generate_batch(
                batch_file=args.input,
                contract_template_path=args.contract_template,
                delivery_template_path=args.delivery_template,
                output_dir=args.output,
            )
        except TemplatePreflightError as exc:
            print(f"TEMPLATE PREFLIGHT FAILED [{exc.code}]: {exc}", file=sys.stderr)
            print("The whole batch was not run - fix the template/mapping and retry.", file=sys.stderr)
            return 2
        except BatchFileError as exc:
            print(f"BATCH FILE ERROR: {exc}", file=sys.stderr)
            return 2

        print(
            f"records={summary.total_records} "
            f"documents_passed={summary.passed_documents} "
            f"documents_failed={summary.failed_documents}"
        )
        for entry in summary.entries:
            if entry.validation_status != "PASS":
                print(f"FAILED {entry.business_reference} {entry.document_type}: {'; '.join(entry.issues)}")
        return 0 if summary.failed_documents == 0 else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
