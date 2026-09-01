"""
中文用途：应用安装初始化文件。

这里放安装/迁移后的轻量初始化：
1. 初始化系统配置
2. 初始化默认分摊规则
3. 初始化状态字典
4. 初始化 ERP 桌面入口
"""

from __future__ import annotations

import json


WORKSPACE_LABEL = "海外成本核算"
WORKSPACE_TITLE = "海外成本核算"
WORKSPACE_HEADING = "海外采购综合成本核算"
WORKBENCH_PAGE = "overseas-cost-workbench"
ACCESS_ROLE = "海外成本核算用户"
ERP_SETTINGS_DOCTYPE = "Overseas Cost ERP Settings"
HOME_WORKSPACE_LABEL = "Home"
HOME_SHORTCUT_LABEL = "海外成本核算"
HOME_SHORTCUT_ID = "overseas-cost-home-shortcut"
WORKSPACE_NAME_CANDIDATES = (
    "海外成本核算",
    "海外采购综合成本核算",
)


def after_install() -> None:
    """中文用途：Frappe 安装 app 后的初始化入口。"""

    ensure_language_defaults()
    ensure_access_role()
    ensure_erpnext_standard_fields()
    ensure_workspace()


def after_migrate() -> None:
    """中文用途：Frappe migrate 后确保桌面入口存在。"""

    ensure_language_defaults()
    ensure_access_role()
    ensure_erpnext_standard_fields()
    ensure_workspace()


def _normalize_language_code(value: object) -> str:
    """把历史上误存的 ``[zh]``/``["zh"]`` 还原为 Frappe 语言编码。"""

    normalized = str(value or "").strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1].strip().strip("'\"").strip()
    return normalized or "en"


def ensure_language_defaults() -> dict:
    """修复语言被保存成列表字符串后导致页面回退英文的问题。"""

    try:
        import frappe
    except Exception:
        return {"ok": False, "message": "当前未连接 Frappe。"}

    changed_users = 0
    changed_defaults = 0
    changed_system = False

    users = frappe.db.sql(
        """
        select name, language
        from `tabUser`
        where language like '[%'
        """,
        as_dict=True,
    )
    for user in users:
        language = _normalize_language_code(user.language)
        frappe.db.set_value("User", user.name, "language", language, update_modified=False)
        changed_users += 1

    defaults = frappe.db.sql(
        """
        select name, defvalue
        from `tabDefaultValue`
        where defkey in ('lang', 'language')
          and defvalue like '[%'
        """,
        as_dict=True,
    )
    for default in defaults:
        language = _normalize_language_code(default.defvalue)
        frappe.db.set_value(
            "DefaultValue",
            default.name,
            "defvalue",
            language,
            update_modified=False,
        )
        changed_defaults += 1

    system_language = frappe.db.get_single_value("System Settings", "language")
    if system_language and system_language != _normalize_language_code(system_language):
        frappe.db.set_single_value(
            "System Settings",
            "language",
            _normalize_language_code(system_language),
        )
        changed_system = True

    if changed_users or changed_defaults or changed_system:
        frappe.db.commit()

    return {
        "ok": True,
        "changed_users": changed_users,
        "changed_defaults": changed_defaults,
        "changed_system": changed_system,
    }


def ensure_access_role() -> dict:
    """创建工作台专用角色，避免业务人员必须使用 System Manager。"""

    try:
        import frappe
    except Exception:
        return {"ok": False, "message": "当前未连接 Frappe。"}

    if not frappe.db.exists("Role", ACCESS_ROLE):
        role = frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": ACCESS_ROLE,
                "desk_access": 1,
                "is_custom": 1,
            }
        )
        role.insert(ignore_permissions=True)
        frappe.db.commit()
        return {"ok": True, "created": True, "role": ACCESS_ROLE}

    role = frappe.get_doc("Role", ACCESS_ROLE)
    changed = False
    if hasattr(role, "desk_access") and not role.desk_access:
        role.desk_access = 1
        changed = True
    if changed:
        role.save(ignore_permissions=True)
        frappe.db.commit()
    return {"ok": True, "created": False, "changed": changed, "role": ACCESS_ROLE}


