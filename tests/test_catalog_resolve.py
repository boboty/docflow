from pathlib import Path

from docflow.catalog.models import Address, Catalog, Contact, Organization, Product, TemplateEntry
from docflow.catalog.resolve import resolve_organization, resolve_product, resolve_template


def _catalog(**kwargs) -> Catalog:
    return Catalog(
        organizations=kwargs.get("organizations", {}),
        products=kwargs.get("products", {}),
        templates=kwargs.get("templates", {}),
    )


def _supplier_org(**overrides) -> Organization:
    defaults = dict(
        id="supplier_linyi_yier",
        name="临沂亦尔科技有限公司",
        roles=("supplier",),
        aliases=("临沂亦尔", "亦尔临沂"),
        contacts=(Contact(id="default", name="张三", label="默认联系人", phone="13800000000", default=True),),
        addresses=(Address(id="registered", address="山东省临沂市示例地址", label="注册地址", default=True),),
    )
    defaults.update(overrides)
    return Organization(**defaults)


# 1. organization formal name resolve
def test_resolve_organization_by_formal_name():
    org = _supplier_org()
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, "临沂亦尔科技有限公司")
    assert result["status"] == "RESOLVED"
    assert result["id"] == "supplier_linyi_yier"


# 2. organization alias resolve
def test_resolve_organization_by_alias():
    org = _supplier_org()
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, "临沂亦尔")
    assert result["status"] == "RESOLVED"
    assert result["id"] == "supplier_linyi_yier"


# 3. role filter
def test_resolve_organization_role_filter_excludes_non_matching_role():
    org = _supplier_org()
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, "临沂亦尔", role="ship_to")
    assert result["status"] == "NOT_FOUND"


def test_resolve_organization_role_filter_matches():
    org = _supplier_org()
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, "临沂亦尔", role="supplier")
    assert result["status"] == "RESOLVED"
    assert result["role"] == "supplier"


# 4. product SKU resolve
def test_resolve_product_by_sku():
    product = Product(id="ST01-Black", name="示例黑色产品", specification="ST01-Black", unit="双")
    catalog = _catalog(products={product.id: product})
    result = resolve_product(catalog, "ST01-Black")
    assert result["status"] == "RESOLVED"
    assert result["id"] == "ST01-Black"


# 5. product alias resolve
def test_resolve_product_by_alias():
    product = Product(id="ST01-Black", name="示例黑色产品", unit="双", aliases=("ST01黑", "黑色款"))
    catalog = _catalog(products={product.id: product})
    result = resolve_product(catalog, "ST01黑")
    assert result["status"] == "RESOLVED"
    assert result["id"] == "ST01-Black"


# 6. single contact auto-select (no default flag needed)
def test_single_contact_auto_selected_without_default_flag():
    org = _supplier_org(contacts=(Contact(id="only", name="王五", default=False),))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name)
    assert result["status"] == "RESOLVED"
    assert result["contact"]["id"] == "only"


# 7. multi-contact + default
def test_multi_contact_with_default_selected():
    org = _supplier_org(contacts=(
        Contact(id="c1", name="张三", default=True),
        Contact(id="c2", name="李四", default=False),
    ))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name)
    assert result["status"] == "RESOLVED"
    assert result["contact"]["id"] == "c1"


# 8. multi-contact no default -> AMBIGUOUS
def test_multi_contact_without_default_is_ambiguous():
    org = _supplier_org(contacts=(
        Contact(id="c1", name="张三", default=False),
        Contact(id="c2", name="李四", default=False),
    ))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name)
    assert result["status"] == "AMBIGUOUS"
    assert result["field"] == "contact"
    assert {c["id"] for c in result["candidates"]} == {"c1", "c2"}


# 9. explicit contact overrides default
def test_explicit_contact_query_overrides_default():
    org = _supplier_org(contacts=(
        Contact(id="c1", name="张三", label="默认", default=True),
        Contact(id="c2", name="李四", label="财务", default=False),
    ))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name, contact_query="财务")
    assert result["status"] == "RESOLVED"
    assert result["contact"]["id"] == "c2"


