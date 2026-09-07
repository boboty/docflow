"""Structured, deterministic validation results.

Validators never raise for business-rule failures; they return a
ValidationResult so callers (batch generation) can continue processing
the rest of a batch and report precise, machine-readable reasons.

Phase 0 Repair: validation is layered so it checks *facts against facts*
and *facts against derivation*, not a derived value against itself:

  - validate_fact_pack:            required fields + source fact sanity
                                    (gross_amount >= 0, quantity > 0, ...)
  - validate_source_consistency:   gross_unit_price * quantity ~= gross_amount
                                    (two independently supplied source facts)
  - validate_aggregate_consistency: Σ item.gross_amount ~= FactPack.gross_total
                                    (only when an upstream total was supplied)
  - validate_derived_consistency:  net_amount + tax_amount == gross_amount
                                    (a derivation invariant, cheap regression
                                    guard against a future rounding change)
  - validate_cross_document:       contract vs delivery totals and line
                                    identity, for a pair built from one pack
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from docflow.domain.document import DocumentProjection
from docflow.domain.facts import DocumentFactPack
from docflow.rules.money import round_money, source_consistency_tolerance

DERIVED_TOLERANCE = Decimal("0.01")


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
    """Required fields and source-fact sanity (no derivation involved)."""
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

    if pack.gross_total is not None and not pack.gross_total.is_finite():
        issues.append(ValidationIssue("NON_FINITE_VALUE", f"gross_total must be a finite number, got {pack.gross_total}", "gross_total"))

    for idx, item in enumerate(pack.items):
        prefix = f"items[{idx}]"
        require(item.sku, f"{prefix}.sku")
        require(item.product_name, f"{prefix}.product_name")
        require(item.unit, f"{prefix}.unit")

        # NaN/Infinity parse fine as Decimal but raise InvalidOperation on
        # ordering comparisons (NaN) or on quantize (Infinity) - the
        # adapters.batch_input boundary already rejects these, but this
        # validator is also public API, so it must not crash on them
        # either. Report and skip the magnitude checks below rather than
        # let `< 0` raise.
        numeric_facts = (
            ("quantity", item.quantity),
            ("gross_amount", item.gross_amount),
            ("gross_unit_price", item.gross_unit_price),
            ("tax_rate", item.tax_rate),
        )
        any_non_finite = False
        for name, value in numeric_facts:
            if not value.is_finite():
                issues.append(ValidationIssue("NON_FINITE_VALUE", f"{prefix}.{name} must be a finite number, got {value}", f"{prefix}.{name}"))
                any_non_finite = True
        if any_non_finite:
            continue

        if item.quantity <= 0:
            issues.append(ValidationIssue("QUANTITY_NOT_POSITIVE", f"{prefix}.quantity must be > 0", f"{prefix}.quantity"))
        if item.gross_amount < 0:
            issues.append(ValidationIssue("NEGATIVE_GROSS_AMOUNT", f"{prefix}.gross_amount must be >= 0", f"{prefix}.gross_amount"))
        if item.gross_unit_price < 0:
            issues.append(ValidationIssue("NEGATIVE_PRICE", f"{prefix}.gross_unit_price must be >= 0", f"{prefix}.gross_unit_price"))
        if item.tax_rate < 0:
            issues.append(ValidationIssue("NEGATIVE_TAX_RATE", f"{prefix}.tax_rate must be >= 0", f"{prefix}.tax_rate"))

    return ValidationResult(tuple(issues))


def validate_source_consistency(pack: DocumentFactPack) -> ValidationResult:
    """gross_unit_price and gross_amount are two independently supplied
    source facts; check they agree within the documented rounding-derived
    tolerance (see rules.money.source_consistency_tolerance) rather than
    silently trusting one or the other.
    """
    issues: list[ValidationIssue] = []

    for idx, item in enumerate(pack.items):
        if not (item.quantity.is_finite() and item.gross_unit_price.is_finite() and item.gross_amount.is_finite()):
            continue  # non-finite facts already reported by validate_fact_pack
        if item.quantity <= 0:
            continue  # already reported by validate_fact_pack
        expected = round_money(item.gross_unit_price * item.quantity)
        tolerance = source_consistency_tolerance(item.quantity)
        diff = abs(expected - round_money(item.gross_amount))
        if diff > tolerance:
            issues.append(ValidationIssue(
                "GROSS_UNIT_PRICE_INCONSISTENT",
                f"items[{idx}]: gross_unit_price*quantity={expected} but gross_amount="
                f"{item.gross_amount} (diff={diff} > tolerance={tolerance})",
                f"items[{idx}].gross_amount",
            ))

    return ValidationResult(tuple(issues))


def validate_aggregate_consistency(pack: DocumentFactPack) -> ValidationResult:
    """Only checked when the caller supplied an independent source total."""
    if pack.gross_total is None or not pack.gross_total.is_finite():
        return ValidationResult.ok()  # non-finite gross_total already reported by validate_fact_pack
    if any(not item.gross_amount.is_finite() for item in pack.items):
        return ValidationResult.ok()  # non-finite item facts already reported by validate_fact_pack

    total = round_money(sum((item.gross_amount for item in pack.items), Decimal("0")))
    supplied = round_money(pack.gross_total)
    if abs(total - supplied) > DERIVED_TOLERANCE:
        return ValidationResult.failed(ValidationIssue(
            "SOURCE_TOTAL_MISMATCH",
            f"sum(items.gross_amount)={total} != FactPack.gross_total={supplied}",
            "gross_total",
        ))
    return ValidationResult.ok()


def validate_derived_consistency(projection: DocumentProjection) -> ValidationResult:
    """net_amount + tax_amount == gross_amount, per line.

    This holds by construction of rules.money.compute_line_item_amounts; it
    is kept as an explicit, cheap regression guard rather than removed,
    since a future change to the derivation could silently break it.
    """
    issues: list[ValidationIssue] = []

    for idx, item in enumerate(projection.items):
        if abs((item.net_amount + item.tax_amount) - item.gross_amount) > DERIVED_TOLERANCE:
            issues.append(ValidationIssue(
                "NET_PLUS_TAX_MISMATCH",
                f"items[{idx}]: net_amount({item.net_amount}) + tax_amount({item.tax_amount}) "
                f"!= gross_amount({item.gross_amount})",
            ))

    return ValidationResult(tuple(issues))


def validate_cross_document(
    contract: DocumentProjection, delivery: DocumentProjection
) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if abs(contract.totals.gross_total - delivery.totals.gross_total) > DERIVED_TOLERANCE:
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