def ensure_erpnext_standard_fields() -> dict:
    """给 ERPNext 标准单据补海外成本展示字段。

    只新增展示/追溯字段，不改库存估值、入库成本和总账逻辑。
    """

    try:
        import frappe
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    except Exception:
        return {"ok": False, "message": "当前未连接 Frappe 或 Custom Field 工具不可用。"}

    required_doctypes = ("Item", "Purchase Order", "Purchase Order Item")
    missing_doctypes = [doctype for doctype in required_doctypes if not frappe.db.exists("DocType", doctype)]
    if missing_doctypes:
        return {"ok": False, "message": "ERPNext 标准 DocType 不存在，已跳过自定义字段。", "missing": missing_doctypes}

    custom_fields = {
        "Item": [
            {
                "fieldname": "custom_overseas_batch_no",
                "label": "海外成本批次号",
                "fieldtype": "Data",
                "insert_after": "item_name",
            },
            {
                "fieldname": "custom_overseas_cost_version",
                "label": "海外成本计算版本",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_batch_no",
            },
            {
                "fieldname": "custom_overseas_business_entity",
                "label": "业务主体/子公司",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_cost_version",
            },
            {
                "fieldname": "custom_overseas_supplier",
                "label": "供应商",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_business_entity",
            },
            {
                "fieldname": "custom_overseas_original_unit_price",
                "label": "原始采购单价",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_supplier",
            },
            {
                "fieldname": "custom_overseas_comprehensive_unit_price",
                "label": "综合物品单价",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_original_unit_price",
            },
        ],
        "Purchase Order": [
            {
                "fieldname": "custom_overseas_batch_no",
                "label": "海外成本批次号",
                "fieldtype": "Data",
                "insert_after": "company",
            },
            {
                "fieldname": "custom_overseas_cost_version",
                "label": "海外成本计算版本",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_batch_no",
            },
            {
                "fieldname": "custom_overseas_business_entity",
                "label": "业务主体/子公司",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_cost_version",
            },
            {
                "fieldname": "custom_overseas_supplier_source",
                "label": "供应商来源",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_business_entity",
            },
            {
                "fieldname": "custom_overseas_total_cost_rmb",
                "label": "综合成本金额 RMB",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_supplier_source",
            },
            {
                "fieldname": "custom_overseas_cost_payload_json",
                "label": "海外成本技术报文",
                "fieldtype": "Long Text",
                "insert_after": "custom_overseas_total_cost_rmb",
            },
        ],
        "Purchase Order Item": [
            {
                "fieldname": "custom_overseas_original_unit_price",
                "label": "原始采购单价",
                "fieldtype": "Currency",
                "insert_after": "rate",
            },
            {
                "fieldname": "custom_overseas_comprehensive_unit_price",
                "label": "综合物品单价",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_original_unit_price",
            },
            {
                "fieldname": "custom_overseas_original_amount",
                "label": "原始采购金额",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_comprehensive_unit_price",
            },
            {
                "fieldname": "custom_overseas_comprehensive_amount",
                "label": "综合成本金额",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_original_amount",
            },
            {
                "fieldname": "custom_overseas_freight_alloc_amount",
                "label": "运费分摊额",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_comprehensive_amount",
            },
            {
                "fieldname": "custom_overseas_clearance_alloc_amount",
                "label": "清关费分摊额",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_freight_alloc_amount",
            },
            {
                "fieldname": "custom_overseas_tax_alloc_amount",
                "label": "税费分摊额",
                "fieldtype": "Currency",
                "insert_after": "custom_overseas_clearance_alloc_amount",
            },
            {
                "fieldname": "custom_overseas_batch_no",
                "label": "批次号",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_tax_alloc_amount",
            },
            {
                "fieldname": "custom_overseas_cost_version",
                "label": "成本计算版本",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_batch_no",
            },
            {
                "fieldname": "custom_overseas_business_entity",
                "label": "业务主体/子公司",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_cost_version",
            },
            {
                "fieldname": "custom_overseas_cost_center",
                "label": "成本中心",
                "fieldtype": "Data",
                "insert_after": "custom_overseas_business_entity",
            },
        ],
    }
    try:
        create_custom_fields(custom_fields, ignore_validate=True)
    except TypeError:
        create_custom_fields(custom_fields)
    return {"ok": True, "message": "ERPNext 标准单据海外成本字段已确保存在。"}