# 10. single address auto-select
def test_single_address_auto_selected_without_default_flag():
    org = _supplier_org(addresses=(Address(id="only", address="示例地址", default=False),))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name)
    assert result["status"] == "RESOLVED"
    assert result["address"]["id"] == "only"


# 11. multi-address + default
def test_multi_address_with_default_selected():
    org = _supplier_org(addresses=(
        Address(id="a1", address="地址1", default=True),
        Address(id="a2", address="地址2", default=False),
    ))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name)
    assert result["status"] == "RESOLVED"
    assert result["address"]["id"] == "a1"


# 12. multi-address no default -> AMBIGUOUS
def test_multi_address_without_default_is_ambiguous():
    org = _supplier_org(addresses=(
        Address(id="yiwu", address="地址1", label="义乌仓", default=False),
        Address(id="guangzhou", address="地址2", label="广州仓", default=False),
    ))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name)
    assert result["status"] == "AMBIGUOUS"
    assert result["field"] == "address"
    assert {a["label"] for a in result["candidates"]} == {"义乌仓", "广州仓"}


# 13. explicit address label overrides default
def test_explicit_address_label_overrides_default():
    org = _supplier_org(addresses=(
        Address(id="yiwu", address="地址1", label="义乌仓", default=True),
        Address(id="guangzhou", address="地址2", label="广州仓", default=False),
    ))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, org.name, address_query="广州仓")
    assert result["status"] == "RESOLVED"
    assert result["address"]["id"] == "guangzhou"


# 14. duplicate alias across two organizations -> AMBIGUOUS
def test_duplicate_alias_across_organizations_is_ambiguous():
    org_a = Organization(id="org_a", name="甲公司", aliases=("小甲",))
    org_b = Organization(id="org_b", name="乙公司", aliases=("小甲",))
    catalog = _catalog(organizations={org_a.id: org_a, org_b.id: org_b})
    result = resolve_organization(catalog, "小甲")
    assert result["status"] == "AMBIGUOUS"
    assert result["field"] == "organization"
    assert {c["id"] for c in result["candidates"]} == {"org_a", "org_b"}


def test_organization_not_found():
    catalog = _catalog()
    result = resolve_organization(catalog, "不存在的公司")
    assert result["status"] == "NOT_FOUND"


def test_product_not_found():
    catalog = _catalog()
    result = resolve_product(catalog, "NO-SUCH-SKU")
    assert result["status"] == "NOT_FOUND"


# 16. template resolve
def test_resolve_template_by_key(tmp_path):
    template = TemplateEntry(key="procurement_contract", document_type="procurement.contract.v1", path="/x.xlsx")
    catalog = _catalog(templates={template.key: template})
    result = resolve_template(catalog, "procurement_contract", catalog_root=tmp_path)
    assert result["status"] == "RESOLVED"
    assert result["document_type"] == "procurement.contract.v1"
    assert result["path"] == "/x.xlsx"  # absolute path: returned as-is (legacy-compatible)


def test_resolve_template_not_found(tmp_path):
    catalog = _catalog()
    result = resolve_template(catalog, "no_such_template", catalog_root=tmp_path)
    assert result["status"] == "NOT_FOUND"


def test_resolve_template_relative_path_resolved_against_catalog_root(tmp_path):
    catalog_root = tmp_path / "workspace" / ".docflow" / "catalog"
    template = TemplateEntry(
        key="procurement_contract", document_type="procurement.contract.v1",
        path="../templates/procurement_contract.xlsx",
    )
    catalog = _catalog(templates={template.key: template})
    result = resolve_template(catalog, "procurement_contract", catalog_root=catalog_root)
    assert result["status"] == "RESOLVED"
    expected = (catalog_root / "../templates/procurement_contract.xlsx").resolve()
    assert result["path"] == str(expected)
    assert Path(result["path"]).is_absolute()


def test_resolve_normalizes_whitespace_and_case_for_ascii():
    org = Organization(id="acme", name="ACME Co", aliases=("acme-alias",))
    catalog = _catalog(organizations={org.id: org})
    result = resolve_organization(catalog, "  ACME-ALIAS  ")
    assert result["status"] == "RESOLVED"
    assert result["id"] == "acme"
