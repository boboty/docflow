# DocFlow — Phase 0 / First Vertical Slice

## 项目目标

创建一个独立项目 `docflow`。

DocFlow 的长期定位是：

> 将结构化业务事实按照确定性规则投影为正式企业单证。

第一阶段只解决一个真实需求：

> 根据批量采购业务数据，使用既有 Excel 模板，批量生成采购合同和送货单。

这不是一个通用 Office 自动化工具，也不是 BEL Core 的组成部分。

当前阶段优先证明：

```text
business data
→ canonical document facts
→ deterministic derivation
→ template mapping
→ validation
→ generated documents
```

## 一、架构原则

必须遵守：

1. **Headless first**
   - 不建设 Web UI。
   - 不建设后台管理页面。
   - CLI 是第一操作界面。

2. **Agent-ready, but no Agent dependency**
   - Engine 不依赖任何 LLM、Agent Runtime、Pi、Codex 或 Prompt。
   - 后续 Skill / Pi 只能作为 Engine 的调用方。

3. **业务规则确定性执行**
   - 金额、税额、单价、合计、校验均由代码实现。
   - 不允许使用 LLM 计算或判断确定性业务规则。

4. **模板与业务事实解耦**
   - Canonical Document Facts 不包含 Excel 单元格坐标。
   - Excel mapping 属于模板层。

5. **当前不依赖 BEL**
   - 不引用 BEL 数据库、Domain Model 或代码。
   - 未来 BEL 通过 Adapter 转换为 DocumentFactPack。

6. **YAGNI**
   当前禁止建设：
   - 通用模板设计器
   - Web UI
   - 数据库
   - 审批流
   - 签章
   - DocumentInstance 持久化
   - 通用工作流引擎
   - AI 模板理解
   - BEL Adapter

## 二、第一阶段业务范围

支持两种 Document Definition：

```text
procurement.contract.v1
delivery.note.v1
```

使用现有两个真实 Excel 模板作为开发输入：

- 采购合同模板
- 送货单模板

真实模板和真实业务数据不得提交到公开 Git 仓库。

如需测试模板，应构造 synthetic fixture。

## 三、核心数据模型

先设计一个最小 `DocumentFactPack`。

建议至少表达：

```text
DocumentFactPack
├── business_reference
├── contract_no
├── delivery_no
├── contract_date
├── delivery_date
├── buyer
├── seller
├── ship_to
│   ├── company
│   ├── contact
│   ├── phone
│   └── address
├── currency
├── items[]
│   ├── sku
│   ├── product_name
│   ├── specification
│   ├── quantity
│   ├── unit
│   ├── gross_unit_price
│   ├── net_unit_price
│   ├── gross_amount
│   ├── net_amount
│   ├── tax_rate
│   └── tax_amount
└── optional document-specific values
```

注意：

- 不要为了追求“万能模型”提前抽象。
- 当前字段以采购合同 + 送货单真实需求为准。
- DocumentFactPack 是输入契约，不是 System of Record。

## 四、派生规则

金额和税务字段必须集中实现，不允许散落在模板 renderer 中。

至少支持：

```text
gross_amount
net_amount
tax_amount
gross_unit_price
net_unit_price
```

规则必须使用 Decimal，并明确 rounding policy。

需要支持人民币金额大写。

模板只消费已经确定的 projection values，不承担核心业务计算。

## 五、模板定义

模板 mapping 必须配置化。

建议形式：

```yaml
id: procurement.contract.v1
format: xlsx

header:
  contract_no: ...
  buyer: ...
  seller: ...
  contract_date: ...

items:
  start_row: ...
  end_row: ...
  columns:
    sku: ...
    product_name: ...
    specification: ...
    quantity: ...
    unit: ...
    net_unit_price: ...
    net_amount: ...
    tax_amount: ...
    gross_amount: ...
```

第一阶段 mapping 可以针对这两个模板手工建立。

禁止开发可视化模板编辑器。

## 六、明细行处理

第一版使用固定 capacity。

规则：

- 明细数量 <= 模板容量：正常生成；
- 不足容量：清空剩余模板行中的旧样例数据；
- 超过容量：明确失败：

```text
TEMPLATE_ITEM_CAPACITY_EXCEEDED
```

第一阶段不要实现复杂动态插行、移动合计区或自动重建打印区域。

## 七、Validation

生成前必须进行确定性校验。

至少包括：

### 单证事实校验

