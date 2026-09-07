---
name: docflow
description: Generate real 采购合同 (procurement contract) and 送货单 (delivery note) .xlsx documents from structured, gross-pricing business facts via the docflow CLI. Use when the user asks to generate a procurement contract, a delivery note, both together, or a batch of formal documents from procurement business data.
---

# DocFlow Skill

DocFlow turns structured business facts into real, formatted 采购合同 and
送货单 `.xlsx` files by calling the existing `docflow` CLI. This skill is a
thin operating procedure for that CLI - it does not reimplement, extend,
or second-guess any business rule. All money/tax/rounding logic lives in
the DocFlow engine; this skill never computes it itself.

```text
User → Agent → this Skill → docflow CLI → manifest.json → Agent's response
```

## When to use this skill

Use it when the user asks to:

- generate a procurement contract (采购合同);
- generate a delivery note (送货单);
- generate both from the same business facts;
- produce formal documents for a batch of procurement business.

...**and** the business facts available satisfy DocFlow's Phase 0 gross-pricing
input contract (see "Input contract" below). If they don't, say so - see
"What this skill must never do" and Scenario D.

## What DocFlow is not

Do not present DocFlow as, or reach for it as:

- a general-purpose Excel editor or document generator;
- a generic contract-drafting tool for arbitrary contract types;
- an OCR or document-extraction tool;
- a template-management or template-design system.

It does exactly one thing: project a `DocumentFactPack` you already have
into two specific, pre-existing real Excel templates.

## What this skill must never do

**This is the most important rule.** You may read, organize, map field
names, invoke the CLI, and explain results. You must never compute or
guess an authoritative business amount yourself.

Specifically:

- `gross_amount` (含税金额) and `gross_unit_price` (含税单价) are
  independent source facts. Never derive one from the other, and never
  compute `gross_amount = quantity * gross_unit_price` yourself and feed
  the result in as if it were a supplied fact - DocFlow already validates
  the two against each other with a documented tolerance; that is its job,
  not yours.
- Never derive `gross_amount` or `gross_unit_price` from a tax-exclusive
  `net_unit_price`. If the data you have is net-of-tax only, you are
  missing DocFlow's required facts - see Scenario D.
- Never reimplement tax math, rounding, RMB capitalization, or amount
  totals in your own reasoning to "double check" or "fill in" a number.
  If a number is missing, ask for it or say it's missing. Don't invent it.
- If the source data only gives you a tax-exclusive unit price and no
  gross/含税 figures, tell the user DocFlow Phase 0 needs the authoritative
  gross fact - do not silently convert or approximate one.

Why: DocFlow's entire value is that money math is centralized and
deterministic in one engine. An agent inventing or "helpfully" precomputing
a number defeats that, and worse, could pass validation while producing a
document with a silently wrong amount. When engine rules change in the
future (rounding policy, tolerance, capitalization), nothing in this file
should need to change, because none of those rules are duplicated here.

## Input contract

A batch file is a JSON array of records. Each record maps directly to one
`DocumentFactPack` (see `src/docflow/domain/facts.py` and the parsing in
`src/docflow/adapters/batch_input.py` for the authoritative definition -
this skill only summarizes it; if the two ever disagree, the code wins).

```json
{
  "business_reference": "BR-0001",
  "contract_no": "CT-0001",
  "delivery_no": "DN-0001",
  "contract_date": "2026-05-16",
  "delivery_date": "2026-06-09",
  "buyer": "示例采购方有限公司",
  "seller": "示例供应方有限公司",
  "seller_contact": "示例联系人",
  "seller_phone": "10000000000",
  "seller_address": "示例省示例市示例地址",
  "ship_to": {
    "company": "示例收货单位",
    "contact": "示例收货联系人",
    "phone": "20000000000",
    "address": "示例收货地址"
  },
  "currency": "CNY",
  "gross_total": "2058.00",
  "items": [
    {
      "sku": "SKU-001",
      "product_name": "示例产品",
      "specification": "型号SKU-001",
      "quantity": "42",
      "unit": "双",
      "gross_unit_price": "49",
      "gross_amount": "2058.00",
      "tax_rate": "0.13",
      "remarks": null
    }
  ]
}
```

