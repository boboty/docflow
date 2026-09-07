"""Local-only golden acceptance against the real 18-line contract/delivery
sample (Phase 0 Repair section 2).

This test is SKIPPED unless real template paths are provided via
environment variables - the real templates and real business data are
never committed to this repository. To run it:

    export DOCFLOW_GOLDEN_CONTRACT_TEMPLATE=/path/to/real/采购合同模板.xlsx
    export DOCFLOW_GOLDEN_DELIVERY_TEMPLATE=/path/to/real/送货单模板.xlsx
    .venv/bin/python -m pytest tests/test_golden_acceptance.py -v

The real per-line business data (SKUs, quantities, prices, buyer/seller
names, addresses) lives in local/golden_batch.local.json, which is
git-ignored (see .gitignore's `/local/` entry) and never committed.
Override its location with DOCFLOW_GOLDEN_BATCH if you keep it elsewhere.
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from docflow.adapters.batch_input import fact_pack_from_record, load_batch_records
from docflow.application.generation import generate_batch
from docflow.domain.document import DocumentType, build_projection

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BATCH = REPO_ROOT / "local" / "golden_batch.local.json"

_CONTRACT_TEMPLATE = os.environ.get("DOCFLOW_GOLDEN_CONTRACT_TEMPLATE")
_DELIVERY_TEMPLATE = os.environ.get("DOCFLOW_GOLDEN_DELIVERY_TEMPLATE")
_BATCH_FILE = Path(os.environ.get("DOCFLOW_GOLDEN_BATCH", DEFAULT_BATCH))

_READY = bool(
    _CONTRACT_TEMPLATE
    and _DELIVERY_TEMPLATE
    and Path(_CONTRACT_TEMPLATE).exists()
    and Path(_DELIVERY_TEMPLATE).exists()
    and _BATCH_FILE.exists()
)

pytestmark = pytest.mark.skipif(
    not _READY,
    reason=(
        "golden acceptance needs real templates + real batch data kept outside "
        "the repo; set DOCFLOW_GOLDEN_CONTRACT_TEMPLATE and "
        "DOCFLOW_GOLDEN_DELIVERY_TEMPLATE (and optionally DOCFLOW_GOLDEN_BATCH) "
        "to run it"
    ),
)

# Locked golden values (Phase 0 Repair section 2 / 9).
GOLDEN_NET_TOTAL = Decimal("3497.35")
GOLDEN_TAX_TOTAL = Decimal("454.65")
GOLDEN_GROSS_TOTAL = Decimal("3952.00")
GOLDEN_RMB_CAPITAL = "叁仟玖佰伍拾贰元整"

# The specific regression line: qty 42, gross unit price 49.
GOLDEN_SECOND_LINE = {
    "quantity": Decimal("42"),
    "gross_unit_price": Decimal("49.00"),
    "gross_amount": Decimal("2058.00"),
    "net_unit_price": Decimal("43.36"),
    "net_amount": Decimal("1821.24"),
    "tax_amount": Decimal("236.76"),
}


def test_real_18_line_sample_matches_golden_totals(tmp_path):
    output_dir = tmp_path / "output"

    summary = generate_batch(
        batch_file=_BATCH_FILE,
        contract_template_path=Path(_CONTRACT_TEMPLATE),
        delivery_template_path=Path(_DELIVERY_TEMPLATE),
        output_dir=output_dir,
    )

    failures = [(e.business_reference, e.document_type, e.issues) for e in summary.entries if e.validation_status != "PASS"]
    assert summary.failed_documents == 0, failures

    raw = load_batch_records(_BATCH_FILE)[0]
    fact_pack = fact_pack_from_record(raw)
    contract = build_projection(fact_pack, DocumentType.PROCUREMENT_CONTRACT_V1)
    delivery = build_projection(fact_pack, DocumentType.DELIVERY_NOTE_V1)

    assert contract.totals.net_total == GOLDEN_NET_TOTAL
    assert contract.totals.tax_total == GOLDEN_TAX_TOTAL
    assert contract.totals.gross_total == GOLDEN_GROSS_TOTAL
    assert delivery.totals.gross_total == GOLDEN_GROSS_TOTAL
    assert contract.amount_in_words == GOLDEN_RMB_CAPITAL

    second_line = contract.items[1]
    assert second_line.quantity == GOLDEN_SECOND_LINE["quantity"]
    assert second_line.gross_unit_price == GOLDEN_SECOND_LINE["gross_unit_price"]
    assert second_line.gross_amount == GOLDEN_SECOND_LINE["gross_amount"]
    assert second_line.net_unit_price == GOLDEN_SECOND_LINE["net_unit_price"]
    assert second_line.net_amount == GOLDEN_SECOND_LINE["net_amount"]
    assert second_line.tax_amount == GOLDEN_SECOND_LINE["tax_amount"]

    ref = fact_pack.business_reference
    contract_path = output_dir / ref / "procurement-contract.xlsx"
    delivery_path = output_dir / ref / "delivery-note.xlsx"
    assert contract_path.exists()
    assert delivery_path.exists()

    # File-level verification: read the ACTUAL generated cells back, not
    # just the in-memory projection the renderer was given. This is what
    # would have caught the P0 "delivery recomputes D*F" bug, where the
    # projection-level totals matched but the rendered file did not.
    contract_ws = openpyxl.load_workbook(contract_path)["采购合同"]
    delivery_ws = openpyxl.load_workbook(delivery_path)["送货单"]

    assert contract_ws["A28"].value == f"合并（RMB大写）：{GOLDEN_RMB_CAPITAL}"

    second_row = 10  # contract items start at row 9, so the 2nd line is row 10
    assert contract_ws[f"F{second_row}"].value == float(GOLDEN_SECOND_LINE["net_unit_price"])
    assert contract_ws[f"G{second_row}"].value == float(GOLDEN_SECOND_LINE["net_amount"])
    assert contract_ws[f"H{second_row}"].value == float(GOLDEN_SECOND_LINE["tax_amount"])
    assert contract_ws[f"I{second_row}"].value == float(GOLDEN_SECOND_LINE["gross_amount"])

    n = len(fact_pack.items)
    contract_gross_by_row = [contract_ws[f"I{9 + i}"].value for i in range(n)]
    delivery_gross_by_row = [delivery_ws[f"G{7 + i}"].value for i in range(n)]

    # Row-for-row file parity: the delivery note's amount column must equal
    # the contract's, for every line - not just in aggregate.
    assert contract_gross_by_row == delivery_gross_by_row

    file_gross_total = sum(Decimal(str(v)) for v in contract_gross_by_row)
    assert file_gross_total.quantize(Decimal("0.01")) == GOLDEN_GROSS_TOTAL

    file_net_total = sum(Decimal(str(contract_ws[f"G{9 + i}"].value)) for i in range(n))
    file_tax_total = sum(Decimal(str(contract_ws[f"H{9 + i}"].value)) for i in range(n))
    assert file_net_total.quantize(Decimal("0.01")) == GOLDEN_NET_TOTAL
    assert file_tax_total.quantize(Decimal("0.01")) == GOLDEN_TAX_TOTAL
