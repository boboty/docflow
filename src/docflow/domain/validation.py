"""Structured, deterministic validation results.

Validators never raise for business-rule failures; they return a
ValidationResult so callers (batch generation) can continue processing
the rest of a batch and report precise, machine-readable reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from docflow.domain.document import DocumentProjection
from docflow.domain.facts import DocumentFactPack

AMOUNT_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(())

    @classmethod
    def failed(cls, *issues: ValidationIssue) -> "ValidationResult":
        return cls(tuple(issues))

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        return ValidationResult(self.issues + other.issues)


def validate_fact_pack(pack: DocumentFactPack) -> ValidationResult:
    issues: list[ValidationIssue] = []

    def require(value: object, field_name: str) -> None:
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(ValidationIssue("REQUIRED_FIELD_MISSING", f"{field_name} is required", field_name))

    require(pack.business_reference, "business_reference")
    require(pack.contract_no, "contract_no")
    require(pack.delivery_no, "delivery_no")
    require(pack.buyer, "buyer")
    require(pack.seller, "seller")
    require(pack.currency, "currency")
    require(pack.ship_to.company, "ship_to.company")
    require(pack.ship_to.address, "ship_to.address")

    if not pack.items:
        issues.append(ValidationIssue("NO_LINE_ITEMS", "at least one line item is required", "items"))

    for idx, item in enumerate(pack.items):
        prefix = f"items[{idx}]"
        require(item.sku, f"{prefix}.sku")
        require(item.product_name, f"{prefix}.product_name")
        require(item.unit, f"{prefix}.unit")
        if item.quantity <= 0:
            issues.append(ValidationIssue("QUANTITY_NOT_POSITIVE", f"{prefix}.quantity must be > 0", f"{prefix}.quantity"))
        if item.net_unit_price < 0:
            issues.append(ValidationIssue("NEGATIVE_PRICE", f"{prefix}.net_unit_price must be >= 0", f"{prefix}.net_unit_price"))
        if item.tax_rate < 0:
            issues.append(ValidationIssue("NEGATIVE_TAX_RATE", f"{prefix}.tax_rate must be >= 0", f"{prefix}.tax_rate"))

    return ValidationResult(tuple(issues))


def validate_amounts(projection: DocumentProjection) -> ValidationResult:
    issues: list[ValidationIssue] = []

    sum_gross = sum((i.gross_amount for i in projection.items), Decimal("0"))
    if abs(sum_gross - projection.totals.gross_total) > AMOUNT_TOLERANCE:
        issues.append(ValidationIssue(
            "GROSS_AMOUNT_MISMATCH",
            f"sum(item.gross_amount)={sum_gross} != total.gross_total={projection.totals.gross_total}",
        ))

    sum_net_plus_tax = sum(
        (i.net_amount + i.tax_amount for i in projection.items), Decimal("0")
    )
    if abs(sum_net_plus_tax - projection.totals.gross_total) > AMOUNT_TOLERANCE:
        issues.append(ValidationIssue(
            "NET_PLUS_TAX_MISMATCH",
            f"sum(net_amount+tax_amount)={sum_net_plus_tax} != total.gross_total={projection.totals.gross_total}",
        ))

    return ValidationResult(tuple(issues))


def validate_cross_document(
    contract: DocumentProjection, delivery: DocumentProjection
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if abs(contract.totals.gross_total - delivery.totals.gross_total) > AMOUNT_TOLERANCE:
        issues.append(ValidationIssue(
            "CROSS_DOCUMENT_TOTAL_MISMATCH",
            f"contract.gross_total={contract.totals.gross_total} != "
            f"delivery.gross_total={delivery.totals.gross_total}",
        ))

    if contract.item_identity_sequence != delivery.item_identity_sequence:
        issues.append(ValidationIssue(
            "CROSS_DOCUMENT_ITEMS_MISMATCH",
            "contract and delivery note line items (sku, quantity) do not match",
        ))

    return ValidationResult(tuple(issues))