Notes:

- `business_reference`, `contract_no`, `delivery_no`, `contract_date`,
  `delivery_date`, `buyer`, `seller`, `ship_to` (all 4 sub-fields), and a
  non-empty `items` array are required.
- Each item requires `sku`, `product_name`, `specification`, `quantity`
  (> 0), `unit`, `gross_unit_price` (>= 0), `gross_amount` (>= 0, the
  authoritative fact), and `tax_rate` (>= 0). `remarks` is optional.
- `currency` defaults to `"CNY"`. `seller_contact`/`seller_phone`/
  `seller_address` and the top-level `gross_total` are optional; supply
  `gross_total` only if you actually have an independent source total to
  cross-check against (DocFlow will validate Σitem.gross_amount against
  it) - do not compute one yourself just to fill the field.
- Numbers may be given as JSON numbers or numeric strings; DocFlow parses
  them as `Decimal`. Do not pre-round or reformat them.
- `NaN`/`Infinity` are rejected by DocFlow as invalid input - don't worry
  about filtering them yourself, just pass through what the source gave
  you and let DocFlow report it as a structured failure if it's bad.

See `examples/batch.example.json` for a complete, synthetic, runnable
batch file (never real company data).

## Building the batch file when input isn't already JSON

You may receive business facts as a table, CSV, or another tool's
structured output. Your job is **field mapping**, not **fact creation**:

- If the source clearly provides an authoritative gross/含税 figure per
  line (e.g. columns literally named 含税单价/含税金额/价税合计), map them
  to `gross_unit_price`/`gross_amount`.
- If the source is missing `gross_amount` (or `gross_unit_price`)
  entirely, do not compute it from quantity and a tax-exclusive price.
  Tell the user: "当前输入缺少权威含税金额（gross_amount），DocFlow
  Phase 0 不应静默推导该事实，请提供含税金额或含税单价。" Stop there for
  that record (or the whole request, if it affects all records) rather
  than guessing.

## Template paths

