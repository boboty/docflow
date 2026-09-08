---
name: docflow
description: Generate real 采购合同 (procurement contract) and 送货单 (delivery note) .xlsx documents from structured, gross-pricing business facts via the docflow CLI, resolving stable supplier/ship-to/product/template facts from a Reference Catalog. Use when the user asks to generate a procurement contract, a delivery note, both together, or a batch of formal documents from procurement business data.
---

# DocFlow Skill

DocFlow turns structured business facts into real, formatted 采购合同 and
送货单 `.xlsx` files by calling the DocFlow CLI **bundled with this
Skill**, using a small Reference Catalog to fill in supplier/ship-to/
product/template facts that don't change transaction to transaction. This
skill is an operating procedure for those two things - it does not
reimplement, extend, or second-guess any business rule, and it does not
go looking for data (or for an install of DocFlow) on its own.

```text
User's current-task facts + Reference Catalog
        → Agent (this skill)
        → DocumentFactPack
        → bundled DocFlow runtime (this Skill's own scripts/docflow)
        → manifest.json
        → Agent's response
```

## The bundled runtime - always use it, never install anything

**Installing this Skill already installed DocFlow.** There is a complete,
self-contained, executable DocFlow runtime shipped inside the Skill's own
`runtime/` directory - it is not a separate thing you or the user need to
set up.

Every command in this document runs through this Skill's own launcher,
never a global `docflow`, never a bare `python -m docflow.cli`, never
`pip install`/`uv tool install`. Concretely:

```text
SKILL_ROOT  = the directory this SKILL.md file lives in
              (use your platform's standard way to reference a skill's own
              directory if it has one; otherwise it's simply the parent
              directory of this file)
DOCFLOW     = "$SKILL_ROOT/scripts/docflow"
```

Every example below assumes `DOCFLOW` is set that way; wherever you see
`$DOCFLOW`, substitute your platform's actual path to this Skill's
`scripts/docflow`. Do not:

- run `command -v docflow` or otherwise look for a global install;
- run `python -m docflow.cli` directly, or invoke any Python module path;
- ask the user to `pip install`, `uv tool install`, or clone a source repo;
- tell the user "DocFlow isn't installed" or ask them where its source
  code lives - it already shipped with this Skill.