def ensure_workspace() -> dict:
    """创建/更新 ERP 首页的海外成本入口。

    目标是在 Desk 首页应用卡片中展示“海外成本核算”，位置尽量跟随
    Deeplinkerp Settings 后面。点击卡片后进入工作区，再进入综合成本工作台。
    """

    try:
        import frappe
    except Exception:
        return {"ok": False, "message": "当前未连接 Frappe。"}

    settings_result = _ensure_erp_settings_defaults(frappe)

    if not frappe.db.exists("DocType", "Workspace"):
        return {"ok": False, "message": "当前站点没有 Workspace DocType。"}

    workspace_name = None
    for candidate in WORKSPACE_NAME_CANDIDATES:
        workspace_name = (
            frappe.db.exists("Workspace", candidate)
            or frappe.db.exists("Workspace", {"label": candidate})
            or frappe.db.exists("Workspace", {"title": candidate})
        )
        if workspace_name:
            break
    if workspace_name:
        doc = frappe.get_doc("Workspace", workspace_name)
        created = False
    else:
        doc = frappe.get_doc({"doctype": "Workspace"})
        created = True

    _set_if_field(doc, "label", WORKSPACE_LABEL)
    _set_if_field(doc, "title", WORKSPACE_TITLE)
    _set_if_field(doc, "module", "Overseas Costing")
    _set_if_field(doc, "type", "Workspace")
    _set_if_field(doc, "public", 1)
    _set_if_field(doc, "is_hidden", 0)
    _set_if_field(doc, "icon", "calculator")
    _set_if_field(doc, "indicator_color", "blue")
    _set_if_field(doc, "sequence_id", _resolve_workspace_sequence(frappe))

    _set_workspace_content(doc)
    if created:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    home_shortcut_result = _ensure_home_shortcut(frappe)
    frappe.db.commit()
    return {
        "ok": True,
        "created": created,
        "workspace": doc.name,
        "erp_settings": settings_result,
        "home_shortcut": home_shortcut_result,
        "message": "海外成本核算入口已更新。",
    }


def _ensure_erp_settings_defaults(frappe) -> dict:
    if not frappe.db.exists("DocType", ERP_SETTINGS_DOCTYPE):
        return {"ok": False, "message": "ERP 对接设置 DocType 尚未安装。"}

    try:
        settings = frappe.get_single(ERP_SETTINGS_DOCTYPE)
    except Exception as exc:
        return {"ok": False, "message": f"ERP 对接设置读取失败：{exc}"}

    changed = False
    stock_uom = "Nos" if frappe.db.exists("UOM", "Nos") else None
    defaults = {
        "enabled": 1,
        "base_url": "https://deeplinkerp.com/api/resource",
        "push_mode": "标准模块（物料+采购订单）",
        "item_group": "All Item Groups",
        "stock_uom": stock_uom,
        "default_currency": "CNY",
        "http_method": "POST",
        "timeout": 20,
        "payload_field": "payload_json",
    }
    for fieldname, value in defaults.items():
        if value is not None and _has_field(settings, fieldname) and not getattr(settings, fieldname, None):
            setattr(settings, fieldname, value)
            changed = True

    if changed:
        settings.save(ignore_permissions=True)
    return {"ok": True, "changed": changed}


def _set_workspace_content(doc) -> None:
    content = [
        {
            "id": "overseas-cost-heading",
            "type": "header",
            "data": {"text": WORKSPACE_HEADING, "col": 12},
        },
        {
            "id": "overseas-cost-workbench-card",
            "type": "shortcut",
            "data": {
                "shortcut_name": "综合成本工作台",
                "col": 3,
            },
        },
        {
            "id": "overseas-cost-erp-settings-card",
            "type": "shortcut",
            "data": {
                "shortcut_name": "ERP 对接设置",
                "col": 3,
            },
        },
    ]
    _set_if_field(doc, "content", json.dumps(content, ensure_ascii=False))
    _set_child_table(
        doc,
        "shortcuts",
        [
            {
                "type": "Page",
                "label": "综合成本工作台",
                "link_to": WORKBENCH_PAGE,
                "color": "Blue",
            },
            {
                "type": "DocType",
                "label": "ERP 对接设置",
                "link_to": ERP_SETTINGS_DOCTYPE,
                "color": "Green",
            }
        ],
    )
    for fieldname in ("links", "charts", "number_cards", "quick_lists", "custom_blocks", "roles"):
        _set_child_table(doc, fieldname, [])


