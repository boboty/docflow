# DocFlow

> 将结构化业务事实按照确定性规则投影为正式企业单证。

Phase 0 / first vertical slice: given one batch of structured procurement
business facts, deterministically generate **采购合同 (procurement contract)**
and **送货单 (delivery note)** as `.xlsx` files, using the buyer's existing
real Excel templates.

```text
business data
  -> DocumentFactPack (canonical facts)
  -> deterministic derivation (money, tax, RMB capitalization)
  -> template mapping (cell coordinates, hand-authored per template)
  -> validation (structured, not exceptions)
  -> generated documents + manifest
```

## What this is not

- Not a general-purpose Office automation tool.
- Not part of BEL Core, and has no dependency on BEL today.
- Not a web app: **CLI is the only operator interface** (headless-first).
- Not Agent/LLM-dependent: all business rules (amounts, tax, rounding,
  validation) are plain deterministic code. LLM/Agent layers may call this
  engine in the future; the engine never calls them.

See `docs/` (task brief) for the full phase-1 mandate and the explicit
YAGNI list (no web UI, no DB, no visual template designer, no approval
flow, no BEL adapter, etc.) — these are intentionally out of scope.

## Real templates and real data

Real Excel templates and real business data (company names, addresses,
phone numbers, contract numbers) must **never** be committed to this
repository. Keep them outside the repo (e.g. iCloud/local storage) and
pass their paths to the CLI at runtime. Tests use synthetic fixtures
(`tests/fixtures/synthetic_templates.py`) that mirror the real templates'
structure (merged cells, item table position, subtotal formulas, 18-row
capacity) with fabricated sample data only.

## Project layout

```text
src/docflow/
├── domain/
│   ├── facts.py        # DocumentFactPack - the input contract
│   ├── document.py      # DocumentProjection - derived, template-ready values
│   └── validation.py     # structured ValidationResult / issues
├── rules/
│   ├── money.py          # Decimal money/tax derivation, rounding policy
│   └── chinese_amount.py # RMB capitalization (人民币大写)
├── templates/
│   ├── definition.py      # TemplateDefinition (cell coordinates only)
│   ├── registry.py        # DocumentType -> TemplateDefinition
│   └── mappings/*.yaml    # hand-authored mapping config per real template
├── renderers/
│   └── xlsx.py            # fills a copy of the real template; no business logic
├── adapters/
│   └── batch_input.py     # JSON batch -> DocumentFactPack (the only JSON-aware code)
├── application/
│   └── generation.py      # orchestration: validate -> derive -> render -> manifest
└── cli.py                 # `docflow generate ...`
```

## Usage

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/python -m docflow.cli generate \
  --input batch.json \
  --contract-template /path/to/real/采购合同模板.xlsx \
  --delivery-template /path/to/real/送货单模板.xlsx \
  --output ./output
```

Batch input is a JSON array; see `tests/conftest.py::sample_batch_dict` for
the expected shape of one record (`business_reference`, `contract_no`,
`delivery_no`, dates, `buyer`/`seller`, `ship_to`, `items[]`, etc.).

Output:

```text
output/
├── <business_reference>/
│   ├── procurement-contract.xlsx
│   └── delivery-note.xlsx
└── manifest.json
```

A record fails independently of the rest of the batch; `manifest.json`
records `PASS`/`FAILED` with structured issue codes per document
(`business_reference`, `document_type`, `template_id`, `template_version`,
`output_file`, `validation_status`, `issues`, `source_snapshot_hash`).

## Testing

```bash
.venv/bin/python -m pytest
```

All tests run against synthetic templates generated on the fly - no
binary fixtures, no real data.
