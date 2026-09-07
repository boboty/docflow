# DocFlow — Phase 0 Repair 2 (Acceptance Findings)

验收对象：HEAD `94d5711` + working tree（Phase 0 Repair 的 16 个已修改文件
及 3 个未跟踪文件）。仓库只有一个提交。未修改项目代码、测试或文档，验收
输出位于仓库外临时目录。

## Findings

### P0 BLOCKER：送货单未遵循权威 gross_amount，可能错误标记 PASS

- **事实**：源数据允许含税单价与行金额存在舍入容差，但送货单用数量乘单
  价重新计算金额。
- **证据**：`delivery.note.v1.yaml:42`。实际输入
  `quantity=42, gross_unit_price=49, gross_amount=2058.10`，生成结果两份
  均 PASS；合同 `I9=2058.10`，送货单 `G7 = D7*F7`，结果为 `2058.00`。
- **影响**：合法通过校验的事实可生成金额不一致的两份单证。当前跨单证校
  验比较内存 projection，未发现实际文件偏差。
- **建议**：送货单金额必须保留权威源金额；增加包含舍入差额的文件级核
  对，确保两份单证与源总额一致。

**修复**：`delivery.note.v1.yaml` 的 `items.columns` 直接映射
`gross_amount: G`（字面值，来自 `LineItemAmounts.gross_amount`），删除
`formula_columns` 机制（原第二轮为"避免公式残留"而引入，但与"gross_amount
权威且允许舍入容差"的原则冲突）。回归测试
`tests/test_generation_batch.py::test_contract_and_delivery_files_agree_on_amount_within_source_tolerance`
和
`tests/test_render_delivery.py::test_gross_amount_is_written_verbatim_even_when_it_diverges_from_unit_price_times_quantity`
复现了报告中的确切输入，并用真实模板人工复核：合同 `I9` 与送货单 `G7`
均为 `2058.1`。

### P0 BLOCKER：非有限 Decimal 会中断整批

- **事实**：`"NaN"`、`"Infinity"` 可通过 Decimal 解析，随后触发未处理异
  常。
- **证据**：`batch_input.py:68`、`validation.py:88`。
- **影响**：普通非法金额破坏 record-level isolation，留下部分输出。

**修复**：`adapters/batch_input.py` 新增 `_parse_decimal()`，在
`Decimal(str(value))` 解析成功后额外检查 `.is_finite()`，非有限值转为
`BatchRecordError("NON_FINITE_DECIMAL", ...)`（对 `_decimal` 与
`_optional_decimal` 均生效，覆盖全部金额/数量/税率/`gross_total`
字段）。`domain/validation.py` 同步加固：`validate_fact_pack` 在做
`< 0` 比较前先检查每个数值事实的 `.is_finite()`（NaN 的排序比较、
Infinity 的 `quantize` 都会抛 `decimal.InvalidOperation`，已用脚本验证），
非有限则报 `NON_FINITE_VALUE` 并跳过后续比较；`validate_source_consistency`
/ `validate_aggregate_consistency` 同样在使用前判空/判有限，双重防护即
使有人绕过 JSON adapter 直接构造 FactPack 也不会崩溃。回归测试覆盖
`good → NaN/Infinity/-Infinity → good` 三种输入，均验证前后 good 记录正
常生成、坏记录结构化 FAILED、整批不中断。

### P0 BLOCKER：无效 mapping 未在 record loop 前完整拦截

- **事实**：preflight 检查文件与 sheet，但没有完整检查 mapping 可用性。
- **证据**：`definition.py:56`、`xlsx.py:45`。占位符 `{unknown_fact}`
  preflight 通过、合同已生成、随后 `KeyError`；无效 YAML / 错误结构 /
  非法行号分别泄漏 `ParserError`、`TypeError`、`ValueError`。

**修复**：
1. `templates/definition.py` 的 `load_template_definition()` 全面重写：
   YAML 解析异常、非 mapping 顶层结构、缺字段、非法行号
   （`start_row`/`end_row` 非整数或 `end_row < start_row`）、非法列字母
   （必须匹配 `^[A-Z]+$`）、非法表头单元格地址
   （必须匹配 `^[A-Z]+[1-9][0-9]*$`），全部统一转换为
   `TemplateDefinitionError`，不再泄漏底层异常类型。
