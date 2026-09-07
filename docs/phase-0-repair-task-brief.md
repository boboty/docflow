# DocFlow — Phase 0 Repair

上一轮总体架构通过，但当前实现还不能验收。

本轮不要扩功能，不做 Skill，不接 BEL，不做 UI。

目标只有一个：

> 让真实采购合同 + 送货单样例生成结果在业务字段上与原单一致。

## 一、P0：修正金额事实口径

当前实现错误地把 `net_unit_price` 作为权威输入，再通过：

```text
net_amount = net_unit_price × quantity
tax_amount = net_amount × tax_rate
gross_amount = net_amount + tax_amount
```

向前计算。这与真实业务样例不一致。

真实样例中：

```text
数量：42
含税单价：49
价税合计：2058
税率：13%
```

合同展示：

```text
不含税单价：43.36
不含税金额：1821.24
税额：236.76
价税合计：2058
```

注意：`43.36 × 42 = 1821.12`，并不等于真实不含税金额 `1821.24`。原因是
`43.36` 是展示精度后的单价，不是行金额计算的权威来源。

当前 vertical slice 请冻结为 Gross Pricing 口径。`LineItemFacts` 至少调整为：

```text
sku
product_name
specification
quantity
unit
gross_unit_price
gross_amount
tax_rate
remarks
```

派生：

```text
net_amount = round(gross_amount / (1 + tax_rate), 2)
tax_amount = gross_amount - net_amount
net_unit_price = round(gross_unit_price / (1 + tax_rate), 2)
```

或者在能够证明等价的情况下采用其它实现，但必须满足真实样例。

`gross_amount` 应作为独立事实保留，不要只靠 `gross_unit_price × quantity`。
现阶段可以校验两者是否一致，但不要丢掉 `gross_amount`。

**明确原则**：source gross amount 是权威业务事实；display net unit price
是派生展示值。禁止再从展示后的 `net_unit_price` 反推权威金额。

## 二、增加真实样例 Golden Acceptance

本轮最重要的是增加一组 private/local golden acceptance。真实模板和真实
业务数据仍然不要提交到公开仓库。可以：

- 放在 repo 外；
- 或使用 `.local.*` / ignored fixture；
- 或单独提供一个本地 acceptance script。

必须验证真实 18 行样例生成结果。至少锁死以下值：

```text
net_total   = 3497.35
tax_total   = 454.65
gross_total = 3952.00
RMB大写     = 叁仟玖佰伍拾贰元整
```

并特别验证这一行：

```text
quantity         = 42
gross_unit_price = 49
gross_amount     = 2058
net_unit_price   = 43.36
net_amount       = 1821.24
tax_amount       = 236.76
```

最终生成的采购合同.xlsx / 送货单.xlsx 必须在业务字段上与原样例一致。不是
"差不多"，是金额逐项一致。

## 三、修正送货单未使用行的公式残留

当前 delivery note 模板 items rows = 7–24，G列金额 = Dn * Fn。renderer 当
前没有写 G 列，只保留模板原生公式。

问题：当实际明细少于 18 行时，剩余行（G10...G24）仍然保留公式，Excel 重
算后可能显示大量 `0`。

修复要求：不要引入通用 repeat-region framework，只增加最小模板能力，例如：

```yaml
formula_columns:
  gross_amount:
    column: G
    formula: "=D{row}*F{row}"
```

行为：used rows 写入/保留正确公式，unused rows 清空对应公式单元格。合同模
板如果未来需要同样能力，可以复用，但不要为了泛化提前设计复杂 DSL。

必须增加测试：delivery note with 3 items → rows 10–24 的 G 列为空，而使用
行例如 G7 = D7*F7 仍然正确。

## 四、调整 Validation，使其验证"事实 vs 派生"，而不是自己验证自己

当前 `projection totals vs sum(projection items)`，因为双方都来自同一个
计算链，验证价值很低。

本轮应优先增加这些验证：

**Source fact validation**：`gross_amount >= 0`、`gross_unit_price >= 0`、
`quantity > 0`、`tax_rate >= 0`。

**Source consistency**：如果 `gross_unit_price`、`gross_amount`、
`quantity` 同时存在，则校验 `round(gross_unit_price × quantity, 2) ≈
gross_amount`。如存在合理 rounding tolerance，必须明确记录 policy。

**Derived consistency**：`net_amount + tax_amount == gross_amount`。

**Aggregate consistency**：如果 FactPack 有 source total，则
`Σ gross_amount == source total`。如果当前输入还没有 source total，可考虑
增加一个可选 `gross_total`。不要为了这个再扩出复杂 totals model。

## 五、模板 preflight

当前批量处理语义应明确区分：

**模板级错误**（template file missing / xlsx invalid / sheet missing /
mapping invalid）：属于整批无法执行，应在进入 record loop 前做 template
preflight。遇到这种错误，整个 batch 立即失败，不要把它伪装成每一笔业务失
败。

**Record-level 错误**（缺字段 / 金额错误 / 数量错误 / 超过模板
capacity）：继续保持单笔 FAILED，其它记录继续。

## 六、Batch input 健壮性

检查所有输入解析路径，例如 `extra=dict(raw.get("extra", {}))`——如果类型
不合法，不应泄漏普通 Python 异常导致整批退出。

要求：record 输入结构错误统一转成结构化 `BatchRecordError`；不要简单
catch 全部 `Exception`；保留 programmer error / unexpected error 的可见
性。

## 七、不要修改的架构边界

以下现有设计保持：

```text
DocumentFactPack
→ deterministic derivation
→ DocumentProjection
→ Template Mapping
→ XLSX Renderer
→ Manifest
```

继续保持：无 BEL 依赖、无 Agent/LLM 依赖、无数据库、无 Web UI、无模板设计
器、无审批/签章、CLI-first、真实模板和真实数据不提交 repository。不要为了
本轮修复引入新的 framework。

## 八、测试要求

本轮完成后至少补齐：gross pricing derivation；真实问题回归（qty 42 /
gross unit price 49 / gross amount 2058 / tax 13% → net unit price 43.36
/ net amount 1821.24 / tax amount 236.76）；18 行真实样例 golden totals
（3497.35 / 454.65 / 3952.00）；RMB 大写（叁仟玖佰伍拾贰元整）；delivery
unused formula rows cleared；template preflight；malformed record 不终止
batch；单笔失败其它继续；manifest 仍正确；两份生成单据业务字段一致。

## 九、Definition of Done

用真实 18 行业务样例运行 DocFlow：一份业务事实 → 采购合同.xlsx + 送货
单.xlsx。结果必须满足：

```text
合同总额 = 3952
送货单总额 = 3952
合同不含税合计 = 3497.35
合同税额合计 = 454.65
RMB大写 = 叁仟玖佰伍拾贰元整
```

且第二个 SKU 对应行必须得到：`43.36 / 1821.24 / 236.76 / 2058`。

本轮不要实现 Agent Skill。只有本轮通过后，才进入 Skill 封装。