DocFlow does not have a config system for template paths (by design -
this skill uses the CLI's existing arguments, nothing more). Resolve the
two real template paths in this order:

1. If the user explicitly gives you paths, use them.
2. Otherwise, check the environment variables `DOCFLOW_CONTRACT_TEMPLATE`
   and `DOCFLOW_DELIVERY_TEMPLATE` (a convention for your run environment,
   not a DocFlow feature - just shell variables you read and pass through).
3. If neither is available, **stop and tell the user** you don't know
   where the real templates are. Do not guess a path, do not search the
   filesystem for something that looks like a template, and do not
   proceed without one.

Real templates and real business data must never be committed to this
repository, referenced from `tests/`/`examples/`/`skills/`, or otherwise
written into a git-tracked path.

## Workspace and temp files

When you need to write a batch JSON file (or receive output), use a
scratch/temp directory, not a path inside this repository:

```text
/tmp/docflow-<short-task-id>/
├── batch.json
└── output/
```

Or a business working directory the user explicitly names. Never write
batch JSON or generated output under `tests/`, `examples/`, or `skills/`
in this repo, and never default output into the repository itself.

## Invoking DocFlow

```bash
docflow generate \
  --input "$INPUT" \
  --contract-template "$DOCFLOW_CONTRACT_TEMPLATE" \
  --delivery-template "$DOCFLOW_DELIVERY_TEMPLATE" \
  --output "$OUTPUT"
```

If `docflow` isn't on `PATH` in your environment, fall back to
`python -m docflow.cli generate ...` using the same arguments (check
`command -v docflow` first rather than assuming either form works).

There is nothing else to configure. Don't wrap this in a shell script or
another Python file "for convenience" - a single CLI invocation per run is
already the stable, minimal interface.

## Handling the exit code

The CLI's exit code tells you which of three situations you're in. Get
this right before you say anything to the user.

| Exit | Meaning | What you do |
|---|---|---|
| `0` | Whole batch executed, every document PASSED | Read manifest, report full success, list output files |
| `1` | Whole batch executed, but at least one record/document FAILED | **Partial success** - read manifest, report PASS and FAILED separately, keep the successful files |
| `2` | Whole batch was **not executed** (template preflight or batch-file error) | No documents were attempted. Report the stderr error as a whole-batch configuration problem. Do not look for output. |

**Exit 1 is not "generation failed."** It means the batch ran and some
records didn't pass DocFlow's validation. Never tell the user "生成失败"
for exit 1 - the documents that passed are real, complete, correct files.

**Exit 2 means nothing ran.** Don't describe it as "some records failed" -
no record was even attempted. Report it as a configuration/environment
problem (missing/invalid template, invalid mapping, unreadable batch
file) using the message from stderr, and don't search for a manifest -
none was written.

## You must read manifest.json, not just the exit code

For exit `0` or `1`, always read `<output-dir>/manifest.json` - never rely
solely on the exit code or the `documents_passed=...`/`documents_failed=...`
line the CLI prints to stdout. The manifest is the structured source of
truth. Each entry has:

```text
business_reference, document_type, template_id, template_version,
output_file, validation_status ("PASS"/"FAILED"), issues (list of
"<CODE>: <message>" strings), source_snapshot_hash
```

`output_file` is relative to the output directory you passed - join them
to get the actual file path. A `FAILED` entry has `output_file: null`.

For exit `2`, there is no manifest (the batch never started) - use the
stderr message instead.

## Reporting results to the user

Keep it short. No Python tracebacks, no internal log lines. Report:
business reference, document type, the validation issue code, and a
one-line reason - nothing more from the internals.

**All PASS (exit 0):**

```text
已完成 12 笔业务单证生成：

采购合同：12
送货单：12
失败：0

输出目录：/tmp/docflow-xyz/output
```

**Partial success (exit 1):**

```text
已完成批量处理：

成功：10 笔（生成 20 份单证）
失败：2 笔

失败原因：
- BR-008：REQUIRED_FIELD_MISSING - buyer is required
- BR-010：GROSS_UNIT_PRICE_INCONSISTENT - items[0]: gross_unit_price*quantity=... but gross_amount=...
```

**Whole-batch failure (exit 2):**

```text
本次批量未执行（模板配置问题），没有生成任何文件。

错误：TEMPLATE_FILE_MISSING - template file not found: /path/to/template.xlsx
```

## Worked scenarios

**A - single business, both documents.** Build one-record batch JSON from
the user's data (gross-pricing facts, mapped not computed), resolve
template paths, run `docflow generate`, read manifest, confirm both
entries are PASS, report the two output file paths.

**B - batch with one bad record (good/bad/good).** Run once over the
3-record batch. Exit will be `1`. Read the manifest: 2 records x 2
documents = 4 PASS entries, 1 record x 2 documents = 2 FAILED entries.
Report 2/3 succeeded, list the failed record's issue codes, and give the
paths to the 4 successful files. Do not re-run per record and do not
treat exit 1 as total failure.

**C - template path wrong.** `docflow` exits `2`. Report that the batch
did not run due to a template configuration problem (missing or invalid
file - read the exact reason from stderr), and do not claim any business
record was processed.

**D - missing gross facts.** The source data has `quantity`,
`net_unit_price`, `tax_rate` but no `gross_unit_price`/`gross_amount`. Do
not compute gross figures from the net price. Tell the user DocFlow Phase
0 requires the authoritative gross fact and ask them to supply it (or
confirm you cannot proceed without it).

**E - the rounding-tolerance case.** Source gives
`quantity=42, gross_unit_price=49, gross_amount=2058, tax_rate=0.13`.
Pass these through verbatim - do not recompute or "sanity check" them
yourself. DocFlow's engine derives `net_unit_price=43.36`,
`net_amount=1821.24`, `tax_amount=236.76`. If your own mental math gives a
different number, trust the engine's output, not your arithmetic - that's
the entire point of this skill's boundary.