2. `renderers/xlsx.py` 的 `preflight()` 新增两项语义校验：
   - 用已知合法占位符集合（`_HEADER_CONTEXT_KEYS`，与实际渲染时
     `_header_context()` 用的字段完全一致）对每条 header 模板字符串跑一
     次 `str.format(**dummy_context)`，`KeyError`/`IndexError` 转换为
     `TemplatePreflightError("TEMPLATE_MAPPING_INVALID", ...)`；
   - 校验 `items.columns` 里的字段名都在已知合法字段集合
     （`_VALID_ITEM_FIELDS`）内，否则同样报
     `TEMPLATE_MAPPING_INVALID`。
3. `application/generation.py` 的 `_preflight_templates()` 在
   record loop 之前对两个模板分别跑 `registry.get()` +
   `preflight()`，任一环节失败均在写任何 manifest/文件之前抛出
   `TemplatePreflightError`。

回归测试复现了报告中的确切场景（`{unknown_fact}` 占位符、非法行号、无效
YAML、非 mapping 结构），并额外验证：用真实模板 + 复现用的坏 mapping 跑
`generate_batch`，确认整批在写任何文件之前失败
（`tests/test_preflight.py::test_generate_batch_does_not_render_anything_when_mapping_is_broken`，
且用真实模板人工复核过一遍相同场景）。

### P1 SHOULD FIX：Golden 测试没有验收实际 Excel 内容

- **事实**：Golden 测试核对的是重新构建的 projection，对生成文件只检查
  存在。
- **证据**：`test_golden_acceptance.py:71`。

**修复**：`tests/test_golden_acceptance.py` 新增文件级核对：用 openpyxl
重新打开生成的合同与送货单文件，逐行核对合同 `I` 列与送货单 `G` 列的实
际单元格值完全一致（18 行逐一比较，不只是聚合总额），核对 A28 的 RMB 大
写文本、第二行 F/G/H/I 四个具体数值，并从文件里独立求和验证
`net_total`/`tax_total`/`gross_total` 三个锁死值。

## 结论

三个 P0 blocker 均已修复并用真实模板复现验证（不仅是 synthetic
fixture）；P1 已按建议固化为文件级 golden 验收。详见对话中的最终报告。

## 复验轮：mapping preflight 剩余缺口（已修复）

复验发现 mapping preflight 仍有三类可写性/合法性检查缺失：

1. **非左上角合并单元格**：header 或 item 坐标落在合并区域内但不是锚点
   （如 `B3` 落在 `A3:E3` 合并区），openpyxl 写入时抛
   `AttributeError: 'MergedCell' object ... is read-only`。
2. **超出 Excel 网格边界**：行号超过 1,048,576（如 `A1048577`），
   `ws[cell] = value` 抛 `ValueError`。
3. **格式字符串本身语法错误**：如 `{buyer`（缺右花括号），`str.format()`
   抛 `ValueError`，未被 preflight 原有的 `except (KeyError, IndexError)`
   捕获。

**修复**：

- `templates/definition.py` 新增 `MAX_EXCEL_ROW`(1,048,576) /
  `MAX_EXCEL_COLUMN`(16,384，即 `XFD`) 常量，在 `_parse_header()` 和
  `_parse_items()` 里用 `openpyxl.utils.cell.coordinate_from_string` /
  `column_index_from_string` 解析后做边界检查，超界直接
  `TemplateDefinitionError`（在 mapping 加载阶段就失败，甚至早于
  per-file preflight）。
- `renderers/xlsx.py` 的 `preflight()`：
  - 不再用 `read_only=True` 打开模板（只读模式不暴露
    `ws.merged_cells.ranges`），改为正常模式打开（仍在同一个宽泛
    `except Exception` 里，文件损坏检测不受影响）；
  - 新增 `_is_non_writable_merged_cell()`，对每个 header 坐标和
    `items.start_row..end_row` × 每个映射列的每个坐标，检查是否落在合并
    区域且不是锚点，命中则 `TemplatePreflightError`；
  - 格式字符串校验的 `except` 子句增加 `ValueError`。

用报告里的确切三个场景（`B3`、`A1048577`、`{buyer`）对真实模板独立复现
验证：三者均在 `generate_batch()` 写任何文件之前以
`TemplatePreflightError`/`TemplateDefinitionError` 结构化失败，
`output_dir` 均未创建。回归测试：
`tests/test_preflight.py::test_preflight_rejects_header_cell_inside_non_anchor_merged_range`、
`test_preflight_rejects_malformed_format_string`、
`test_load_template_definition_rejects_row_beyond_excel_limit`、
`test_load_template_definition_rejects_end_row_beyond_excel_limit`。

全部测试（含真实模板 golden acceptance）：**56 passed**。