- 必填字段
- quantity > 0
- currency 明确
- 金额关系成立

### 金额校验

```text
Σ item gross_amount == total gross amount
Σ item net_amount + Σ item tax_amount == total gross amount
```

允许按照明确 rounding policy 存在可解释的舍入差。

### 跨单证校验

同一 DocumentFactPack 生成采购合同和送货单时至少校验：

```text
合同总金额 == 送货单总金额
合同 SKU / 数量 == 送货单 SKU / 数量
```

Validation 应返回结构化结果，而不是只抛字符串异常。

## 八、批量生成

CLI 第一版至少提供：

```bash
docflow generate \
  --input <batch-file> \
  --contract-template <xlsx> \
  --delivery-template <xlsx> \
  --output <dir>
```

输入格式可以先选择最容易稳定实现的一种：

- JSON，或
- 明确定义的 XLSX batch schema。

如内部使用 JSON 更干净，可以：

```text
Excel Adapter
→ DocumentFactPack[]
→ Engine
```

不要让 Engine 直接依赖某一种 Excel 输入布局。

批量执行必须：

- 单笔失败不导致整批中断；
- 每笔返回 PASS / FAILED；
- 给出明确失败原因；
- 输出汇总结果。

## 九、输出结构

建议：

```text
output/
├── <business-reference-1>/
│   ├── procurement-contract.xlsx
│   └── delivery-note.xlsx
├── <business-reference-2>/
│   ├── ...
│   └── ...
└── manifest.json
```

`manifest.json` 至少记录：

```text
business_reference
document_type
template_id
template_version
output_file
validation_status
issues
source_snapshot_hash
```

manifest 是未来与 BEL Evidence / Document Projection Result 衔接的稳定缝隙。

当前不需要数据库。

## 十、建议代码结构

不要机械照抄，如果分析后有更简单结构可以调整，但职责必须保持清楚：

```text
src/docflow/
├── domain/
│   ├── facts.py
│   ├── document.py
│   └── validation.py
│
├── application/
│   └── generation.py
│
├── rules/
│   ├── money.py
│   └── chinese_amount.py
│
├── templates/
│   ├── definition.py
│   └── registry.py
│
├── renderers/
│   └── xlsx.py
│
├── adapters/
│   └── batch_input.py
│
└── cli.py
```

## 十一、测试要求

必须有 synthetic tests。

至少覆盖：

1. 单笔采购合同生成；
2. 单笔送货单生成；
3. 同一 FactPack 同时生成两种单证；
4. 金额与税额计算；
5. RMB 大写；
6. 少于模板容量；
7. 等于模板容量；
8. 超过模板容量失败；
9. 缺少必填字段失败；
10. 批量中一笔失败，其余继续；
11. manifest 正确；
12. 同一输入生成结果在业务内容上稳定。

不要把用户真实公司名、地址、电话、合同编号和真实模板提交到 repository。

## 十二、第一阶段 Definition of Done

完成时必须实际证明：

```text
一份结构化业务事实
→ 采购合同.xlsx
→ 送货单.xlsx
```

且：

- 两份文件保留原模板布局；
- 商品明细完整；
- 金额正确；
- 税额正确；
- 含税/不含税价格口径正确；
- 总金额一致；
- 金额大写正确；
- 可批量执行；
- 错误可定位；
- 无 LLM 依赖；
- 无 BEL 依赖；
- 无 Web UI。

## 十三、长期方向，仅用于避免架构走死

未来可能出现：

```text
Excel → DocumentFactPack
BEL → DocumentFactPack
ERP → DocumentFactPack
```

然后统一：

```text
DocumentFactPack
→ Document Projection
→ Document Pack
```

以及：

```text
Generated Document
→ Evidence
→ BEL
```

但这些都不是当前阶段任务。

当前目标只有一句话：

> **把采购合同 + 送货单这个真实 vertical slice 做对、做稳，并留下未来可接 Agent Skill 和 BEL 的边界。**

开始前先阅读项目内 `AGENTS.md` / README 等已有约束；如果这是空仓库，则先建立最小项目骨架和 README。

先分析两个真实模板的字段、合并单元格、明细区域、公式、打印设置和样式结构，再实现，不要先凭猜测设计 mapping。

完成后输出：

1. 实现摘要；
2. 架构与关键边界；
3. 实际生成验证结果；
4. 测试结果；
5. 当前明确没有做的内容；
6. 下一步是否已经适合封装 Agent Skill。