The only thing `$DOCFLOW` itself needs at runtime is `uv`. `runtime/run.py`
is a [PEP 723](https://peps.python.org/pep-0723/) script - its own inline
metadata declares its dependencies (openpyxl, PyYAML), and `uv run`
resolves *only those* into an isolated, uv-managed environment. There is
no `pyproject.toml`, no setuptools build, and no install (editable or
otherwise) of a `docflow` package - `run.py` puts this runtime's own
bundled `src/` on `sys.path` and calls straight into it. If a command
fails with `DOCFLOW_RUNTIME_UNAVAILABLE`, that means either this Skill's
`runtime/` is missing/corrupted, or `uv` itself isn't installed on this
machine (not in `PATH`, not at `$HOME/.local/bin/uv`) - report that
specific, structured problem; do not fall back to a system Python or a
global `docflow`, and do not tell the user to install DocFlow (the
problem is `uv`, not DocFlow). Don't set `UV_NO_SYNC` or any other uv
environment-variable workaround to "fix" a launcher problem - PEP 723
script mode has no project-sync step for that variable to affect, and if
`$DOCFLOW` is actually failing, the fix is to report
`DOCFLOW_RUNTIME_UNAVAILABLE` accurately, not to paper over it with an
env var.

**The installed Skill is immutable during task execution.** Never write,
edit, move, or delete anything under this Skill's own directory
(`SKILL.md`, `scripts/`, `runtime/`, `examples/`) while carrying out a
task - not the runtime's source, not its lockfile, not this document.
The only place state changes as a result of using this skill is the
current workspace: `.docflow/catalog/`, the user's business input, and
`output/`. If something about the Skill itself seems wrong (missing
runtime, corrupted files), report it - don't try to patch, regenerate, or
"fix" the Skill's own files yourself.

## STOP CONDITIONS - read this before anything else

Two earlier runs of this skill went wrong. First: the user said "I have a
batch of procurement data, generate the documents" without providing the
data or a template path, and the agent found
`local/golden_batch.local.json` in the repository, treated it as this
task's business data, searched iCloud for a template, guessed one by
filename, and ran DocFlow. Second, in a later run where Catalog lookups
came back `NOT_FOUND`: the agent read a *previous transaction's* values
still sitting in the real template file (company name, contact, phone,
address, SKUs) and told the user "I noticed what might be a match in the
template, confirm if that's right?" - and separately, when reporting a
generated batch, the agent did its own arithmetic on the amounts
("42×49=2058, total 2744, consistent") before DocFlow had validated
anything. Every one of these was wrong. The five rules below exist
specifically to prevent this class of mistake, and they override
everything else in this document.

**Rule 1 - no data, no run.** If the user has not provided or explicitly
named this task's business data in the current conversation, do not run
DocFlow. It does not matter what else is sitting in the workspace -
`golden_batch.local.json`, `sample.json`, a `local/`, `tests/`,
`examples/`, or `output/` directory, a previous task's files. **A file
being accessible or discoverable does not make it an authorized source
for the current task.** Only data the user uploaded or explicitly pointed
to in *this* task counts. If it's missing, ask for it or tell the user
you need it - do not substitute anything you happen to find. (Resolving
or bootstrapping the *Catalog* itself - `docflow catalog init`/`resolve`
against `$PWD/.docflow/catalog` - is not "running DocFlow" and doesn't
touch business data; that's fine to do freely, per the next section.)

**Rule 2 - no filesystem discovery.** Never use `find`, `locate`, a
broad/recursive search, an iCloud or Documents scan, or "guess the
filename from the contract/delivery number" to locate business data or a
template. The one sanctioned, fixed location you don't need permission to
use is the current workspace's own Catalog at `$PWD/.docflow/catalog`
(see "The Catalog root" below) - that is a documented convention, not a
search. Everything else - the business data itself, and template paths
not already registered in the Catalog - comes only from an explicit
user-given path or value. If the user explicitly asks you to *find* a
file ("look for the contract template on my machine"), you may search -
but finding it does not make it authorized for use. Report what you found
and ask before treating it as this task's input.

**Rule 3 - Catalog `NOT_FOUND` means unknown, not "search harder".** If
`docflow catalog resolve` returns `NOT_FOUND`, that name is genuinely not
in the Catalog. Do not widen the search, check other directories, or
infer an answer from context. Tell the user it's not registered and ask
them to provide it (optionally offering to save it to the Catalog once
they confirm - see "Catalog persistence needs its own, separate authorization" below).

**Rule 4 - a template is a projection/layout source, never a Catalog or
business-data source.** A real template file defines document structure
and approved static boilerplate. Any value already sitting inside it -
company names, contacts, phone numbers, addresses, SKUs, product names,
dates, document numbers, amounts, old remarks - is **historical/sample
residue from whichever transaction last used that physical file**, full
stop, regardless of how well it happens to match something the user is
currently talking about. When the user hands you a template (to register
its path, or because you're using it to render), that is the full extent
of what they authorized. You must never:

  - use a value read from inside a template as this transaction's fact;
  - use it as this transaction's fact even when a Catalog lookup came
    back `NOT_FOUND` for the same name (Rule 3 already covers this, but
    it bears repeating here: `NOT_FOUND` is not license to go read the
    template instead);
  - present it to the user as a candidate ("I noticed what might be a
    match in the template, confirm if that's right?") - this is still
    using it, just with an extra step;
  - write it to the Catalog, with or without asking;
  - let it influence a `DocumentFactPack` in any way.

This holds even if the user's own short name happens to look like a
perfect match for something the template contains. The only way template
content becomes usable data is a separate, explicit instruction to treat
the template as a data source - e.g. "请从这份文件中提取基础资料" ("please
extract reference data from this file"). That is a distinct task from
generating documents, and it still ends with the normal
explicit-confirmation-before-`catalog apply` step (Rule 5 below and
"Catalog persistence needs its own, separate authorization").

**Rule 5 - do not perform or report arithmetic validation of
authoritative money facts.** You receive `quantity`, `gross_unit_price`,
`gross_amount`, `gross_total`, map them into the batch JSON, and hand them
to DocFlow. That is the entire extent of your involvement with the
numbers. Do not multiply, sum, or otherwise "sanity check" them yourself,
and do not report that you did - not "42×49=2058, total 2744, 自洽",
not any restatement of that reasoning in softer words. The correct thing
to say is that the figures were received and handed to DocFlow; only
after reading a manifest entry (or a validation error) may you say
DocFlow validated them - "DocFlow 校验通过" once `validation_status` is
actually `PASS`, or a specific issue code once it's `FAILED`. Performing
the arithmetic yourself and reporting "自洽"/"correct" before that is
exactly the kind of engine-duplicate-in-the-prompt this skill exists to
avoid (see "What this skill must never do") - it doesn't matter that the
arithmetic happens to be correct.

## When to use this skill

Use it when the user asks to:

- generate a procurement contract (采购合同);
- generate a delivery note (送货单);
- generate both from the same business facts;
- produce formal documents for a batch of procurement business.

...**and** the user has actually supplied this task's business data (Rule
1), and that data satisfies DocFlow's Phase 0 gross-pricing input contract
(see "Input contract" below and "What this skill must never do"). If
either condition fails, say so instead of proceeding.

## What DocFlow is not

Do not present DocFlow as, or reach for it as:

- a general-purpose Excel editor or document generator;
- a generic contract-drafting tool for arbitrary contract types;
- an OCR or document-extraction tool;
- a template-management or template-design system;
- a customer/supplier master-data system (that's the Reference Catalog's
  narrow job below, and even the Catalog is not an ERP or System of
  Record - it only holds long-lived, reusable facts).

It does exactly one thing: project a `DocumentFactPack` into two specific,
pre-existing real Excel templates.

## What this skill must never do

**This is the most important rule for the business data itself.** You may
read, organize, map field names, resolve names against the Catalog,
invoke the CLI, and explain results. You must never compute or guess an
authoritative business amount yourself.

Specifically:

- `gross_amount` (含税金额) and `gross_unit_price` (含税单价) are
  independent source facts. Never derive one from the other, and never
  compute `gross_amount = quantity * gross_unit_price` yourself and feed
  the result in as if it were a supplied fact - DocFlow already validates
  the two against each other with a documented tolerance; that is its job,
  not yours.
- Never derive `gross_amount` or `gross_unit_price` from a tax-exclusive
  `net_unit_price`. If the data you have is net-of-tax only, you are
  missing DocFlow's required facts - tell the user, don't convert.
- Never reimplement tax math, rounding, RMB capitalization, or amount
  totals in your own reasoning to "double check" or "fill in" a number.
  If a number is missing, ask for it or say it's missing. Don't invent it.
- The Reference Catalog never supplies a price, quantity, tax rate, or any
  other transaction fact (see "Catalog facts vs. current-task facts"
  below) - not even "the last order's price for this SKU". If it's not in
  the Catalog schema, it doesn't come from the Catalog, ever.

Why: DocFlow's entire value is that money math is centralized and
deterministic in one engine, and Catalog data is centralized as *stable*
facts only. An agent inventing a number, or promoting a historical price
into a current fact, defeats both of those and could pass validation
while producing a document with a silently wrong amount.

## Catalog facts vs. current-task facts

The Reference Catalog exists so you don't have to ask for a supplier's
full legal name, address, and contact every single time. It is not a
place to look for *this transaction's* numbers.

**Catalog may supply** (stable, reusable, looked up by name/alias):

```text
organization formal name, aliases, roles
organization contacts (name, phone) and addresses
product name, specification, unit, aliases
template file paths
```

**Catalog must never supply** (this transaction's facts - only from data
the user gave you in the current task):

```text
contract_no, delivery_no, contract_date, delivery_date
quantity, gross_unit_price, gross_amount, tax_rate, remarks
business_reference, gross_total
```

If the current task's data is missing one of these, that is a gap in
*this task's input*, not something to fill from the Catalog, from a past
order, or from any file under `local/`, `tests/`, `examples/`, `golden/`,
`acceptance/`, a previous `output/`, or any other historical source.

## The Catalog root, and why you don't need to configure it

Every `docflow catalog *` subcommand resolves its root the same way,
automatically:

```text
explicit --catalog-root  >  DOCFLOW_CATALOG_ROOT  >  $PWD/.docflow/catalog
```

For ordinary use you do nothing: the Catalog lives at
`<current workspace>/.docflow/catalog` - `$PWD` being the agent's current
working directory - and the CLI finds it there without any environment
variable or manual setup. `$PWD/.docflow/catalog` is a fixed, documented
convention, not filesystem search (Rule 2 is about *not* going hunting
for a Catalog in other locations - this default location is the one
sanctioned place to look, always relative to the current workspace, never
a parent directory or `$HOME`).

**First use in a workspace:** if `docflow catalog validate` or `resolve`
turns up nothing (an empty/not-yet-existing catalog), run
`docflow catalog init` before anything else:

```bash
"$DOCFLOW" catalog init            # creates $PWD/.docflow/catalog if missing
"$DOCFLOW" catalog validate        # confirm it's usable
"$DOCFLOW" catalog resolve ...     # now resolve as normal
```

`init` is idempotent and safe to run every time you're not sure a
workspace has been initialized yet: it only ever *creates a missing
file* (as an empty `{}` section) and never touches a file that already
exists - so it can never overwrite real Catalog data, even partially. If
an existing file is malformed, `init` reports `INVALID_CATALOG` and exits
`2` rather than rewriting it to force success; treat that exactly like
any other invalid-catalog error (a configuration problem, not something
to "fix" by regenerating the file yourself).

Advanced/explicit overrides (`--catalog-root`, `DOCFLOW_CATALOG_ROOT`)
still work exactly as before, e.g. if the user wants to point at a
Catalog shared across multiple workspaces.

**Workspace isolation.** A different `$PWD` means a completely different
Catalog - `/work/client-a/.docflow/catalog` and
`/work/client-b/.docflow/catalog` never see each other's data, and
neither is found by walking up from a subdirectory. If you `cd` between
tasks for different clients/workspaces, each one bootstraps and
accumulates its own Catalog independently; don't try to "share" one by
copying files around unless the user explicitly asks for that.

**Git.** If the current workspace happens to be a git repository,
`.docflow/catalog` can contain real business data once populated. Never
`git add` or commit it yourself, and don't modify the workspace's
`.gitignore` to "protect" it unless the user explicitly asks you to -
that's a decision for the user to make about their own repository, not
something this skill does on their behalf.

Real Catalog data (`organizations.yaml`, `products.yaml`,
`templates.yaml`) is never committed to *this* (DocFlow's own)
repository. `skills/docflow/examples/catalog/*.example.yaml` is a
synthetic reference for the schema only - it is not a real catalog and is
never used as one.

## Resolving names against the Catalog

Resolve every supplier/ship-to/freight-forwarder/product/template
reference through the CLI - never by grepping or hand-parsing the YAML
yourself. You don't need to pass `--catalog-root` for normal use - the
CLI already defaults to the current workspace's catalog as described
above:

```bash
# Organization (role optional; contact/address optional overrides)
"$DOCFLOW" catalog resolve --kind organization --query "临沂亦尔" --role supplier

"$DOCFLOW" catalog resolve --kind organization --query "众壹" --role ship_to --address "义乌仓"

# Product
"$DOCFLOW" catalog resolve --kind product --query "ST01黑"

# Template
"$DOCFLOW" catalog resolve --kind template --query procurement_contract
```

Each call prints one JSON object with a `status`:

| `status` | Meaning | What you do |
|---|---|---|
| `RESOLVED` | Exactly one match | Use the returned fields; don't ask the user to re-confirm what's already resolved |
| `NOT_FOUND` | No match at all | Tell the user this name isn't in the Catalog; ask them for the missing details (Rule 3 - don't search elsewhere) |
| `AMBIGUOUS` | Multiple candidates (e.g. two addresses, neither marked default) | Ask the user to pick, listing the `candidates` from the JSON - **ask only about the ambiguous field**, not everything about that organization |
| `INVALID_CATALOG` | The Catalog itself is malformed | Report this as a Catalog configuration problem, not a business-data problem |

Selection priority for a contact/address within a resolved organization
(already implemented by `resolve` - you don't need to reason about this
yourself, just read the result): explicit query > exact id/label match >
Catalog default > sole candidate > `AMBIGUOUS`.

Only ask the user about what's actually missing or ambiguous. If the
current task's data already contains everything DocFlow's input contract
needs (e.g. the user's file already spells out the full buyer/seller
names, dates, and amounts), you don't need to resolve anything at all -
Catalog lookups are a convenience for filling gaps, not a mandatory step.

## Template paths

Resolve the two real template paths in this order:

1. If the user explicitly gives you paths, use them.
2. Otherwise, resolve them from the Catalog:
   `docflow catalog resolve --kind template --query procurement_contract`
   and `... --query delivery_note`.
3. Otherwise, check `DOCFLOW_CONTRACT_TEMPLATE` /
   `DOCFLOW_DELIVERY_TEMPLATE` (kept for compatibility; prefer the Catalog
   going forward).
4. If none of the above resolve, **stop and tell the user** you don't
   know where the real templates are. Do not guess a path, do not search
   the filesystem for something that looks like a template (Rule 2), and
   do not proceed without one.

**First real generation in a fresh workspace** almost always hits step 4,
because `templates.yaml` starts out empty (`docflow catalog init` creates
it empty, it doesn't invent template locations). That's expected, not an
error state - ask once:

> 当前工作区还没有登记采购合同和送货单模板，请提供这两份模板；确认后可以
> 保存到当前工作区，以后无需重复提供。

If the user confirms saving, register both with `catalog apply` (see
"Catalog persistence needs its own, separate authorization"):

```bash
cat > change.json << 'EOF'
[
  {"operation": "set_template", "key": "procurement_contract",
   "document_type": "procurement.contract.v1", "path": "/abs/path/to/contract-template.xlsx"},
  {"operation": "set_template", "key": "delivery_note",
   "document_type": "delivery.note.v1", "path": "/abs/path/to/delivery-template.xlsx"}
]
EOF
"$DOCFLOW" catalog apply --input change.json
```

Next time, step 2 resolves both directly and you don't need to ask again.

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
  non-empty `items` array are required - these are current-task facts
  (see above), except `buyer`/`seller`/`ship_to`, whose *name/contact/
  address* details you may fill in from a Catalog `RESOLVED` result once
  you know which organization the user means.
- Each item requires `sku`, `product_name`, `specification`, `quantity`
  (> 0), `unit`, `gross_unit_price` (>= 0), `gross_amount` (>= 0, the
  authoritative fact), and `tax_rate` (>= 0). `remarks` is optional.
  `product_name`/`specification`/`unit` may come from a Catalog product
  resolve; `quantity`/`gross_unit_price`/`gross_amount`/`tax_rate` never do.
- `currency` defaults to `"CNY"`. `seller_contact`/`seller_phone`/
  `seller_address` and the top-level `gross_total` are optional; supply
  `gross_total` only if you actually have an independent source total to
  cross-check against - do not compute one yourself just to fill the field.
- Numbers may be given as JSON numbers or numeric strings; DocFlow parses
  them as `Decimal`. Do not pre-round or reformat them.

See `examples/batch.example.json` for a complete, synthetic, runnable
batch file (never real company data).

## Building the batch file when input isn't already JSON

You may receive business facts as a table, CSV, or another tool's
structured output - but only when the user has actually provided that
data for *this* task (Rule 1). Your job is **field mapping**, not **fact
creation**:

- If the source clearly provides an authoritative gross/含税 figure per
  line (e.g. columns literally named 含税单价/含税金额/价税合计), map them
  to `gross_unit_price`/`gross_amount`.
- If the source is missing `gross_amount` (or `gross_unit_price`)
  entirely, do not compute it from quantity and a tax-exclusive price.
  Tell the user: "当前输入缺少权威含税金额（gross_amount），DocFlow
  Phase 0 不应静默推导该事实，请提供含税金额或含税单价。" Stop there for
  that record (or the whole request, if it affects all records) rather
  than guessing.
- If the source names a supplier/ship-to/product by a short name, try
  resolving it against the Catalog before asking the user to spell out
  full details.

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
"$DOCFLOW" generate \
  --input "$INPUT" \
  --contract-template "$CONTRACT_TEMPLATE_PATH" \
  --delivery-template "$DELIVERY_TEMPLATE_PATH" \
  --output "$OUTPUT"
```

There is no fallback to a global `docflow`, a system Python, or any other
form - `$DOCFLOW` (this Skill's bundled launcher) is the only way this
skill invokes DocFlow, always. There is nothing else to configure. Don't
wrap this in a shell script or another Python file "for convenience" - a
single CLI invocation per run is already the stable, minimal interface.

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

`docflow catalog resolve` uses its own exit codes for scripting
convenience (`0`=RESOLVED, `1`=NOT_FOUND/AMBIGUOUS, `2`=INVALID_CATALOG),
but always read the JSON `status` field rather than relying on the exit
code alone when deciding how to respond. `docflow catalog init`,
`validate`, and `apply` use `0`=success, `2`=rejected/invalid.

**A fourth code, `127`, is not a DocFlow status at all.** It comes from
`$DOCFLOW` itself (the launcher), before DocFlow's own code ever ran,
meaning the bundled runtime or `uv` couldn't start
(`DOCFLOW_RUNTIME_UNAVAILABLE` on stderr). Treat that as an execution
-environment problem distinct from 0/1/2 - not a business-data failure,
and not something a different batch/input would fix.

## You must read manifest.json, not just the exit code

For exit `0` or `1` of `docflow generate`, always read
`<output-dir>/manifest.json` - never rely solely on the exit code or the
`documents_passed=...`/`documents_failed=...` line the CLI prints to
stdout. The manifest is the structured source of truth. Each entry has:

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

## Catalog persistence needs its own, separate authorization

The Catalog grows only through explicit user confirmation - never
silently, never automatically, and never inferred from an adjacent action
that merely *looks* like permission. In particular:

  - the user handing you a template file (to register its path, or to
    render against) is **not** authorization to save anything to the
    Catalog - not the template path, and certainly not any value read
    from inside it (see Rule 4 above);
  - the user supplying a company/contact/address/product for *this*
    transaction is **not** default permission to persist it permanently -
    "this time" and "from now on, save this" are two different
    instructions, and only the second one triggers `catalog apply`.

Only an explicit instruction like 保存 / 登记 / 以后默认用 / 记下来 / 加入
Catalog authorizes a write. Two shapes this takes:

1. **User volunteers a save.** "众壹新增一个宁波仓，地址 XXX，以后保存起来。"
   → build the operation and apply it now.
2. **You notice something reusable and ask.** After a successful run, if
   the user gave you an organization/address/contact detail that wasn't
   already in the Catalog: "这个地址目前不在众壹的基础资料里，要保存成
   '宁波仓'以后直接用吗？" → only apply if they say yes.

Never write to the Catalog because you inferred it would be convenient,
and never do it mid-task before the current documents are generated -
accumulation is a wrap-up step, not a precondition.

```bash
cat > change.json << 'EOF'
[
  {
    "operation": "upsert_address",
    "organization": "zhongyi",
    "address": {"id": "ningbo", "label": "宁波仓", "address": "浙江省宁波市……", "default": false}
  }
]
EOF
"$DOCFLOW" catalog apply --input change.json
```

Supported operations: `upsert_organization`, `upsert_contact`,
`upsert_address`, `upsert_product`, `set_template`. `apply` validates the
whole batch of operations before writing anything (atomic - a rejected
operation means *none* of them are written) and re-validates after
writing. If it exits `2`, nothing was saved; report the error and don't
retry silently with different data. There is no delete, merge, or
history/versioning operation - if the user wants something removed or
restructured, tell them that's outside this skill's scope (hand-edit the
Catalog files directly, which is a human/config action, not something
this skill automates).

## Worked scenarios

**A - single business, both documents, no Catalog needed.** The user's
current-task data already has full names/addresses. Build the batch JSON
directly, resolve template paths, run `docflow generate`, read manifest,
report the two output file paths.

**B - short names, Catalog fills the gaps.** User: "供应商临沂亦尔，发众壹
义乌仓" plus a data file with dates/amounts. Resolve `临沂亦尔` (role
`supplier`) and `众壹` (role `ship_to`, address `义乌仓`) via
`catalog resolve`; both come back `RESOLVED`. Do not ask for company full
names, addresses, contacts, or phone numbers - you already have them.
Build the batch, run, report.

**C - address ambiguity.** `众壹` has 义乌仓 and 广州仓, neither marked
default. `catalog resolve --kind organization --query 众壹` returns
`AMBIGUOUS` with `field: "address"`. Ask exactly one question: "众壹目前
有义乌仓和广州仓，这次发哪个？" Don't ask about anything else that already
resolved.

**D - no data provided (Rule 1), fresh workspace.** User: "我有一批采购
数据，帮我生成合同和送货单。" No file, no path - possibly not even a
Catalog yet (`docflow catalog init` may run here, which is fine, that's
just bootstrapping `$PWD/.docflow/catalog`, not touching business data).
Do not search `local/`, `golden/`, iCloud, or anywhere else. Respond:
"请提供或指定本次业务数据。" Do not run DocFlow.

**E - batch with one bad record (good/bad/good).** Run once over the
3-record batch. Exit will be `1`. Read the manifest: 2 records x 2
documents = 4 PASS entries, 1 record x 2 documents = 2 FAILED entries.
Report 2/3 succeeded, list the failed record's issue codes, and give the
paths to the 4 successful files. Do not re-run per record and do not
treat exit 1 as total failure.

**F - template path wrong.** `docflow generate` exits `2`. Report that the
batch did not run due to a template configuration problem (missing or
invalid file - read the exact reason from stderr), and do not claim any
business record was processed.

**G - missing gross facts.** The source data has `quantity`,
`net_unit_price`, `tax_rate` but no `gross_unit_price`/`gross_amount`. Do
not compute gross figures from the net price. Tell the user DocFlow Phase
0 requires the authoritative gross fact and ask them to supply it (or
confirm you cannot proceed without it).

**H - the rounding-tolerance case.** Source gives
`quantity=42, gross_unit_price=49, gross_amount=2058, tax_rate=0.13`.
Pass these through verbatim - do not recompute or "sanity check" them
yourself. DocFlow's engine derives `net_unit_price=43.36`,
`net_amount=1821.24`, `tax_amount=236.76`. If your own mental math gives a
different number, trust the engine's output, not your arithmetic - that's
the entire point of this skill's boundary.

**I - new address, save after confirmation.** User: "发众壹宁波仓，地址是
XXX" and 宁波仓 isn't in the Catalog. Use the user-supplied address for
*this* task's `ship_to` directly (Rule 1 - it's current-task data they
gave you). After the documents are generated, ask: "众壹的'宁波仓'还没在
基础资料里，要保存下来以后直接用吗？" Only call `catalog apply` if they
confirm. Next time, "众壹宁波仓" resolves directly.

**J - an obvious placeholder in the user's data, correctly left alone.**
The user's file has `ship_to.address: "浙江省金华市……【这里填真实地址】"`.
This is a template placeholder marker the user hasn't filled in, not a
real address. Do not treat it as real, do not silently invent a real
address, do not save it to the Catalog, and do not try to "look it up"
anywhere. Just ask the user for the actual address for this shipment.
Recognizing an obvious placeholder like this is an agent-level judgment
call (「【...】」, "TBD", "XXX", "待填写" and similar) - it does not need
(and this round deliberately does not add) any placeholder-detection
logic in the Engine or Catalog.

**K - a template with old data in it, and Catalog lookups come back
`NOT_FOUND`.** You open (or render against) a real template and it still
has a previous customer's company name, contact, phone, and SKUs sitting
in header/body cells - completely normal, since a real xlsx file remembers
whatever was last typed into it. Rule 4 applies in full even here: do not
read those values, do not mention them to the user as possible matches,
do not save them to the Catalog, and do not let a Catalog `NOT_FOUND`
change that. Simply tell the user the name isn't registered and ask them
to provide it, exactly as Rule 3 already says.

**L - reporting a passed batch without doing the arithmetic yourself.**
A batch generates successfully: two line items, `42×49=2058` and
`14×49=686`, `gross_total=2744`. Do not say "42×49=2058，686+2058=2744，
金额自洽" or anything equivalent - that's you validating money facts, which
Rule 5 reserves for the Engine. Read the manifest, confirm every entry's
`validation_status` is `PASS`, and report: "已收到含税单价、含税金额和总额，
DocFlow 校验通过，已生成 N 份文档" (or the "All PASS" template under
"Reporting results to the user"). The numbers being correct doesn't change
this - the point is that DocFlow said so, not that you re-derived it.
