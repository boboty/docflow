"""Builds synthetic xlsx templates that mirror the *structure* (merged cells,
item table position, subtotal formulas, capacity) of the two real templates
this project targets, using fabricated sample data.

No real template file, company name, address, phone number or contract
number is ever used here or committed to this repository.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

CONTRACT_ITEM_START_ROW = 9
CONTRACT_ITEM_END_ROW = 26  # capacity 18, matches the real template

DELIVERY_ITEM_START_ROW = 7
DELIVERY_ITEM_END_ROW = 24  # capacity 18, matches the real template


def build_contract_template(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "采购合同"

    ws.merge_cells("A1:I2")
    ws["A1"] = "采购合同"

    ws.merge_cells("A3:E3")
    ws["A3"] = "购方：示例采购方有限公司"
    ws.merge_cells("F3:I3")
    ws["F3"] = "合同编号：SAMPLE-0000"

    ws.merge_cells("A4:E4")
    ws["A4"] = "销方：示例供应商有限公司"

    ws.merge_cells("A5:I5")
    ws["A5"] = "兹经供需双方协商同意，特订立本合同如下。"

    ws.merge_cells("A6:I6")
    ws["A6"] = "一、产品名称、规格、计量单位、数量、单价、金额、交(提)货期限："

    headers = ["SKU", "产品名称", "规格型号", "数量", "单位", "单价（不含税）", "不含税金额", "税金", "价税合计"]
    for col_idx, text in enumerate(headers, start=1):
        col = openpyxl.utils.get_column_letter(col_idx)
        ws.merge_cells(f"{col}7:{col}8")
        ws[f"{col}7"] = text

    # Pre-existing sample rows (like a real template shipped with example
    # data) so tests can verify leftover rows get cleared.
    for row in range(CONTRACT_ITEM_START_ROW, CONTRACT_ITEM_END_ROW + 1):
        ws[f"A{row}"] = f"SAMPLE-SKU-{row}"
        ws[f"B{row}"] = "示例产品"
        ws[f"C{row}"] = f"示例型号-{row}"
        ws[f"D{row}"] = 1
        ws[f"E{row}"] = "件"
        ws[f"F{row}"] = 1
        ws[f"G{row}"] = 1
        ws[f"H{row}"] = 0
        ws[f"I{row}"] = 1

    ws.merge_cells("A27:F27")
    ws["A27"] = "小计"
    ws["G27"] = f"=SUM(G{CONTRACT_ITEM_START_ROW}:G{CONTRACT_ITEM_END_ROW})"
    ws["H27"] = f"=SUM(H{CONTRACT_ITEM_START_ROW}:H{CONTRACT_ITEM_END_ROW})"
    ws["I27"] = f"=SUM(I{CONTRACT_ITEM_START_ROW}:I{CONTRACT_ITEM_END_ROW})"

    ws.merge_cells("A28:F28")
    ws["A28"] = "合并（RMB大写）：零元整"
    ws.merge_cells("G28:H28")
    ws["G28"] = "合并（RMB小写）："
    ws["I28"] = "=I27"

    clause_rows = [
        (30, "二、质量要求技术标准，乙方对质量负责的条件和期限："),
        (31, "销方确保质量应符合购方确认的样品要求和标准。"),
        (33, "三、交(提)货地点、方式："),
        (34, "购方指定地点。"),
        (36, "四、运输方式和运费负担："),
        (37, "货物由销方运到购方指定地点，采购单价包含运费。"),
        (39, "五、违约责任："),
        (40, "逾期交货按合同约定支付违约金。"),
        (42, "六、结算方式及期限："),
        (43, "全款，发货前结清。"),
        (45, "七、争议解决："),
        (46, "凡本合同所引起的一切争议，双方应通过友好协商解决。"),
    ]
    for row, text in clause_rows:
        ws.merge_cells(f"A{row}:I{row}")
        ws[f"A{row}"] = text

    ws.merge_cells("A48:D48")
    ws["A48"] = "购方：示例采购方有限公司"
    ws.merge_cells("F48:I48")
    ws["F48"] = "销方：示例供应商有限公司"
    ws.merge_cells("A49:D49")
    ws["A49"] = "时间："
    ws.merge_cells("F49:I49")
    ws["F49"] = "时间："

    wb.save(path)
    return path


def build_delivery_template(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "送货单"

    ws.merge_cells("A1:H2")
    ws["A1"] = "送 货 单"

    ws.merge_cells("A3:C3")
    ws["A3"] = "收货单位：示例收货单位"
    ws.merge_cells("D3:E3")
    ws["D3"] = "联系人：示例联系人"
    ws.merge_cells("F3:H3")
    ws["F3"] = "NO：SAMPLE-0000"

    ws.merge_cells("A4:H4")
    ws["A4"] = "收货地址：示例收货地址"

    ws.merge_cells("A5:D5")
    ws["A5"] = "联系电话：00000000000"
    ws.merge_cells("E5:H5")
    ws["E5"] = "日期："

    headers = ["序号", "商品名称", "型号规格", "数量", "单位", "单价/元", "金额/元", "备注"]
    for col_idx, text in enumerate(headers, start=1):
        col = openpyxl.utils.get_column_letter(col_idx)
        ws[f"{col}6"] = text

    for row in range(DELIVERY_ITEM_START_ROW, DELIVERY_ITEM_END_ROW + 1):
        ws[f"A{row}"] = row - DELIVERY_ITEM_START_ROW + 1
        ws[f"B{row}"] = "示例产品"
        ws[f"C{row}"] = f"示例型号-{row}"
        ws[f"D{row}"] = 1
        ws[f"E{row}"] = "件"
        ws[f"F{row}"] = 1
        ws[f"G{row}"] = f"=D{row}*F{row}"

    ws["A25"] = "合计金额："
    ws.merge_cells("D25:H25")
    ws["D25"] = f"=SUM(G{DELIVERY_ITEM_START_ROW}:G{DELIVERY_ITEM_END_ROW})"

    ws.merge_cells("A27:H27")
    ws["A27"] = "说明：以上货品请核对数量，如有质量问题，请在3日内联系本公司。"

    ws.merge_cells("A28:H28")
    ws["A28"] = "送货单位：示例供应商有限公司"
    ws.merge_cells("A29:H29")
    ws["A29"] = "地址：示例发货地址"
    ws.merge_cells("A30:H30")
    ws["A30"] = "联系电话："

    ws.merge_cells("A33:D33")
    ws["A33"] = "送货单位：示例供应商有限公司"
    ws.merge_cells("E33:H33")
    ws["E33"] = "收货单位：示例收货单位"

    wb.save(path)
    return path
