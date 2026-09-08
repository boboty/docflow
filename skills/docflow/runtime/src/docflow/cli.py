"""CLI entry point. Headless-first: this is the only operator interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from docflow.adapters.batch_input import BatchFileError
from docflow.application.generation import generate_batch
from docflow.catalog.bootstrap import init_catalog
from docflow.catalog.loader import CatalogError, load_catalog
from docflow.catalog.mutation import (
    CatalogMutationError,
    ChangeFileError,
    apply_operations,
    import_seal,
    import_template,
    load_operations,
)
from docflow.catalog.resolve import resolve_organization, resolve_product, resolve_template
from docflow.catalog.root import resolve_catalog_root
from docflow.renderers.xlsx import TemplatePreflightError

_RESOLVE_EXIT_CODES = {"RESOLVED": 0, "NOT_FOUND": 1, "AMBIGUOUS": 1, "INVALID_CATALOG": 2}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Batch-generate contracts and delivery notes")
    generate.add_argument("--input", required=True, type=Path, help="Batch JSON file")
    generate.add_argument("--contract-template", required=True, type=Path, help="Real 采购合同 xlsx template")
    generate.add_argument("--delivery-template", required=True, type=Path, help="Real 送货单 xlsx template")
    generate.add_argument("--output", required=True, type=Path, help="Output directory")
    generate.add_argument("--catalog-root", type=Path, default=None, help="Catalog root for optional managed assets")

    catalog = subparsers.add_parser("catalog", help="Reference Catalog operations")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)

    init = catalog_sub.add_parser("init", help="Bootstrap a catalog (creates only missing files)")
    init.add_argument("--catalog-root", type=Path, default=None)

    validate = catalog_sub.add_parser("validate", help="Validate the catalog")
    validate.add_argument("--catalog-root", type=Path, default=None)

    resolve = catalog_sub.add_parser("resolve", help="Resolve a name/alias against the catalog")
    resolve.add_argument("--catalog-root", type=Path, default=None)
    resolve.add_argument("--kind", required=True, choices=["organization", "product", "template"])
    resolve.add_argument("--query", required=True)
    resolve.add_argument("--role", default=None, help="Filter organizations by role (e.g. supplier, ship_to)")
    resolve.add_argument("--contact", default=None, help="Explicit contact id/label within the resolved organization")
    resolve.add_argument("--address", default=None, help="Explicit address id/label within the resolved organization")
    resolve.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON")

    apply_ = catalog_sub.add_parser("apply", help="Apply explicit, user-confirmed catalog mutations")
    apply_.add_argument("--catalog-root", type=Path, default=None)
    apply_.add_argument("--input", required=True, type=Path, help="change.json: a JSON array of operations")

    import_template_p = catalog_sub.add_parser(
        "import-template", help="Register a template as a workspace-managed asset (the only way to register one)"
    )
    import_template_p.add_argument("--catalog-root", type=Path, default=None)
    import_template_p.add_argument("--key", required=True, help="e.g. procurement_contract, delivery_note")
    import_template_p.add_argument("--document-type", required=True, help="e.g. procurement.contract.v1")
    import_template_p.add_argument("--source", required=True, type=Path, help="External template xlsx to import")
    import_template_p.add_argument("--replace", action="store_true", help="Overwrite an existing entry for --key")

    import_seal_p = catalog_sub.add_parser("import-seal", help="Import a workspace-managed organization seal PNG")
    import_seal_p.add_argument("--catalog-root", type=Path, default=None)
    import_seal_p.add_argument("--organization", required=True, help="Existing organization id")
    import_seal_p.add_argument("--source", required=True, type=Path, help="External PNG seal to import")
    import_seal_p.add_argument("--replace", action="store_true", help="Overwrite the organization's existing seal")

    return parser


def _handle_generate(args: argparse.Namespace) -> int:
    try:
        summary = generate_batch(
            batch_file=args.input,
            contract_template_path=args.contract_template,
            delivery_template_path=args.delivery_template,
            output_dir=args.output,
            catalog_root=resolve_catalog_root(args.catalog_root),
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


def _handle_catalog(args: argparse.Namespace) -> int:
    # Single, shared root-resolution rule for every catalog subcommand:
    # explicit --catalog-root > DOCFLOW_CATALOG_ROOT > $PWD/.docflow/catalog.
    # This always returns a path - there is no "not configured" failure
    # mode any more; a fresh workspace just resolves to its own
    # not-yet-created default location.
    root = resolve_catalog_root(args.catalog_root)

    if args.catalog_command == "init":
        try:
            init_catalog(root)
        except CatalogError as exc:
            print(f"INVALID CATALOG [{exc.code}]: {exc}", file=sys.stderr)
            print("Existing catalog data was left untouched.", file=sys.stderr)
            return 2
        print(f"catalog at {root} is ready")
        return 0

    if args.catalog_command == "validate":
        try:
            load_catalog(root)
        except CatalogError as exc:
            print(f"INVALID CATALOG [{exc.code}]: {exc}", file=sys.stderr)
            return 2
        print(f"catalog at {root} is valid")
        return 0

    if args.catalog_command == "resolve":
        try:
            catalog = load_catalog(root)
        except CatalogError as exc:
            print(json.dumps({"status": "INVALID_CATALOG", "message": str(exc)}, ensure_ascii=False))
            return 2

        if args.kind == "organization":
            result = resolve_organization(
                catalog, args.query, role=args.role, contact_query=args.contact, address_query=args.address
            )
        elif args.kind == "product":
            result = resolve_product(catalog, args.query)
        else:
            result = resolve_template(catalog, args.query, catalog_root=root)

        print(json.dumps(result, ensure_ascii=False))
        return _RESOLVE_EXIT_CODES[result["status"]]

    if args.catalog_command == "apply":
        try:
            operations = load_operations(args.input)
            apply_operations(root, operations)
        except (ChangeFileError, CatalogMutationError, CatalogError) as exc:
            code = getattr(exc, "code", "CHANGE_FILE_ERROR")
            print(f"CATALOG APPLY REJECTED [{code}]: {exc}", file=sys.stderr)
            print("No changes were written.", file=sys.stderr)
            return 2
        print(f"catalog at {root} updated")
        return 0

    if args.catalog_command == "import-template":
        try:
            import_template(
                catalog_root=root,
                key=args.key,
                document_type=args.document_type,
                source=args.source,
                replace=args.replace,
            )
        except TemplatePreflightError as exc:
            print(f"TEMPLATE IMPORT REJECTED [{exc.code}]: {exc}", file=sys.stderr)
            print("No changes were written.", file=sys.stderr)
            return 2
        except (CatalogMutationError, CatalogError) as exc:
            code = getattr(exc, "code", "TEMPLATE_IMPORT_ERROR")
            print(f"TEMPLATE IMPORT REJECTED [{code}]: {exc}", file=sys.stderr)
            print("No changes were written.", file=sys.stderr)
            return 2
        print(f"template {args.key!r} imported into {root}")
        return 0

    if args.catalog_command == "import-seal":
        try:
            import_seal(root, args.organization, args.source, args.replace)
        except (CatalogMutationError, CatalogError) as exc:
            code = getattr(exc, "code", "SEAL_IMPORT_ERROR")
            print(f"SEAL IMPORT REJECTED [{code}]: {exc}", file=sys.stderr)
            print("No changes were written.", file=sys.stderr)
            return 2
        print(f"seal for {args.organization!r} imported into {root}")
        return 0

    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        return _handle_generate(args)
    if args.command == "catalog":
        return _handle_catalog(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
