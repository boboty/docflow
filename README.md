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

## Using DocFlow from an agent (normal usage)

An agent with local shell/filesystem access should install/use this as
**the `skills/docflow/` Skill**, not the Python source directly. The
Skill bundles its own runtime (`skills/docflow/runtime/`, a
[PEP 723](https://peps.python.org/pep-0723/) script executed via
`uv run` - no `pip install`, no global `docflow`, no knowledge of this
repo's location required) and a launcher at `skills/docflow/scripts/docflow`.
Follow [skills/docflow/SKILL.md](skills/docflow/SKILL.md) rather than
calling any Python API directly - it documents the input contract,
exit-code semantics, manifest handling, the `docflow catalog` commands
(see below), and (most importantly) the boundaries that keep an agent
from computing an authoritative money fact itself, inventing a
business-data source by scanning the filesystem, or treating a
template's leftover values from a previous transaction as real data.

Copying `skills/docflow/` anywhere (a different machine, a fresh
workspace) is sufficient - it has no dependency on this repo at all once
copied. See `scripts/build_skill_runtime.py` for how that bundle is kept
in sync with `src/docflow` (the actual source of truth; the Skill runtime
is a published artifact of it, never hand-edited separately).

## Reference Catalog

A small, YAML-backed store of long-lived facts (organizations and their
roles/contacts/addresses, products, registered template paths) that lets
an agent resolve a short name like "众壹" into full details instead of
asking the user to repeat them every time. It is not a database, not a
system of record, and never stores transaction facts (price, quantity,
dates, document numbers) - see `src/docflow/catalog/` and
`skills/docflow/SKILL.md`.

**Normal usage needs no configuration at all.** The Catalog root
resolves, in order:

```text
explicit --catalog-root  >  DOCFLOW_CATALOG_ROOT  >  $PWD/.docflow/catalog
```

An agent working in a workspace just runs `catalog init` once (idempotent
- safe to call whenever unsure whether it's already set up; never
overwrites existing data) and the rest follows from the current
directory - `DOCFLOW_CATALOG_ROOT` is an override for advanced/shared
setups, not something a normal user or agent needs to set:

```bash
docflow catalog init
docflow catalog validate
docflow catalog resolve --kind organization --query "众壹" --role ship_to --json
docflow catalog apply --input change.json
```

Real Catalog data is never committed; `skills/docflow/examples/catalog/*.example.yaml`
is a synthetic schema reference only.

## What this is not

- Not a general-purpose Office automation tool.
- Not part of BEL Core, and has no dependency on BEL today.
- Not a web app: **CLI is the only operator interface** (headless-first).
- Not Agent/LLM-dependent: all business rules (amounts, tax, rounding,
  validation) are plain deterministic code. LLM/Agent layers may call this
  engine in the future; the engine never calls them.

See `docs/` (task briefs) for the full phase-0 mandate and the explicit
YAGNI list (no web UI, no DB, no visual template designer, no approval
flow, no BEL adapter, etc.) — these are intentionally out of scope.

## Pricing model: gross pricing

Line-item facts are **gross pricing**: `gross_amount` (含税金额, what the
real contract/delivery-note pair actually settle on) is the authoritative
source fact per line, supplied by the caller - never recomputed as
`gross_unit_price * quantity`. Tax-exclusive figures are derived FROM it:

```text
net_amount     = round(gross_amount / (1 + tax_rate), 2)
tax_amount     = gross_amount - net_amount
net_unit_price = round(gross_unit_price / (1 + tax_rate), 2)
```

`gross_unit_price` is a second, independently supplied source fact (the
per-unit price printed on the real delivery note); it is expected to
roughly agree with `gross_amount / quantity`, but that agreement is a
*validation* concern (`domain.validation.validate_source_consistency`),
not a derivation shortcut. See `docs/phase-0-repair-task-brief.md` for why
(an earlier revision derived amounts forward from a tax-exclusive unit
price and did not match real business documents).

This principle also applies to **rendering**: the delivery note's amount
column is written as the literal `gross_amount` value, never a per-row
`=quantity*unit_price` formula. If a formula were used there, the
documented rounding tolerance in `validate_source_consistency` would let a
fact pack pass validation while the two generated *files* silently showed
different amounts for the same line - which happened in an earlier
revision (see `docs/phase-0-repair-2-acceptance-findings.md`).

## Real templates and real data

Real Excel templates and real business data (company names, addresses,
phone numbers, contract numbers) must **never** be committed to this
repository. Keep them outside the repo (e.g. iCloud/local storage) and
pass their paths to the CLI at runtime. Tests use synthetic fixtures
(`tests/fixtures/synthetic_templates.py`) that mirror the real templates'
structure (merged cells, item table position, subtotal formulas, 18-row
capacity) with fabricated sample data only.

A local, git-ignored golden acceptance test
(`tests/test_golden_acceptance.py`) checks a real 18-line sample against
locked totals. It is skipped by default; see that file's docstring to run
it against your own real templates and `local/golden_batch.local.json`
(also git-ignored - `/local/` is in `.gitignore`).

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
│   ├── definition.py      # TemplateDefinition: header/text/items cell mappings
│   ├── registry.py        # DocumentType -> TemplateDefinition
│   └── mappings/*.yaml    # hand-authored mapping config per real template
│                          # (`text`: body cells that are mostly-static clauses
│                          #  but embed a transaction fact inline, e.g. a
│                          #  delivery-deadline sentence - see the mapping
│                          #  YAML's own comments for why a cell like that is
│                          #  never left as "static template boilerplate")
├── renderers/
│   └── xlsx.py            # fills a copy of the real template; no business logic
├── adapters/
│   └── batch_input.py     # JSON batch -> DocumentFactPack (the only JSON-aware code)
├── application/
│   └── generation.py      # orchestration: validate -> derive -> render -> manifest
├── catalog/               # Reference Catalog - decoupled from the Engine above;
│   ├── models.py          # Organization/Contact/Address/Product/TemplateEntry
│   ├── loader.py          # YAML -> Catalog, structural/semantic validation
│   ├── resolve.py         # deterministic name/alias -> RESOLVED/NOT_FOUND/AMBIGUOUS
│   └── mutation.py        # explicit-confirmation-only, all-or-nothing apply
└── cli.py                 # `docflow generate ...` / `docflow catalog ...`
```

## Developer usage (this repo, not the bundled Skill)

This is for working on DocFlow itself - running it from source with an
editable install. An agent should not do this; see "Using DocFlow from an
agent" above for the normal, zero-install path.

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

Before the record loop runs, a **template preflight** checks the template
files and mapping are actually usable: file exists, is a valid xlsx, has
the mapped sheet, the mapping YAML itself is well-formed (row range and
cell addresses within Excel's actual grid limits, valid column letters),
every header placeholder and item column field name is one the renderer
actually understands, every format string is syntactically valid, and no
mapped cell falls inside a merged range without being that range's
writable top-left anchor - so a typo'd or structurally-wrong mapping fails
before the first record, not mid-batch after some records already
produced output. A preflight failure aborts the *whole* batch
immediately (exit code 2, nothing written) - it is never disguised as a
per-record FAILED entry, since no record could possibly succeed.

All numeric fields (amounts, quantities, tax rate, the optional
`gross_total`) are validated to be finite as soon as they're parsed from
JSON - `"NaN"`/`"Infinity"` parse as valid `Decimal` values but are
rejected as `NON_FINITE_DECIMAL` at the batch-input boundary, and
`domain.validation` independently guards against them too, so a bad value
can never propagate into a `decimal.InvalidOperation` crash that would
abort the rest of the batch.

## Testing

```bash
.venv/bin/python -m pytest
```

All tests run against synthetic templates generated on the fly - no
binary fixtures, no real data.