def _resolve_workspace_sequence(frappe) -> float:
    for label in ("Deeplinkerp Settings", "DeeplinkERP Settings", "Deeplinkerp设置"):
        try:
            sequence = frappe.db.get_value("Workspace", {"label": label}, "sequence_id")
        except Exception:
            sequence = None
        if sequence not in (None, ""):
            try:
                return float(sequence) + 0.1
            except (TypeError, ValueError):
                return 14.1
    return 14.1


def _ensure_home_shortcut(frappe) -> dict:
    """在 /app 首页追加海外成本核算快捷入口，不覆盖 Home 原有布局。"""

    home_name = (
        frappe.db.exists("Workspace", HOME_WORKSPACE_LABEL)
        or frappe.db.exists("Workspace", {"label": HOME_WORKSPACE_LABEL})
        or frappe.db.exists("Workspace", {"title": HOME_WORKSPACE_LABEL})
    )
    if not home_name:
        return {"ok": False, "message": "未找到 Home 工作区。"}

    home = frappe.get_doc("Workspace", home_name)
    content = _load_workspace_content(getattr(home, "content", None))
    if content is None:
        return {"ok": False, "message": "Home 工作区 content 不是可解析的 JSON，已跳过。"}

    changed = _upsert_home_shortcut_content(content)
    if _upsert_home_shortcut_row(home):
        changed = True

    if changed:
        _set_if_field(home, "content", json.dumps(content, ensure_ascii=False))
        home.save(ignore_permissions=True)
    return {"ok": True, "changed": changed, "workspace": home.name}


def _load_workspace_content(raw_content) -> list[dict] | None:
    if isinstance(raw_content, list):
        return raw_content
    if not raw_content:
        return []
    try:
        content = json.loads(raw_content)
    except (TypeError, ValueError):
        return None
    if not isinstance(content, list):
        return None
    return content


def _upsert_home_shortcut_content(content: list[dict]) -> bool:
    shortcut_block = {
        "id": HOME_SHORTCUT_ID,
        "type": "shortcut",
        "data": {
            "shortcut_name": HOME_SHORTCUT_LABEL,
            "col": 3,
        },
    }

    for block in content:
        data = block.get("data") if isinstance(block, dict) else None
        if block.get("id") == HOME_SHORTCUT_ID or (
            block.get("type") == "shortcut"
            and isinstance(data, dict)
            and data.get("shortcut_name") == HOME_SHORTCUT_LABEL
        ):
            if block != shortcut_block:
                block.clear()
                block.update(shortcut_block)
                return True
            return False

    insert_at = None
    for index, block in enumerate(content):
        data = block.get("data") if isinstance(block, dict) else None
        shortcut_name = data.get("shortcut_name") if isinstance(data, dict) else None
        if shortcut_name in ("Deeplinkerp Settings", "DeeplinkERP Settings", "Deeplinkerp设置"):
            insert_at = index + 1
            break

    if insert_at is None:
        content.append(shortcut_block)
    else:
        content.insert(insert_at, shortcut_block)
    return True


def _upsert_home_shortcut_row(home) -> bool:
    row_data = {
        "type": "Page",
        "label": HOME_SHORTCUT_LABEL,
        "link_to": WORKBENCH_PAGE,
        "color": "Blue",
    }

    if not _has_field(home, "shortcuts"):
        return False

    for row in home.get("shortcuts") or []:
        if getattr(row, "label", None) == HOME_SHORTCUT_LABEL:
            changed = False
            for fieldname, value in row_data.items():
                if getattr(row, fieldname, None) != value:
                    setattr(row, fieldname, value)
                    changed = True
            return changed

    home.append("shortcuts", row_data)
    return True


def _set_if_field(doc, fieldname: str, value) -> None:
    if _has_field(doc, fieldname):
        setattr(doc, fieldname, value)


def _set_child_table(doc, fieldname: str, rows: list[dict]) -> None:
    if not _has_field(doc, fieldname):
        return
    try:
        doc.set(fieldname, [])
        for row in rows:
            doc.append(fieldname, row)
    except Exception:
        setattr(doc, fieldname, rows)


def _has_field(doc, fieldname: str) -> bool:
    meta = getattr(doc, "meta", None)
    if not meta:
        return True
    try:
        return bool(meta.has_field(fieldname))
    except Exception:
        return True
