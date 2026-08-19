"""
中文用途：批量拉取钉钉国际物流审批单，并先筛出海运审批追溯数据。

当前脚本只做只读拉取和本地输出，不写入 ERP/Frappe：
1. 按流程模板 process_code 和时间范围拉审批实例 ID
2. 逐条读取审批实例详情
3. 从表单字段中筛选“物流方式=海运”的审批单
4. 输出 JSON / CSV，供人工核对后再决定是否导入系统

运行示例：
python -m overseas_costing.scripts.import_oa_logistics ^
  --process-code PROC-XXXX ^
  --start 2026-07-01 ^
  --end 2026-07-21 ^
  --output data/dingtalk_sea_approvals.json ^
  --csv data/dingtalk_sea_approvals.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import frappe
except Exception:  # pragma: no cover - 本地命令行无 Frappe 环境时保持可运行
    frappe = None

CURRENT_FILE = Path(__file__).resolve()
PACKAGE_ROOT = CURRENT_FILE.parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from overseas_costing.utils.dingtalk import build_dingtalk_order_payload, extract_dingtalk_instance_id
from overseas_costing.utils.field_mapper import map_oa_row_to_item, map_purchase_expense_row_to_item, normalize_unit

NEW_TOKEN_PATH = "/v1.0/oauth2/{corp_id}/token"
NEW_LIST_INSTANCE_IDS_PATH = "/v1.0/workflow/processes/instanceIds/query"
NEW_INSTANCE_DETAIL_PATH = "/v1.0/workflow/processInstances?processInstanceId={process_instance_id}"
NEW_APPROVAL_ATTACHMENT_DOWNLOAD_PATH = "/v1.0/workflow/processInstances/spaces/files/urls/download"
NEW_APPROVAL_ATTACHMENT_AUTH_DOWNLOAD_PATH = "/v1.0/workflow/processInstances/spaces/files/authDownload"

LEGACY_TOKEN_PATH = "/gettoken"
LEGACY_LIST_INSTANCE_IDS_PATH = "/topapi/processinstance/listids?access_token={access_token}"
LEGACY_INSTANCE_DETAIL_PATH = "/topapi/processinstance/get?access_token={access_token}"
LEGACY_APPROVAL_ATTACHMENT_DOWNLOAD_PATH = "/topapi/processinstance/file/url/get?access_token={access_token}"
LEGACY_APPROVAL_ATTACHMENT_SPACE_PATH = "/topapi/processinstance/cspace/info?access_token={access_token}"
LEGACY_APPROVAL_ATTACHMENT_DENTRY_AUTH_PATH = "/topapi/process/dentry/auth?access_token={access_token}"
LEGACY_USER_DETAIL_PATH = "/topapi/v2/user/get?access_token={access_token}"
NEW_STORAGE_DENTRY_DOWNLOAD_INFO_PATH = "/v1.0/storage/spaces/{space_id}/dentries/{dentry_id}/downloadInfos/query"
NEW_STORAGE_DENTRY_LIST_PATH = "/v1.0/storage/spaces/{space_id}/dentries"
NEW_DRIVE_FILE_DOWNLOAD_INFO_PATH = "/v1.0/drive/spaces/{space_id}/files/{file_id}/downloadInfos"
NEW_STORAGE_THUMBNAILS_QUERY_PATH = "/v1.0/storage/spaces/{space_id}/thumbnails/query"

DEFAULT_SEA_KEYWORDS = ("海运", "SEA", "OCEAN", "MARITIMO", "MARÍTIMO")
TRANSPORT_MODE_KEYWORDS = {
    "EXPRESS": ("快递", "EXPRESS", "COURIER", "CORREO EXPRESS", "CORREO", "DHL", "FEDEX", "UPS"),
    "AIR": ("空运", "AIR", "AIR FREIGHT", "CARGA AEREA", "CARGA AÉREA", "AEREA", "AÉREA"),
    "SEA": DEFAULT_SEA_KEYWORDS + ("OCEAN FREIGHT", "CONTENEDOR", "MARITIMO", "MARÍTIMO"),
}
TRANSPORT_MODE_LABELS = {
    "SEA": "海运",
    "AIR": "空运",
    "EXPRESS": "快递",
}
HIDDEN_APPROVAL_STATUSES = ("TERMINATED", "CANCELED", "CANCELLED", "REVOKED", "撤销", "已撤销")
COMPLETED_APPROVAL_STATUSES = ("COMPLETED", "FINISHED", "AGREE", "APPROVED", "已完成", "审批通过", "同意")
TRANSPORT_FIELD_ALIASES = (
    "物流方式",
    "运输方式",
    "物流方式Camino Envío",
    "物流方式Camino Envio",
    "Camino Envío",
    "Camino Envio",
    "way",
    "transport",
)
BATCH_NO_FIELD_ALIASES = (
    "柜号/单号Número DE Logística",
    "柜号/单号Numero DE Logistica",
    "Número DE Logística",
    "Numero DE Logistica",
    "物流单号",
    "运单号",
    "柜号",
    "单号",
)
LOGISTICS_FEE_FIELD_ALIASES = (
    "物流费用",
    "运费金额",
    "国际运费",
    "海运费",
    "空运费",
    "logisticsfee",
    "freight",
)
LOGISTICS_QUOTE_FIELD_ALIASES = (
    "物流报价",
    "物流报价Cotización de logística",
    "物流报价Cotizacion de logistica",
    "Cotización de logística",
    "Cotizacion de logistica",
    "报价",
)
LOGISTICS_CURRENCY_FIELD_ALIASES = (
    "币种Moneda",
    "币种",
    "Moneda",
)
LOGISTICS_WEIGHT_FIELD_ALIASES = (
    "重量Peso（KG）",
    "重量Peso(KG)",
    "重量Peso",
    "重量",
    "Peso",
    "Peso KG",
)
LOGISTICS_PRE_DELIVERY_FIELD_ALIASES = (
    "预计发货日期Fecha de Pre-entrega",
    "预计发货日期",
    "Fecha de Pre-entrega",
    "Fecha de Pre entrega",
    "Pre-entrega",
)
LOGISTICS_DESTINATION_FIELD_ALIASES = (
    "目标地区Países destinatarios",
    "目标地区Paises destinatarios",
    "目标地区",
    "Países destinatarios",
    "Paises destinatarios",
    "目的地",
    "目的国",
)
GOODS_TABLE_FIELD_ALIASES = ("货物信息", "Bienes")
BUSINESS_ENTITY_FIELD_ALIASES = (
    "业务主体",
    "业务主体Empresas",
    "Entidad comercial",
    "Empresas",
    "Empresa",
    "Business Entity",
    "Company",
    "公司主体",
    "归属公司",
    "子公司",
)
PURCHASE_DETAIL_TABLE_FIELD_ALIASES = (
    "需求明细",
    "Desglose de los gastos",
)
PURCHASE_CURRENCY_FIELD_ALIASES = (
    "币种Moneda",
    "币种",
    "Moneda",
)
PURCHASE_RELATE_FIELD_ALIASES = (
    "关联审批单",
    "Asociar órdenes de compra",
    "Asociar ordenes de compra",
    "órdenes de compra",
    "ordenes de compra",
)
PURCHASE_APPROVAL_KEYWORDS = (
    "采购支出",
    "采购",
    "gastosdecompra",
    "gastoscompra",
    "ordendecompra",
    "ordenesdecompra",
)
ATTACHMENT_FIELD_ALIASES = (
    "附件",
    "Adjunto",
    "物品清单",
    "运费报价",
    "Packing",
    "Packing List",
    "Factura",
    "Invoice",
)
ATTACHMENT_FILE_ID_KEYS = ("fileId", "file_id", "fileID", "mediaId", "media_id", "downloadId", "id")
ATTACHMENT_FILE_NAME_KEYS = ("fileName", "file_name", "filename", "name", "title")
ATTACHMENT_FILE_URL_KEYS = ("fileUrl", "file_url", "downloadUrl", "download_url", "url", "previewUrl", "preview_url")
ATTACHMENT_SPACE_ID_KEYS = ("spaceId", "space_id", "spaceID")
DEFAULT_LOGISTICS_PROCESS_CODE = "PROC-RIYJTXWV-CN52YRK70C5499JG0TJ03-3GSSHZQJ-5"
DEFAULT_FX_RMB_TO_MXN = 2.6
DEFAULT_FX_USD_TO_RMB = round(1 / 0.1393, 6)
MAX_AUDIT_TEXT_LENGTH = 20000
MAX_AI_LOGISTICS_TEXT_LENGTH = 6000
DINGTALK_ENV_FILE_CANDIDATES = (
    "/mnt/e/Yuewei开发/预算管理系统/dingtalk-expense-sync-main/.env",
    "/mnt/e/Yuewei开发/预算管理系统/dingtalk-budget-main/server/.env",
    "/mnt/e/Yuewei开发/dingtalk-expense-sync-main/.env",
    "/mnt/e/Yuewei开发/dingtalk-budget-main/server/.env",
    "E:/Yuewei开发/预算管理系统/dingtalk-expense-sync-main/.env",
    "E:/Yuewei开发/预算管理系统/dingtalk-budget-main/server/.env",
    "E:/Yuewei开发/dingtalk-expense-sync-main/.env",
    "E:/Yuewei开发/dingtalk-budget-main/server/.env",
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _dingtalk_id_value(value: Any) -> str | int:
    text = _clean(value)
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return text
    return text


def load_env_file(env_file: str | None, *, override: bool = False) -> str:
    """加载 .env 文件，但不打印任何敏感值。"""

    path_text = _clean(env_file)
    if not path_text:
        return ""
    path = Path(path_text).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"未找到 .env 文件：{path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value
        if key == "DINGTALK_APPKEY" and (override or "DINGTALK_APP_KEY" not in os.environ):
            os.environ["DINGTALK_APP_KEY"] = value
        if key == "DINGTALK_APPSECRET" and (override or "DINGTALK_APP_SECRET" not in os.environ):
            os.environ["DINGTALK_APP_SECRET"] = value
    return str(path)


def resolve_dingtalk_env_file(env_file: str | None = None) -> str:
    """定位钉钉配置文件，优先使用显式路径，再找预算系统里的 .env。"""

    explicit = _clean(env_file) or _clean(os.environ.get("DINGTALK_ENV_FILE"))
    if explicit:
        return explicit
    for candidate in DINGTALK_ENV_FILE_CANDIDATES:
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return ""


def _runtime_config_value(*keys: str, default: str = "") -> str:
    """读取运行时配置：环境变量优先，其次 Frappe site_config。"""

    for key in keys:
        value = os.environ.get(key)
        if _has_value(value):
            return _clean(value)

    conf = getattr(frappe, "conf", None) if frappe is not None else None
    if conf:
        for key in keys:
            candidates = (key, key.lower())
            for candidate in candidates:
                value = conf.get(candidate) if hasattr(conf, "get") else None
                if _has_value(value):
                    return _clean(value)
    return default


def _runtime_config_int(*keys: str, default: int = 0) -> int:
    value = _runtime_config_value(*keys)
    if not _has_value(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _runtime_config_bool(*keys: str, default: bool = False) -> bool:
    value = _runtime_config_value(*keys)
    if not _has_value(value):
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "开启", "启用")


def _has_dingtalk_pull_credentials() -> bool:
    if _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"):
        return True
    if _runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key") and _runtime_config_value(
        "DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"
    ):
        return True
    return bool(
        _runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id")
        and _runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id")
        and _runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret")
    )


def _preload_env_file_from_argv(argv: list[str]) -> str:
    env_file = _clean(os.environ.get("DINGTALK_ENV_FILE"))
    for index, arg in enumerate(argv):
        if arg == "--env-file" and index + 1 < len(argv):
            env_file = argv[index + 1]
            break
        if arg.startswith("--env-file="):
            env_file = arg.split("=", 1)[1]
            break
    return load_env_file(env_file) if env_file else ""


def resolve_logistics_process_code(process_code: str | None = "") -> str:
    """解析国际物流流程号。

    预算系统 .env 里的 DINGTALK_PROCESS_CODE 可能是预算审批流，不能当成本模块的默认值。
    """

    return _clean(process_code) or _runtime_config_value(
        "DINGTALK_LOGISTICS_PROCESS_CODE",
        "overseas_costing_dingtalk_logistics_process_code",
        default=DEFAULT_LOGISTICS_PROCESS_CODE,
    )


def resolve_purchase_process_code(process_code: str | None = "") -> str:
    """解析采购支出流程号。

    采购支出流程没有安全默认值，必须显式传入或配置环境变量，避免误把预算/其它审批流当采购来源。
    """

    process_codes = _parse_json_text(
        _runtime_config_value("DINGTALK_PROCESS_CODES", "overseas_costing_dingtalk_process_codes")
    )
    purchase_code_from_list = ""
    if isinstance(process_codes, list) and len(process_codes) > 1:
        purchase_code_from_list = _clean(process_codes[1])

    return (
        _clean(process_code)
        or _runtime_config_value("DINGTALK_PURCHASE_PROCESS_CODE", "overseas_costing_dingtalk_purchase_process_code")
        or _runtime_config_value(
            "DINGTALK_PURCHASE_EXPENSE_PROCESS_CODE",
            "overseas_costing_dingtalk_purchase_expense_process_code",
        )
        or purchase_code_from_list
    )


def _api_url() -> str:
    return (_clean(os.environ.get("DINGTALK_API_URL")) or "https://api.dingtalk.com").rstrip("/")


def _oapi_url() -> str:
    return (_clean(os.environ.get("DINGTALK_OAPI_URL")) or "https://oapi.dingtalk.com").rstrip("/")


def _resolve_api_style(api_style: str = "auto") -> str:
    requested = (
        _clean(api_style)
        or _runtime_config_value("DINGTALK_API_STYLE", "overseas_costing_dingtalk_api_style", default="auto")
        or "auto"
    ).lower()
    if requested in ("legacy", "old"):
        return "legacy"
    if requested == "new":
        return "new"
    if requested != "auto":
        raise ValueError(f"不支持的钉钉接口风格：{api_style}")

    has_new = bool(
        _runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id")
        and _runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id")
    )
    has_legacy = bool(
        _runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key")
        and _runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret")
    )
    if has_legacy:
        return "legacy"
    if has_new:
        return "new"
    return "legacy"


def _normalize_key(value: Any) -> str:
    text = _clean(value).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _parse_datetime_ms(value: str, *, end_of_day: bool = False) -> int:
    text = _clean(value)
    if not text:
        raise ValueError("缺少时间参数。")
    if text.isdigit():
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000

    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d")
    parsed: datetime | None = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        parsed = datetime.fromisoformat(text)
    if end_of_day and parsed.time() == dt_time.min:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(parsed.timestamp() * 1000)


def _normalize_transport_mode(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    upper = text.upper()
    if upper in TRANSPORT_MODE_LABELS:
        return upper
    normalized = _normalize_key(text).upper()
    for mode, keywords in TRANSPORT_MODE_KEYWORDS.items():
        if any(_normalize_key(keyword).upper() in normalized for keyword in keywords):
            return mode
    return upper if upper in TRANSPORT_MODE_LABELS else ""


def _parse_transport_modes(value: Any, *, default: tuple[str, ...] = ("SEA",)) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_values = re.split(r"[,，/、\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]
    modes: list[str] = []
    for raw_value in raw_values:
        text = _clean(raw_value)
        if not text:
            continue
        if text.upper() in ("ALL", "*", "全部"):
            return tuple(TRANSPORT_MODE_LABELS)
        mode = _normalize_transport_mode(text)
        if mode and mode not in modes:
            modes.append(mode)
    return tuple(modes) if modes else default


def _iter_time_chunks(start_time_ms: int, end_time_ms: int, chunk_days: int = 30) -> list[tuple[int, int]]:
    if end_time_ms < start_time_ms:
        raise ValueError("结束时间不能早于开始时间。")
    if chunk_days <= 0:
        return [(start_time_ms, end_time_ms)]

    chunks: list[tuple[int, int]] = []
    chunk_ms = chunk_days * 24 * 60 * 60 * 1000
    cursor = start_time_ms
    while cursor <= end_time_ms:
        chunk_end = min(cursor + chunk_ms - 1, end_time_ms)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + 1
    return chunks


def _request_json(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    api_style: str = "new",
    payload: dict | None = None,
    timeout: int = 30,
    retry: int = 2,
) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if token and api_style == "new":
        headers["x-acs-dingtalk-access-token"] = token
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(retry + 1):
        try:
            request = Request(url, data=data, headers=headers, method=method)
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"钉钉接口 HTTP {error.code}：{body}")
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < retry:
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"钉钉接口请求失败：{last_error}") from last_error


def get_access_token(
    *,
    api_style: str = "auto",
    access_token: str = "",
    corp_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    app_key: str = "",
    app_secret: str = "",
) -> str:
    """读取或换取钉钉 access_token。

    优先级：
    1. 显式传入或环境变量中的 DINGTALK_ACCESS_TOKEN
    2. 新版 OpenAPI：corp_id + client_id + client_secret
    3. 旧版 OpenAPI：app_key + app_secret
    """

    token = _clean(access_token) or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token")
    if token:
        return token

    resolved_api_style = _resolve_api_style(api_style)

    if resolved_api_style == "legacy":
        resolved_app_key = _clean(app_key) or _runtime_config_value(
            "DINGTALK_APP_KEY",
            "DINGTALK_APPKEY",
            "overseas_costing_dingtalk_app_key",
        )
        resolved_app_secret = _clean(app_secret) or _runtime_config_value(
            "DINGTALK_APP_SECRET",
            "DINGTALK_APPSECRET",
            "overseas_costing_dingtalk_app_secret",
        )
        if not resolved_app_key or not resolved_app_secret:
            raise ValueError("旧版钉钉接口需要 DINGTALK_APP_KEY 和 DINGTALK_APP_SECRET。")
        query = urlencode({"appkey": resolved_app_key, "appsecret": resolved_app_secret})
        result = _request_json(f"{_oapi_url()}{LEGACY_TOKEN_PATH}?{query}", api_style="legacy")
        _ensure_dingtalk_success(result, api_style="legacy")
        return _clean(result.get("access_token"))

    resolved_corp_id = _clean(corp_id) or _runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id")
    resolved_client_id = _clean(client_id) or _runtime_config_value(
        "DINGTALK_CLIENT_ID",
        "overseas_costing_dingtalk_client_id",
    ) or _runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key")
    resolved_client_secret = _clean(client_secret) or _runtime_config_value(
        "DINGTALK_CLIENT_SECRET",
        "overseas_costing_dingtalk_client_secret",
    ) or _runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret")
    if not resolved_corp_id or not resolved_client_id or not resolved_client_secret:
        raise ValueError("新版钉钉接口需要 DINGTALK_CORP_ID、DINGTALK_CLIENT_ID、DINGTALK_CLIENT_SECRET。")

    result = _request_json(
        f"{_api_url()}{NEW_TOKEN_PATH.format(corp_id=quote(resolved_corp_id, safe=''))}",
        method="POST",
        payload={
            "grant_type": "client_credentials",
            "client_id": resolved_client_id,
            "client_secret": resolved_client_secret,
        },
    )
    token = _clean(result.get("accessToken") or result.get("access_token"))
    if not token:
        raise RuntimeError(f"新版钉钉 token 响应中没有 accessToken：{result}")
    return token


def _ensure_dingtalk_success(result: dict, *, api_style: str) -> None:
    if api_style == "legacy":
        errcode = result.get("errcode", 0)
        if errcode not in (0, "0", None):
            raise RuntimeError(f"钉钉旧版接口返回失败：{result}")
        return
    code = result.get("code")
    if code not in (None, "", "0", 0):
        raise RuntimeError(f"钉钉新版接口返回失败：{result}")


def list_process_instance_ids(
    *,
    token: str,
    process_code: str,
    start_time_ms: int,
    end_time_ms: int,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
) -> list[str]:
    """分页拉取审批实例 ID。"""

    process_code = _clean(process_code)
    if not process_code:
        raise ValueError("缺少国际物流流程模板 process_code。")
    ids: list[str] = []

    resolved_list_api = _resolve_list_api_mode(list_api, api_style)
    for chunk_start_ms, chunk_end_ms in _iter_time_chunks(start_time_ms, end_time_ms, chunk_days=chunk_days):
        if resolved_list_api in ("old", "both"):
            ids.extend(
                _list_process_instance_ids_by_legacy_api(
                    token=token,
                    process_code=process_code,
                    start_time_ms=chunk_start_ms,
                    end_time_ms=chunk_end_ms,
                    page_size=page_size,
                    max_pages=max_pages,
                )
            )

        if resolved_list_api in ("new", "both"):
            ids.extend(
                _list_process_instance_ids_by_new_api(
                    token=token,
                    process_code=process_code,
                    start_time_ms=chunk_start_ms,
                    end_time_ms=chunk_end_ms,
                    page_size=page_size,
                    max_pages=max_pages,
                )
            )

    return list(dict.fromkeys([item for item in ids if item]))


def _resolve_list_api_mode(list_api: str = "auto", api_style: str = "auto") -> str:
    requested = (
        _clean(list_api)
        or _runtime_config_value("DINGTALK_LIST_API", "overseas_costing_dingtalk_list_api", default="auto")
        or "auto"
    ).lower()
    if requested == "legacy":
        requested = "old"
    if requested in ("old", "new", "both"):
        return requested
    if requested != "auto":
        raise ValueError(f"不支持的钉钉列表接口模式：{list_api}")
    return "old" if _resolve_api_style(api_style) == "legacy" else "new"


def _list_process_instance_ids_by_legacy_api(
    *,
    token: str,
    process_code: str,
    start_time_ms: int,
    end_time_ms: int,
    page_size: int,
    max_pages: int,
) -> list[str]:
    ids: list[str] = []
    cursor = 0
    for _page_no in range(max_pages):
        result = _request_json(
            f"{_oapi_url()}{LEGACY_LIST_INSTANCE_IDS_PATH.format(access_token=quote(token, safe=''))}",
            method="POST",
            api_style="legacy",
            payload={
                "process_code": process_code,
                "start_time": start_time_ms,
                "end_time": end_time_ms,
                "size": min(page_size, 20),
                "cursor": cursor,
            },
        )
        _ensure_dingtalk_success(result, api_style="legacy")
        body = result.get("result") or {}
        ids.extend([_clean(item) for item in body.get("list") or [] if _clean(item)])
        next_cursor = body.get("next_cursor")
        if next_cursor in (None, "", cursor):
            break
        cursor = int(next_cursor)
    return ids


def _list_process_instance_ids_by_new_api(
    *,
    token: str,
    process_code: str,
    start_time_ms: int,
    end_time_ms: int,
    page_size: int,
    max_pages: int,
) -> list[str]:
    ids: list[str] = []
    next_token = ""
    for _page_no in range(max_pages):
        payload = {
            "processCode": process_code,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
            "maxResults": min(page_size, 20),
            "statuses": ["COMPLETED"],
        }
        if next_token:
            payload["nextToken"] = next_token
        result = _request_json(
            f"{_api_url()}{NEW_LIST_INSTANCE_IDS_PATH}",
            method="POST",
            token=token,
            api_style="new",
            payload=payload,
        )
        _ensure_dingtalk_success(result, api_style="new")
        body = _unwrap_result(result)
        ids.extend([_clean(item) for item in _first_list(body, "list", "instanceIds", "processInstanceIds") if _clean(item)])
        next_token = _clean(body.get("nextToken") or body.get("next_token"))
        if not next_token:
            break
    return ids


def get_process_instance_detail(*, token: str, process_instance_id: str, api_style: str = "auto") -> dict:
    """读取单个审批实例详情。"""

    instance_id = _clean(process_instance_id)
    resolved_api_style = _resolve_api_style(api_style)
    if resolved_api_style == "legacy":
        try:
            return _get_process_instance_detail_by_new_api(token=token, process_instance_id=instance_id)
        except Exception:
            return _get_process_instance_detail_by_legacy_api(token=token, process_instance_id=instance_id)

    return _get_process_instance_detail_by_new_api(token=token, process_instance_id=instance_id)


def _is_dingtalk_user_not_exist_response(result: dict) -> bool:
    text = json.dumps(result or {}, ensure_ascii=False)
    return any(marker in text for marker in ("userNotExist", "找不到该用户", "用户不存在"))


def _configured_attachment_union_id() -> str:
    for key in ("DINGTALK_ATTACHMENT_UNION_ID", "DINGTALK_DOWNLOAD_UNION_ID"):
        value = _clean(os.environ.get(key))
        if value:
            return value
    return ""


def _legacy_user_union_id(*, token: str, user_id: str) -> str:
    configured_union_id = _configured_attachment_union_id()
    if configured_union_id:
        return configured_union_id

    resolved_user_id = _clean(user_id)
    if not resolved_user_id:
        raise RuntimeError("钉钉附件备用下载链路缺少下载人 userId。")

    result = _request_json(
        f"{_oapi_url()}{LEGACY_USER_DETAIL_PATH.format(access_token=quote(token, safe=''))}",
        method="POST",
        api_style="legacy",
        payload={"userid": resolved_user_id, "language": "zh_CN"},
    )
    if result.get("errcode") in (88, "88") or "qyapi_get_member" in json.dumps(result, ensure_ascii=False):
        raise RuntimeError(
            "钉钉附件备用下载需要应用开通 qyapi_get_member 权限，或在 .env 配置 DINGTALK_ATTACHMENT_UNION_ID。"
        )
    _ensure_dingtalk_success(result, api_style="legacy")
    body = _unwrap_result(result)
    union_id = _clean(body.get("unionid") or body.get("unionId"))
    if not union_id:
        raise RuntimeError("钉钉用户详情响应中没有 unionId，无法继续下载审批附件。")
    return union_id


def _legacy_process_attachment_space_id(
    *,
    token: str,
    process_instance_id: str,
    file_id: str,
    user_id: str,
) -> str:
    resolved_user_id = _clean(user_id)
    if not resolved_user_id:
        raise RuntimeError("钉钉附件备用下载链路缺少下载人 userId。")

    result = _request_json(
        f"{_oapi_url()}{LEGACY_APPROVAL_ATTACHMENT_SPACE_PATH.format(access_token=quote(token, safe=''))}",
        method="POST",
        api_style="legacy",
        payload={
            "process_instance_id": process_instance_id,
            "file_id": file_id,
            "user_id": resolved_user_id,
        },
    )
    _ensure_dingtalk_success(result, api_style="legacy")
    body = _unwrap_result(result)
    space_id = _clean(body.get("space_id") or body.get("spaceId"))
    if not space_id:
        raise RuntimeError(f"钉钉审批附件空间响应中没有 space_id：{result}")
    return space_id


def _legacy_process_attachment_dentry_auth(
    *,
    token: str,
    file_id: str,
    space_id: str,
    user_id: str,
) -> dict:
    resolved_file_id = _clean(file_id)
    resolved_space_id = _clean(space_id)
    resolved_user_id = _clean(user_id)
    if not resolved_file_id or not resolved_space_id or not resolved_user_id:
        raise RuntimeError("钉钉旧版附件授权缺少 fileId、spaceId 或 userId。")

    result = _request_json(
        f"{_oapi_url()}{LEGACY_APPROVAL_ATTACHMENT_DENTRY_AUTH_PATH.format(access_token=quote(token, safe=''))}",
        method="POST",
        api_style="legacy",
        payload={
            "request": {
                "file_infos": [
                    {
                        "file_id": _dingtalk_id_value(resolved_file_id),
                        "space_id": _dingtalk_id_value(resolved_space_id),
                    }
                ],
                "userid": resolved_user_id,
            }
        },
    )
    _ensure_dingtalk_success(result, api_style="legacy")
    return result


def _legacy_process_attachment_file_url(
    *,
    token: str,
    process_instance_id: str,
    file_id: str,
) -> dict:
    resolved_instance_id = _clean(process_instance_id)
    resolved_file_id = _clean(file_id)
    if not resolved_instance_id or not resolved_file_id:
        raise RuntimeError("钉钉旧版附件下载缺少审批实例 ID 或 fileId。")
    return _request_json(
        f"{_oapi_url()}{LEGACY_APPROVAL_ATTACHMENT_DOWNLOAD_PATH.format(access_token=quote(token, safe=''))}",
        method="POST",
        api_style="legacy",
        payload={
            "request": {
                "process_instance_id": resolved_instance_id,
                "file_id": resolved_file_id,
            },
        },
    )


def _extract_storage_download_info(body: dict) -> tuple[str, dict]:
    download_info = body.get("downloadInfo") or body.get("download_info")
    if isinstance(download_info, dict):
        body = {**body, **download_info}

    header_info = body.get("headerSignatureInfo") or body.get("header_signature_info") or {}
    if not isinstance(header_info, dict):
        header_info = {}

    urls = (
        body.get("resourceUrls")
        or body.get("resource_urls")
        or header_info.get("resourceUrls")
        or header_info.get("resource_urls")
        or []
    )
    download_uri = _clean(
        body.get("downloadUri")
        or body.get("download_uri")
        or body.get("downloadUrl")
        or body.get("download_url")
        or body.get("resourceUrl")
        or body.get("resource_url")
        or body.get("url")
    )
    if not download_uri and isinstance(urls, list) and urls:
        download_uri = _clean(urls[0])

    headers = (
        body.get("headers")
        or body.get("downloadHeaders")
        or body.get("download_headers")
        or header_info.get("headers")
        or header_info.get("downloadHeaders")
        or header_info.get("download_headers")
        or {}
    )
    if not isinstance(headers, dict):
        headers = {}
    return download_uri, {str(key): str(value) for key, value in headers.items() if value not in (None, "")}


def _extract_attachment_download_uri(result: dict) -> str:
    body = _unwrap_result(result)
    return _clean(
        body.get("downloadUri")
        or body.get("download_uri")
        or body.get("downloadUrl")
        or body.get("download_url")
        or body.get("resourceUrl")
        or body.get("resource_url")
        or body.get("url")
    )


def _compact_dingtalk_response(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("errcode", "errmsg", "code", "message", "request_id", "requestId", "success"):
        if key in result:
            compact[key] = result.get(key)
    body = _unwrap_result(result)
    if body and body is not result:
        compact["result_keys"] = sorted(str(key) for key in body.keys())
        if _extract_attachment_download_uri(result):
            compact["download_uri_obtained"] = True
    return compact


def _diagnostic_step(name: str, fn) -> tuple[dict, Any]:
    try:
        value = fn()
    except Exception as exc:
        return {"step": name, "ok": False, "error": str(exc)}, None
    response = value if isinstance(value, dict) else None
    step = {"step": name, "ok": True}
    if response:
        step["response"] = _compact_dingtalk_response(response)
    return step, value


def _storage_dentry_download_info(
    *,
    token: str,
    space_id: str,
    dentry_id: str,
    union_id: str,
) -> tuple[str, dict, dict]:
    query = f"?unionId={quote(union_id, safe='')}" if union_id else ""
    result = _request_json(
        f"{_api_url()}{NEW_STORAGE_DENTRY_DOWNLOAD_INFO_PATH.format(space_id=quote(space_id, safe=''), dentry_id=quote(dentry_id, safe=''))}{query}",
        method="POST",
        token=token,
        api_style="new",
        payload={"option": {"version": 1, "preferIntranet": False}},
    )
    _ensure_dingtalk_success(result, api_style="new")
    body = _unwrap_result(result)
    download_uri, download_headers = _extract_storage_download_info(body)
    if not download_uri:
        raise RuntimeError(f"钉钉钉盘下载信息响应中没有下载地址：{result}")
    return download_uri, download_headers, result


def _extract_storage_thumbnail_info(body: dict, *, dentry_id: str) -> tuple[str, dict]:
    items = (
        body.get("resultItems")
        or body.get("result_items")
        or body.get("items")
        or body.get("list")
        or []
    )
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        items = []

    requested_dentry_id = _clean(dentry_id)
    fallback_item: dict = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_id = _clean(item.get("dentryId") or item.get("dentry_id") or item.get("fileId") or item.get("file_id"))
        if requested_dentry_id and candidate_id and candidate_id != requested_dentry_id:
            fallback_item = fallback_item or item
            continue
        thumbnail = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else item
        url = _clean(
            thumbnail.get("url")
            or thumbnail.get("downloadUrl")
            or thumbnail.get("download_url")
            or thumbnail.get("resourceUrl")
            or thumbnail.get("resource_url")
        )
        if url:
            return url, item
        fallback_item = fallback_item or item

    thumbnail = fallback_item.get("thumbnail") if isinstance(fallback_item.get("thumbnail"), dict) else fallback_item
    url = _clean(
        thumbnail.get("url")
        or thumbnail.get("downloadUrl")
        or thumbnail.get("download_url")
        or thumbnail.get("resourceUrl")
        or thumbnail.get("resource_url")
    )
    if url:
        return url, fallback_item
    raise RuntimeError("钉钉缩略图响应中没有可下载的 thumbnail.url。")


def _storage_dentry_thumbnail_info(
    *,
    token: str,
    space_id: str,
    dentry_id: str,
    union_id: str,
) -> tuple[str, dict, dict]:
    resolved_dentry_id = _clean(dentry_id)
    if not resolved_dentry_id:
        raise RuntimeError("钉钉缩略图下载缺少 dentryId。")
    query = f"?unionId={quote(union_id, safe='')}" if union_id else ""
    result = _request_json(
        f"{_api_url()}{NEW_STORAGE_THUMBNAILS_QUERY_PATH.format(space_id=quote(space_id, safe=''))}{query}",
        method="POST",
        token=token,
        api_style="new",
        payload={
            "dentryIds": [resolved_dentry_id],
            "thumbnailOptions": {"size": "large"},
        },
    )
    _ensure_dingtalk_success(result, api_style="new")
    body = _unwrap_result(result)
    thumbnail_uri, thumbnail_item = _extract_storage_thumbnail_info(body, dentry_id=resolved_dentry_id)
    return thumbnail_uri, {}, {"raw_response": result, "thumbnail_item": thumbnail_item}


def _new_auth_process_attachment_download(
    *,
    token: str,
    user_id: str,
    space_id: str,
    file_id: str,
) -> dict:
    resolved_user_id = _clean(user_id)
    resolved_space_id = _clean(space_id)
    resolved_file_id = _clean(file_id)
    if not resolved_user_id or not resolved_space_id or not resolved_file_id:
        raise RuntimeError("钉钉新版附件授权下载缺少 userId、spaceId 或 fileId。")
    result = _request_json(
        f"{_api_url()}{NEW_APPROVAL_ATTACHMENT_AUTH_DOWNLOAD_PATH}",
        method="POST",
        token=token,
        api_style="new",
        payload={
            "userId": resolved_user_id,
            "fileInfos": [
                {
                    "spaceId": _dingtalk_id_value(resolved_space_id),
                    "fileId": resolved_file_id,
                }
            ],
        },
    )
    _ensure_dingtalk_success(result, api_style="new")
    return result


def _extract_storage_dentries(body: dict) -> list[dict]:
    for key in ("dentries", "list", "items", "results", "data"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _storage_dentry_identity(row: dict) -> tuple[str, str]:
    dentry_id = _clean(
        row.get("dentryId")
        or row.get("dentry_id")
        or row.get("fileId")
        or row.get("file_id")
        or row.get("id")
    )
    file_name = _clean(
        row.get("name")
        or row.get("fileName")
        or row.get("file_name")
        or row.get("title")
    )
    return dentry_id, file_name


def _list_storage_dentries(
    *,
    token: str,
    space_id: str,
    union_id: str,
) -> tuple[list[dict], dict]:
    query = urlencode({"parentId": "0", "maxResults": 100, "unionId": union_id})
    result = _request_json(
        f"{_api_url()}{NEW_STORAGE_DENTRY_LIST_PATH.format(space_id=quote(space_id, safe=''))}?{query}",
        method="GET",
        token=token,
        api_style="new",
    )
    _ensure_dingtalk_success(result, api_style="new")
    body = _unwrap_result(result)
    return _extract_storage_dentries(body), result


def _resolve_storage_dentry_id(
    *,
    token: str,
    space_id: str,
    union_id: str,
    file_id: str,
    file_name: str,
) -> tuple[str, dict]:
    dentries, result = _list_storage_dentries(token=token, space_id=space_id, union_id=union_id)
    resolved_file_id = _clean(file_id)
    resolved_file_name = _clean(file_name)
    for row in dentries:
        dentry_id, listed_name = _storage_dentry_identity(row)
        if resolved_file_id and dentry_id == resolved_file_id:
            return dentry_id, result
        if resolved_file_name and listed_name == resolved_file_name:
            return dentry_id, result
    if resolved_file_name:
        normalized_target = _normalize_key(resolved_file_name)
        for row in dentries:
            dentry_id, listed_name = _storage_dentry_identity(row)
            if normalized_target and _normalize_key(listed_name) == normalized_target:
                return dentry_id, result
    raise RuntimeError(
        "钉钉已允许读取附件空间文件列表，但没有找到与当前附件文件名匹配的文件。"
    )


def _drive_file_download_info(
    *,
    token: str,
    space_id: str,
    file_id: str,
    union_id: str,
) -> tuple[str, dict, dict]:
    query = f"?unionId={quote(union_id, safe='')}" if union_id else ""
    result = _request_json(
        f"{_api_url()}{NEW_DRIVE_FILE_DOWNLOAD_INFO_PATH.format(space_id=quote(space_id, safe=''), file_id=quote(file_id, safe=''))}{query}",
        method="GET",
        token=token,
        api_style="new",
    )
    _ensure_dingtalk_success(result, api_style="new")
    body = _unwrap_result(result)
    download_uri, download_headers = _extract_storage_download_info(body)
    if not download_uri:
        raise RuntimeError(f"钉钉钉盘文件下载信息响应中没有下载地址：{result}")
    return download_uri, download_headers, result


def _fallback_process_attachment_download_url(
    *,
    legacy_token: str,
    process_instance_id: str,
    file_id: str,
    file_name: str = "",
    user_id: str,
    corp_id: str,
) -> dict:
    space_id = _legacy_process_attachment_space_id(
        token=legacy_token,
        process_instance_id=process_instance_id,
        file_id=file_id,
        user_id=user_id,
    )
    legacy_auth_result = {}
    legacy_auth_error = ""
    try:
        legacy_auth_result = _legacy_process_attachment_dentry_auth(
            token=legacy_token,
            file_id=file_id,
            space_id=space_id,
            user_id=user_id,
        )
        legacy_download_result = _legacy_process_attachment_file_url(
            token=legacy_token,
            process_instance_id=process_instance_id,
            file_id=file_id,
        )
        _ensure_dingtalk_success(legacy_download_result, api_style="legacy")
        legacy_download_uri = _extract_attachment_download_uri(legacy_download_result)
        if legacy_download_uri:
            return {
                "space_id": space_id,
                "union_id_obtained": False,
                "download_uri": legacy_download_uri,
                "download_headers": {},
                "fallback_api": "legacy_dentry_auth_then_file_url",
                "storage_response": {
                    "legacy_auth_response": legacy_auth_result,
                    "download_response": legacy_download_result,
                },
            }
    except Exception as exc:
        legacy_auth_error = str(exc)

    union_id = _legacy_user_union_id(token=legacy_token, user_id=user_id)
    new_token = get_access_token(api_style="new", corp_id=corp_id)
    auth_result = {}
    auth_error = ""
    try:
        auth_result = _new_auth_process_attachment_download(
            token=new_token,
            user_id=user_id,
            space_id=space_id,
            file_id=file_id,
        )
        direct_result = _request_json(
            f"{_api_url()}{NEW_APPROVAL_ATTACHMENT_DOWNLOAD_PATH}",
            method="POST",
            token=new_token,
            api_style="new",
            payload={
                "processInstanceId": process_instance_id,
                "fileId": file_id,
            },
        )
        _ensure_dingtalk_success(direct_result, api_style="new")
        direct_uri = _extract_attachment_download_uri(direct_result)
        if direct_uri:
            return {
                "space_id": space_id,
                "union_id_obtained": bool(union_id),
                "download_uri": direct_uri,
                "download_headers": {},
                "fallback_api": "new_auth_then_approval_download",
                "storage_response": {
                    "legacy_auth_response": legacy_auth_result,
                    "legacy_auth_error": legacy_auth_error,
                    "auth_response": auth_result,
                    "download_response": direct_result,
                },
            }
    except Exception as exc:
        auth_error = str(exc)
    try:
        download_uri, download_headers, storage_response = _storage_dentry_download_info(
            token=new_token,
            space_id=space_id,
            dentry_id=file_id,
            union_id=union_id,
        )
        fallback_api = "storage_dentry_download_info"
    except Exception as storage_exc:
        try:
            dentry_id, list_response = _resolve_storage_dentry_id(
                token=new_token,
                space_id=space_id,
                union_id=union_id,
                file_id=file_id,
                file_name=file_name,
            )
            download_uri, download_headers, storage_response = _storage_dentry_download_info(
                token=new_token,
                space_id=space_id,
                dentry_id=dentry_id,
                union_id=union_id,
            )
            storage_response = {
                "legacy_auth_response": legacy_auth_result,
                "legacy_auth_error": legacy_auth_error,
                "auth_response": auth_result,
                "auth_error": auth_error,
                "original_storage_error": str(storage_exc),
                "dentry_list_response": list_response,
                "download_response": storage_response,
                "resolved_dentry_id": dentry_id,
            }
            fallback_api = "storage_dentry_list_then_download_info"
        except Exception as list_exc:
            download_uri, download_headers, thumbnail_response = _storage_dentry_thumbnail_info(
                token=new_token,
                space_id=space_id,
                dentry_id=file_id,
                union_id=union_id,
            )
            storage_response = {
                "legacy_auth_response": legacy_auth_result,
                "legacy_auth_error": legacy_auth_error,
                "auth_response": auth_result,
                "auth_error": auth_error,
                "original_storage_error": str(storage_exc),
                "dentry_list_error": str(list_exc),
                "thumbnail_response": thumbnail_response,
            }
            fallback_api = "storage_thumbnail_query"
    return {
        "space_id": space_id,
        "union_id_obtained": bool(union_id),
        "download_uri": download_uri,
        "download_headers": download_headers,
        "fallback_api": fallback_api,
        "storage_response": {
            "legacy_auth_response": legacy_auth_result,
            "legacy_auth_error": legacy_auth_error,
            "auth_response": auth_result,
            "auth_error": auth_error,
            "download_response": storage_response,
        },
    }


def get_process_attachment_download_url(
    *,
    token: str,
    process_instance_id: str,
    file_id: str,
    file_name: str = "",
    space_id: str = "",
    user_id: str = "",
    corp_id: str = "",
    api_style: str = "auto",
) -> dict:
    """换取钉钉审批发起表单附件的临时下载地址。"""

    instance_id = _clean(process_instance_id)
    resolved_file_id = _clean(file_id)
    resolved_space_id = _clean(space_id)
    resolved_user_id = _clean(user_id)
    resolved_corp_id = _clean(corp_id)
    if not instance_id:
        raise ValueError("缺少钉钉审批实例 ID。")
    if not resolved_file_id:
        raise ValueError("缺少钉钉附件 file_id。")

    resolved_api_style = _resolve_api_style(api_style)
    if resolved_api_style == "legacy":
        result = _request_json(
            f"{_oapi_url()}{LEGACY_APPROVAL_ATTACHMENT_DOWNLOAD_PATH.format(access_token=quote(token, safe=''))}",
            method="POST",
            api_style="legacy",
            payload={
                "request": {
                    "process_instance_id": instance_id,
                    "file_id": resolved_file_id,
                },
            },
        )
        if _is_dingtalk_user_not_exist_response(result):
            fallback = _fallback_process_attachment_download_url(
                legacy_token=token,
                process_instance_id=instance_id,
                file_id=resolved_file_id,
                file_name=file_name,
                user_id=resolved_user_id,
                corp_id=resolved_corp_id,
            )
            return {
                "process_instance_id": instance_id,
                "file_id": resolved_file_id,
                "user_id": resolved_user_id,
                "download_uri": fallback["download_uri"],
                "download_headers": fallback.get("download_headers") or {},
                "space_id": fallback.get("space_id") or "",
                "union_id_obtained": fallback.get("union_id_obtained") or False,
                "api_style": resolved_api_style,
                "fallback_api": fallback.get("fallback_api") or "",
                "raw_response": result,
                "storage_response": fallback.get("storage_response") or {},
            }
    else:
        if resolved_space_id and resolved_user_id:
            _new_auth_process_attachment_download(
                token=token,
                user_id=resolved_user_id,
                space_id=resolved_space_id,
                file_id=resolved_file_id,
            )
        result = _request_json(
            f"{_api_url()}{NEW_APPROVAL_ATTACHMENT_DOWNLOAD_PATH}",
            method="POST",
            token=token,
            api_style="new",
            payload={
                "processInstanceId": instance_id,
                "fileId": resolved_file_id,
            },
        )
    _ensure_dingtalk_success(result, api_style=resolved_api_style)
    body = _unwrap_result(result)
    download_uri = _clean(
        body.get("downloadUri")
        or body.get("download_uri")
        or body.get("downloadUrl")
        or body.get("download_url")
        or body.get("url")
    )
    if not download_uri:
        raise RuntimeError(f"钉钉附件下载地址响应中没有 downloadUri：{result}")
    return {
        "process_instance_id": instance_id,
        "file_id": resolved_file_id,
        "space_id": resolved_space_id,
        "user_id": resolved_user_id,
        "download_uri": download_uri,
        "download_headers": {},
        "api_style": resolved_api_style,
        "raw_response": result,
    }


def diagnose_process_attachment_download(
    *,
    token: str,
    process_instance_id: str,
    file_id: str,
    file_name: str = "",
    space_id: str = "",
    user_id: str = "",
    corp_id: str = "",
    api_style: str = "auto",
) -> dict:
    """诊断审批发起附件自动下载链路，不保存文件内容。"""

    instance_id = _clean(process_instance_id)
    resolved_file_id = _clean(file_id)
    resolved_space_id = _clean(space_id)
    resolved_user_id = _clean(user_id)
    resolved_corp_id = _clean(corp_id)
    resolved_api_style = _resolve_api_style(api_style)
    steps: list[dict] = []
    download_uri_obtained = False
    downloaded_by = ""
    storage_response: dict | None = None

    if not instance_id or not resolved_file_id:
        return {
            "ok": False,
            "api_style": resolved_api_style,
            "message": "缺少审批实例 ID 或 fileId，不能诊断附件下载。",
            "steps": steps,
        }

    if resolved_api_style == "legacy":
        legacy_step, legacy_result = _diagnostic_step(
            "legacy_file_url",
            lambda: _legacy_process_attachment_file_url(
                token=token,
                process_instance_id=instance_id,
                file_id=resolved_file_id,
            ),
        )
        steps.append(legacy_step)
        if legacy_result and _extract_attachment_download_uri(legacy_result):
            download_uri_obtained = True
            downloaded_by = "legacy_file_url"

        if not download_uri_obtained and resolved_user_id:
            space_step, space_result = _diagnostic_step(
                "legacy_cspace_info",
                lambda: _request_json(
                    f"{_oapi_url()}{LEGACY_APPROVAL_ATTACHMENT_SPACE_PATH.format(access_token=quote(token, safe=''))}",
                    method="POST",
                    api_style="legacy",
                    payload={
                        "process_instance_id": instance_id,
                        "file_id": resolved_file_id,
                        "user_id": resolved_user_id,
                    },
                ),
            )
            steps.append(space_step)
            if space_result:
                try:
                    _ensure_dingtalk_success(space_result, api_style="legacy")
                    resolved_space_id = _clean(_unwrap_result(space_result).get("space_id") or _unwrap_result(space_result).get("spaceId"))
                except Exception:
                    pass

        if not download_uri_obtained and resolved_space_id and resolved_user_id:
            auth_step, _auth_result = _diagnostic_step(
                "legacy_dentry_auth",
                lambda: _legacy_process_attachment_dentry_auth(
                    token=token,
                    file_id=resolved_file_id,
                    space_id=resolved_space_id,
                    user_id=resolved_user_id,
                ),
            )
            steps.append(auth_step)
            retry_step, retry_result = _diagnostic_step(
                "legacy_file_url_after_auth",
                lambda: _legacy_process_attachment_file_url(
                    token=token,
                    process_instance_id=instance_id,
                    file_id=resolved_file_id,
                ),
            )
            steps.append(retry_step)
            if retry_result and _extract_attachment_download_uri(retry_result):
                download_uri_obtained = True
                downloaded_by = "legacy_dentry_auth_then_file_url"

    if not download_uri_obtained and resolved_user_id:
        union_id = ""
        union_step, union_result = _diagnostic_step(
            "legacy_user_union_id",
            lambda: _request_json(
                f"{_oapi_url()}{LEGACY_USER_DETAIL_PATH.format(access_token=quote(token, safe=''))}",
                method="POST",
                api_style="legacy",
                payload={"userid": resolved_user_id, "language": "zh_CN"},
            ),
        )
        steps.append(union_step)
        if union_result:
            try:
                _ensure_dingtalk_success(union_result, api_style="legacy")
                union_id = _clean(_unwrap_result(union_result).get("unionid") or _unwrap_result(union_result).get("unionId"))
            except Exception:
                union_id = ""

        new_token = ""
        new_token_step, new_token_result = _diagnostic_step(
            "new_access_token",
            lambda: {"result": {"accessToken": get_access_token(api_style="new", corp_id=resolved_corp_id)}},
        )
        steps.append({"step": "new_access_token", "ok": new_token_step["ok"], "token_obtained": bool(new_token_result)})
        if new_token_result:
            new_token = _clean(_unwrap_result(new_token_result).get("accessToken"))

        if new_token and resolved_space_id:
            new_auth_step, _new_auth_result = _diagnostic_step(
                "new_auth_download",
                lambda: _new_auth_process_attachment_download(
                    token=new_token,
                    user_id=resolved_user_id,
                    space_id=resolved_space_id,
                    file_id=resolved_file_id,
                ),
            )
            steps.append(new_auth_step)

            new_download_step, new_download_result = _diagnostic_step(
                "new_approval_download",
                lambda: _request_json(
                    f"{_api_url()}{NEW_APPROVAL_ATTACHMENT_DOWNLOAD_PATH}",
                    method="POST",
                    token=new_token,
                    api_style="new",
                    payload={"processInstanceId": instance_id, "fileId": resolved_file_id},
                ),
            )
            steps.append(new_download_step)
            if new_download_result and _extract_attachment_download_uri(new_download_result):
                download_uri_obtained = True
                downloaded_by = "new_auth_then_approval_download"

            if not download_uri_obtained and union_id:
                storage_step, storage_result = _diagnostic_step(
                    "storage_dentry_download_info",
                    lambda: _request_json(
                        f"{_api_url()}{NEW_STORAGE_DENTRY_DOWNLOAD_INFO_PATH.format(space_id=quote(resolved_space_id, safe=''), dentry_id=quote(resolved_file_id, safe=''))}?unionId={quote(union_id, safe='')}",
                        method="POST",
                        token=new_token,
                        api_style="new",
                        payload={"option": {"version": 1, "preferIntranet": False}},
                    ),
                )
                steps.append(storage_step)
                storage_response = storage_result if isinstance(storage_result, dict) else None
                if storage_result:
                    uri, _headers = _extract_storage_download_info(_unwrap_result(storage_result))
                    if uri:
                        download_uri_obtained = True
                        downloaded_by = "storage_dentry_download_info"

    return {
        "ok": download_uri_obtained,
        "api_style": resolved_api_style,
        "process_instance_id": instance_id,
        "file_id": resolved_file_id,
        "file_name": file_name,
        "space_id": resolved_space_id,
        "user_id_configured": bool(resolved_user_id),
        "download_uri_obtained": download_uri_obtained,
        "downloaded_by": downloaded_by,
        "storage_response": _compact_dingtalk_response(storage_response),
        "steps": steps,
    }


def _get_process_instance_detail_by_legacy_api(*, token: str, process_instance_id: str) -> dict:
    result = _request_json(
        f"{_oapi_url()}{LEGACY_INSTANCE_DETAIL_PATH.format(access_token=quote(token, safe=''))}",
        method="POST",
        api_style="legacy",
        payload={"process_instance_id": process_instance_id},
    )
    _ensure_dingtalk_success(result, api_style="legacy")
    process_instance = result.get("process_instance") or result.get("result", {}).get("process_instance") or result.get("result") or result
    return _normalize_legacy_instance(process_instance, process_instance_id)


def _get_process_instance_detail_by_new_api(*, token: str, process_instance_id: str) -> dict:
    result = _request_json(
        f"{_api_url()}{NEW_INSTANCE_DETAIL_PATH.format(process_instance_id=quote(process_instance_id, safe=''))}",
        method="GET",
        token=token,
        api_style="new",
    )
    _ensure_dingtalk_success(result, api_style="new")
    return _unwrap_result(result)


def _normalize_legacy_instance(instance: dict, process_instance_id: str) -> dict:
    if not isinstance(instance, dict):
        return {"processInstanceId": process_instance_id}

    mapping = {
        "process_instance_id": "processInstanceId",
        "business_id": "businessId",
        "originator_userid": "originatorUserId",
        "originator_dept_id": "originatorDeptId",
        "form_component_values": "formComponentValues",
        "create_time": "createTime",
        "finish_time": "finishTime",
    }
    normalized = dict(instance)
    for old_key, new_key in mapping.items():
        if old_key in normalized and new_key not in normalized:
            normalized[new_key] = normalized[old_key]
    normalized.setdefault("processInstanceId", process_instance_id)
    return normalized


def _unwrap_result(result: dict) -> dict:
    for key in ("result", "data", "processInstance"):
        value = result.get(key)
        if isinstance(value, dict):
            return value
    return result


def _first_list(source: dict, *keys: str) -> list:
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            return value
    return []


def _get_form_components(instance: dict) -> list:
    components = (
        instance.get("form_component_values")
        or instance.get("formComponentValues")
        or instance.get("form_component_values_v2")
        or []
    )
    if isinstance(components, str):
        components = _parse_json_text(components)
    return components if isinstance(components, list) else []


def _iter_form_components(instance: dict):
    stack = list(reversed(_get_form_components(instance)))
    while stack:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        yield component
        for key in ("details", "children", "items"):
            children = component.get(key)
            if isinstance(children, str):
                children = _parse_json_text(children)
            if isinstance(children, list):
                stack.extend(reversed(children))


def extract_form_fields(instance: dict) -> dict[str, Any]:
    """把钉钉表单组件拍平成字段字典。"""

    fields: dict[str, Any] = {}

    def visit(component: Any) -> None:
        if not isinstance(component, dict):
            return
        name = _clean(
            component.get("name")
            or component.get("label")
            or component.get("bizAlias")
            or component.get("componentName")
            or component.get("id")
        )
        value = _parse_json_text(component.get("value"))
        ext_value = _parse_json_text(component.get("ext_value") or component.get("extValue"))
        if name:
            resolved_value = value if value not in (None, "") else ext_value
            if _field_matches_alias(name, BUSINESS_ENTITY_FIELD_ALIASES):
                ext_entity = _extract_dingtalk_entity_value(ext_value)
                value_entity = _extract_dingtalk_entity_value(value)
                if ext_entity.get("name"):
                    resolved_value = ext_value
                elif value_entity.get("name"):
                    resolved_value = value
            if name not in fields or fields[name] in (None, ""):
                fields[name] = resolved_value
        for key in ("details", "children", "items"):
            children = component.get(key)
            if isinstance(children, str):
                children = _parse_json_text(children)
            if isinstance(children, list):
                for child in children:
                    visit(child)
        for row in _iter_detail_rows(value):
            for row_key, row_value in row.items():
                if row_key and row_key not in fields:
                    fields[row_key] = row_value

    for component in _get_form_components(instance):
        visit(component)
    return fields


def _iter_detail_rows(value: Any):
    parsed = _parse_json_text(value)
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                yield from _flatten_detail_row(item)
    elif isinstance(parsed, dict):
        yield from _flatten_detail_row(parsed)


def _flatten_detail_row(row: dict) -> list[dict]:
    flattened: dict[str, Any] = {}
    for key, value in row.items():
        parsed_value = _parse_json_text(value)
        if isinstance(parsed_value, dict):
            name = _clean(parsed_value.get("name") or parsed_value.get("label") or key)
            cell_value = parsed_value.get("value")
            flattened[name] = cell_value if cell_value not in (None, "") else parsed_value.get("extValue")
        else:
            flattened[_clean(key)] = parsed_value
    return [flattened] if flattened else []


def _find_field_value(fields: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key, value in fields.items():
        if _field_matches_alias(key, aliases):
            if value not in (None, ""):
                return value
    return ""


def _find_field_entry(fields: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str, Any]:
    for key, value in fields.items():
        if _field_matches_alias(key, aliases):
            if value not in (None, ""):
                return key, value
    return "", ""


def _field_matches_alias(fieldname: Any, aliases: tuple[str, ...]) -> bool:
    normalized_fieldname = _normalize_key(fieldname)
    normalized_aliases = [_normalize_key(alias) for alias in aliases]
    return any(alias and alias in normalized_fieldname for alias in normalized_aliases)


def _extract_dingtalk_entity_value(value: Any) -> dict[str, str]:
    parsed = _parse_json_text(value)
    if isinstance(parsed, list):
        for item in parsed:
            entity = _extract_dingtalk_entity_value(item)
            if entity.get("name") or entity.get("id"):
                return entity
        return {"name": "", "id": ""}
    if isinstance(parsed, dict):
        for key in ("selectedOptions", "selected_options", "options", "items", "list", "data"):
            nested_value = parsed.get(key)
            if isinstance(nested_value, str):
                nested_value = _parse_json_text(nested_value)
            if isinstance(nested_value, (list, dict)):
                nested_entity = _extract_dingtalk_entity_value(nested_value)
                if nested_entity.get("name") or nested_entity.get("id"):
                    return nested_entity
        name = _clean(
            parsed.get("deptName")
            or parsed.get("name")
            or parsed.get("label")
            or parsed.get("displayName")
            or parsed.get("displayValue")
            or parsed.get("optionName")
            or parsed.get("orgName")
            or parsed.get("corpName")
            or parsed.get("companyName")
            or parsed.get("businessName")
            or parsed.get("title")
            or parsed.get("text")
            or parsed.get("value")
        )
        entity_id = _clean(
            parsed.get("itemId")
            or parsed.get("deptId")
            or parsed.get("id")
            or parsed.get("value")
        )
        return {"name": name, "id": entity_id}
    text = _clean(parsed)
    return {"name": text, "id": ""}


def _extract_subsidiary_from_form_components(components: Any) -> dict[str, str]:
    if not isinstance(components, list):
        return {"subsidiary_code": "", "business_entity_name": "", "business_entity_id": "", "source_field": "", "source": ""}

    stack = list(reversed(components))
    while stack:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        for child_key in ("details", "children", "items"):
            children = component.get(child_key)
            if isinstance(children, str):
                children = _parse_json_text(children)
            if isinstance(children, list):
                stack.extend(reversed(children))
        source_field = _clean(
            component.get("name")
            or component.get("label")
            or component.get("bizAlias")
            or component.get("componentName")
            or component.get("id")
        )
        component_type = _clean(component.get("componentType") or component.get("component_type")).lower()
        value = component.get("value")
        ext_value = component.get("ext_value") or component.get("extValue")
        raw_value = ext_value if ext_value not in (None, "") else value
        entity = _extract_dingtalk_entity_value(raw_value)
        if not (entity.get("name") or entity.get("id")):
            continue

        if _field_matches_alias(source_field, BUSINESS_ENTITY_FIELD_ALIASES):
            name = entity.get("name") or entity.get("id") or ""
        elif component_type in {"departmentfield", "deptfield", "organizationfield", "companyfield"}:
            name = entity.get("name") or entity.get("id") or ""
        else:
            continue

        if not name:
            continue
        return {
            "subsidiary_code": name,
            "business_entity_name": entity.get("name") or "",
            "business_entity_id": entity.get("id") or "",
            "source_field": source_field,
            "source": "dingtalk_form_business_entity" if source_field else "",
        }

    return {"subsidiary_code": "", "business_entity_name": "", "business_entity_id": "", "source_field": "", "source": ""}


def extract_subsidiary_from_approval(item: dict) -> dict[str, str]:
    """从钉钉表单提取归属子公司/业务主体，当前直接使用中文主体名称。"""

    form_fields = item.get("form_fields") or {}
    source_field, raw_value = _find_field_entry(form_fields, BUSINESS_ENTITY_FIELD_ALIASES)
    entity = _extract_dingtalk_entity_value(raw_value)
    name = entity.get("name") or entity.get("id") or ""
    if not name:
        raw_components = item.get("raw_form_components") or item.get("form_component_values") or item.get("formComponentValues") or []
        fallback = _extract_subsidiary_from_form_components(raw_components)
        if fallback.get("subsidiary_code"):
            return fallback
    return {
        "subsidiary_code": name,
        "business_entity_name": entity.get("name") or "",
        "business_entity_id": entity.get("id") or "",
        "source_field": source_field,
        "source": "dingtalk_form_business_entity" if source_field else "",
    }


def _component_name_matches_business_entity(name: Any) -> bool:
    normalized = _normalize_key(name)
    if not normalized:
        return False
    extra_tokens = ("empresa", "entidad", "businessentity", "company", "公司", "主体")
    return _field_matches_alias(name, BUSINESS_ENTITY_FIELD_ALIASES) or any(token in normalized for token in extra_tokens)


def _collect_business_entity_debug_candidates(item: dict, *, max_count: int = 12) -> list[dict]:
    candidates: list[dict] = []
    form_fields = item.get("form_fields") or {}
    for fieldname, value in form_fields.items():
        if not _component_name_matches_business_entity(fieldname):
            continue
        entity = _extract_dingtalk_entity_value(value)
        candidates.append(
            {
                "source": "form_fields",
                "field": _clean(fieldname),
                "entity_name": entity.get("name") or "",
                "entity_id": entity.get("id") or "",
                "raw_type": type(value).__name__,
                "raw_preview": _clean(value)[:160],
            }
        )
        if len(candidates) >= max_count:
            return candidates

    stack = list(reversed(item.get("raw_form_components") or item.get("form_component_values") or item.get("formComponentValues") or []))
    while stack and len(candidates) < max_count:
        component = stack.pop()
        if not isinstance(component, dict):
            continue
        for child_key in ("details", "children", "items"):
            children = component.get(child_key)
            if isinstance(children, str):
                children = _parse_json_text(children)
            if isinstance(children, list):
                stack.extend(reversed(children))
        name = _clean(
            component.get("name")
            or component.get("label")
            or component.get("bizAlias")
            or component.get("componentName")
            or component.get("id")
        )
        component_type = _clean(component.get("componentType") or component.get("component_type"))
        if not _component_name_matches_business_entity(name) and _clean(component_type).lower() not in {
            "departmentfield",
            "deptfield",
            "organizationfield",
            "companyfield",
        }:
            continue
        raw_value = component.get("ext_value") or component.get("extValue") or component.get("value")
        entity = _extract_dingtalk_entity_value(raw_value)
        candidates.append(
            {
                "source": "raw_form_components",
                "field": name,
                "component_type": component_type,
                "entity_name": entity.get("name") or "",
                "entity_id": entity.get("id") or "",
                "raw_type": type(raw_value).__name__,
                "raw_preview": _clean(raw_value)[:160],
            }
        )
    return candidates


def _normalize_currency_code(value: Any) -> str:
    normalized = _normalize_key(value)
    if not normalized:
        return ""
    if any(token in normalized for token in ("rmb", "cny", "人民币", "renminbi")):
        return "RMB"
    if any(token in normalized for token in ("usd", "dólar", "dolar", "dolares", "dólares", "美元", "美金")):
        return "USD"
    if any(token in normalized for token in ("mxn", "peso", "pesos", "比索", "墨西哥")):
        return "MXN"
    return ""


def _normalize_allocation_basis(value: Any) -> str:
    text = _normalize_key(value)
    if text in {"goods_value", "gross_weight", "volume", "chargeable_weight"}:
        return text
    if text in {"货值", "按货值", "按货值分摊"} or "货值" in text:
        return "goods_value"
    if text in {"计费重", "计费重量", "体积重", "按计费重", "按计费重量", "按计费重分摊"} or "计费重" in text:
        return "chargeable_weight"
    if text in {"体积", "方数", "按体积", "按方数", "按体积分摊"} or "体积" in text or "方数" in text:
        return "volume"
    if text in {"毛重", "重量", "按毛重", "按重量", "按毛重分摊", "按重量分摊"} or "毛重" in text or "重量" in text:
        return "gross_weight"
    return "gross_weight"


def _parse_money_amount(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None

    text = _clean(value).replace("，", ",")
    if not text:
        return None

    candidates: list[tuple[int, int, float]] = []
    for match in re.finditer(r"[-+]?\d[\d,]*(?:\.\d+)?", text):
        raw_number = match.group(0).replace(",", "")
        try:
            number = float(raw_number)
        except ValueError:
            continue
        if number <= 0:
            continue

        before = text[max(0, match.start() - 12) : match.start()].lower()
        after = text[match.end() : match.end() + 12].lower()
        if re.match(r"\s*(hq|gp|kg|kgs|cbm|m3|pcs|pc|件|个|箱|柜|天|day)", after):
            continue
        score = 1
        if _normalize_currency_code(f"{before}{after}") or any(symbol in before + after for symbol in ("$", "￥", "¥")):
            score = 3
        candidates.append((score, -match.start(), number))

    if not candidates:
        return None
    return max(candidates)[2]


def extract_logistics_fee_from_approval(item: dict) -> dict:
    """只提取明确填写的物流费用，报价说明不能直接入账。"""

    form_fields = item.get("form_fields") or {}
    currency_field, currency_raw = _find_field_entry(form_fields, LOGISTICS_CURRENCY_FIELD_ALIASES)
    explicit_currency = _normalize_currency_code(currency_raw)
    source_field, raw_value = _find_field_entry(form_fields, LOGISTICS_FEE_FIELD_ALIASES)
    amount = _parse_money_amount(raw_value)
    if amount is None:
        return {}
    currency = _normalize_currency_code(raw_value) or explicit_currency or "RMB"
    return {
        "amount": amount,
        "currency": currency,
        "source_label": "物流费用",
        "source_field": source_field,
        "source_value": raw_value,
        "currency_field": currency_field,
        "currency_value": currency_raw,
    }


def _parse_quote_total_amount(value: Any) -> float | None:
    """报价合计行优先取等号后的总额，否则取最后一个金额。"""

    text = _clean(value).replace("，", ",")
    if not text:
        return None
    numbers = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if not numbers:
        return None
    if "=" in text:
        after_equals = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", text.rsplit("=", 1)[1])
        if after_equals:
            numbers = after_equals
    try:
        amount = float(numbers[-1].replace(",", ""))
    except ValueError:
        return None
    return amount if amount > 0 else None


def _looks_like_quote_amount_line(line: str) -> bool:
    """识别物流报价里的金额行，避免把重量、日期、型号误当成费用。"""

    text = _clean(line)
    if not text:
        return False
    if re.search(r"(?:合计|总计|总费用|总价)", text, re.IGNORECASE):
        return True
    if "=" not in text:
        return False
    if not re.search(r"(?:元|rmb|cny|¥|￥|usd|美金|美元|mxn|peso|比索)", text, re.IGNORECASE):
        return False
    return bool(re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text.rsplit("=", 1)[1]))


def _parse_direct_quote_line(line: str) -> dict | None:
    """识别“飞力达PIL：5850USD/40HQ+杂费”这类报价比较行。"""

    text = _clean(line)
    if not text:
        return None
    match = re.search(
        r"^(?P<carrier>.+?)[:：]\s*(?P<amount>[-+]?\d[\d,]*(?:\.\d+)?)\s*(?P<currency>usd|美金|美元|rmb|cny|元|mxn|peso|比索)(?P<tail>.*)$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    carrier = _clean(match.group("carrier")).strip("：:")
    if not carrier or len(carrier) > 40:
        return None
    if any(skip in carrier for skip in ("合计", "总计", "总费用", "总价", "单价", "每kg", "每KG", "运费", "卸货费", "装货费", "仓租", "免租期", "超期")):
        return None
    try:
        amount = float(match.group("amount").replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None
    return {
        "carrier": carrier,
        "amount": amount,
        "currency": _normalize_currency_code(match.group("currency")) or _normalize_currency_code(text) or "RMB",
        "remark": _clean(match.group("tail")),
    }


def extract_logistics_quote_candidates_from_approval(item: dict) -> list[dict]:
    """从物流报价文字中提取待确认候选，不生成任何费用分摊。"""

    form_fields = item.get("form_fields") or {}
    source_field, raw_value = _find_field_entry(form_fields, LOGISTICS_QUOTE_FIELD_ALIASES)
    text = _clean(raw_value)
    if not source_field or not text:
        return []

    volume_match = re.search(r"(?:预估方数|体积)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:方|立方|cbm|m3)", text, re.IGNORECASE)
    volume_m3 = float(volume_match.group(1)) if volume_match else None
    candidates: list[dict] = []
    carrier = ""
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _clean(raw_line)
        if not line:
            continue
        carrier_match = re.search(r"^\s*(?:\d+\s*[.、]?\s*)?(.+?)报价", line)
        if carrier_match:
            carrier = _clean(carrier_match.group(1)).strip("：:")
        direct_quote = _parse_direct_quote_line(line)
        if direct_quote:
            candidates.append(
                {
                    "carrier": direct_quote["carrier"],
                    "amount": direct_quote["amount"],
                    "currency": direct_quote["currency"],
                    "volume_m3": volume_m3,
                    "source_field": source_field,
                    "source_value": text,
                    "evidence_line": line,
                    "evidence_line_no": line_no,
                    "status": "待确认",
                    "remark": direct_quote.get("remark") or "",
                }
            )
            continue
        if not _looks_like_quote_amount_line(line):
            continue
        amount = _parse_quote_total_amount(line)
        if amount is None:
            continue
        candidates.append(
            {
                "carrier": carrier,
                "amount": amount,
                "currency": _normalize_currency_code(line) or "RMB",
                "volume_m3": volume_m3,
                "source_field": source_field,
                "source_value": text,
                "evidence_line": line,
                "evidence_line_no": line_no,
                "status": "待确认",
            }
        )
    return candidates


def _build_logistics_ai_source_text(form_fields: dict[str, Any]) -> str:
    """把审批正文的普通字段整理给 AI 兜底识别，避开附件/明细表等大块数据。"""

    lines: list[str] = []
    for fieldname, value in (form_fields or {}).items():
        if isinstance(value, (dict, list)):
            continue
        text = _clean(value)
        if not text:
            continue
        text = re.sub(r"\n{3,}", "\n\n", text)
        if len(text) > 1200:
            text = f"{text[:1200]}..."
        lines.append(f"{_clean(fieldname)}: {text}")
    return "\n".join(lines)[:MAX_AI_LOGISTICS_TEXT_LENGTH]


def _should_ai_parse_logistics_text(base_summary: dict, source_text: str) -> bool:
    if not source_text or not _runtime_config_bool(
        "OVERSEAS_COST_AI_TEXT_PARSE_ENABLED",
        "overseas_cost_ai_text_parse_enabled",
        default=True,
    ):
        return False
    has_quote_marker = bool(re.search(r"(报价|运费|物流费|quote|cotizaci|dhl|fedex|ups|合计|总计)", source_text, re.IGNORECASE))
    has_logistics_marker = bool(
        re.search(r"(物流方式|camino|重量|peso|预计发货|pre[- ]?entrega|目标地区|destinat|目的地)", source_text, re.IGNORECASE)
    )
    if not (has_quote_marker or has_logistics_marker):
        return False
    missing_quote = not base_summary.get("logistics_quote_amount") and has_quote_marker
    missing_core = not any(
        base_summary.get(key)
        for key in ("transport_mode", "gross_weight_kg", "pre_delivery_date", "destination", "logistics_no")
    )
    return missing_quote or missing_core


def _call_ai_logistics_text_summary(source_text: str, base_summary: dict) -> dict:
    """调用现有 DeepSeek/OpenAI 兼容配置，兜底识别审批正文基础字段。"""

    try:
        from overseas_costing.services import allocation_service

        config = allocation_service._ai_config()
        if not config.get("api_key"):
            return {}
        messages = [
            {
                "role": "system",
                "content": (
                    "你是钉钉国际物流审批正文的基础字段识别助手。"
                    "只能从用户提供的原文中抽取字段，不得猜测、不得改写物料明细、不得新增费用。"
                    "输出必须是 JSON 对象；没有明确值就返回空字符串或 null。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "从审批正文中识别整票物流基础信息。报价金额只取最终总额，不取每kg单价。",
                        "output_schema": {
                            "transport_mode": "SEA/AIR/EXPRESS 或空",
                            "transport_mode_raw": "原文中的物流方式",
                            "logistics_no": "柜号、运单号或单号",
                            "pre_delivery_date": "预计发货日期，保持原文日期即可",
                            "destination": "目标地区/目的地",
                            "gross_weight_kg": "整票重量KG，数字",
                            "logistics_quote_amount": "物流报价最终总金额，数字",
                            "logistics_quote_currency": "RMB/USD/MXN",
                            "logistics_quote_carrier": "承运商/货代，例如 DHL",
                            "logistics_quote_evidence": "能证明报价金额的原文短句",
                            "confidence": "0-1 数字",
                            "reason": "一句中文说明",
                        },
                        "already_parsed_by_rules": base_summary,
                        "approval_text": source_text,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
        content = allocation_service._call_chat_completions(config, messages)
        parsed = allocation_service._extract_json_object(content)
        if not isinstance(parsed, dict):
            return {}
        return _normalize_ai_logistics_text_summary(parsed, config.get("model"))
    except Exception as exc:
        return {"ai_used": False, "ai_error": str(exc)[:240]}


def _normalize_ai_logistics_text_summary(parsed: dict, model: str | None = "") -> dict:
    mode_raw = _clean(parsed.get("transport_mode_raw") or parsed.get("transport_mode"))
    amount = _parse_money_amount(parsed.get("logistics_quote_amount"))
    weight = _to_number_or_none(parsed.get("gross_weight_kg"))
    confidence = _to_number_or_none(parsed.get("confidence"))
    return {
        "transport_mode": detect_approval_transport_mode(parsed.get("transport_mode") or mode_raw),
        "transport_mode_raw": mode_raw,
        "logistics_no": _clean(parsed.get("logistics_no")),
        "pre_delivery_date": _clean(parsed.get("pre_delivery_date")),
        "destination": _clean(parsed.get("destination")),
        "gross_weight_kg": weight,
        "logistics_quote_amount": amount,
        "logistics_quote_currency": _normalize_currency_code(parsed.get("logistics_quote_currency")) if parsed.get("logistics_quote_currency") else "",
        "logistics_quote_carrier": _clean(parsed.get("logistics_quote_carrier")),
        "logistics_quote_evidence": _clean(parsed.get("logistics_quote_evidence")),
        "ai_used": True,
        "ai_model": _clean(model),
        "ai_confidence": confidence,
        "ai_reason": _clean(parsed.get("reason")),
    }


def _merge_ai_logistics_text_summary(base_summary: dict, ai_summary: dict) -> dict:
    if not ai_summary:
        return base_summary

    merged = dict(base_summary)
    changed = False
    fill_fields = (
        "transport_mode",
        "transport_mode_raw",
        "logistics_no",
        "pre_delivery_date",
        "destination",
        "gross_weight_kg",
        "logistics_quote_amount",
        "logistics_quote_currency",
        "logistics_quote_carrier",
        "logistics_quote_evidence",
    )
    for fieldname in fill_fields:
        current = merged.get(fieldname)
        candidate = ai_summary.get(fieldname)
        if current not in (None, "") or candidate in (None, ""):
            continue
        merged[fieldname] = candidate
        changed = True

    if changed:
        merged["ai_used"] = bool(ai_summary.get("ai_used"))
        merged["ai_model"] = ai_summary.get("ai_model") or ""
        merged["ai_confidence"] = ai_summary.get("ai_confidence")
        merged["ai_reason"] = ai_summary.get("ai_reason") or ""
    elif ai_summary.get("ai_error"):
        merged["ai_error"] = ai_summary.get("ai_error")
    return merged


def extract_logistics_text_summary_from_approval(item: dict) -> dict:
    """提取钉钉国际物流审批正文里的整票基础信息。"""

    form_fields = item.get("form_fields") or {}
    quote_field, quote_text = _find_field_entry(form_fields, LOGISTICS_QUOTE_FIELD_ALIASES)
    pre_delivery_field, pre_delivery_date = _find_field_entry(form_fields, LOGISTICS_PRE_DELIVERY_FIELD_ALIASES)
    destination_field, destination = _find_field_entry(form_fields, LOGISTICS_DESTINATION_FIELD_ALIASES)
    weight_field, weight_value = _find_field_entry(form_fields, LOGISTICS_WEIGHT_FIELD_ALIASES)
    transport_mode_raw = item.get("transport_mode_raw") or _find_field_value(form_fields, TRANSPORT_FIELD_ALIASES)
    logistics_no = item.get("logistics_no") or _find_field_value(form_fields, BATCH_NO_FIELD_ALIASES)

    quote_candidates = item.get("logistics_quote_candidates")
    if not isinstance(quote_candidates, list):
        quote_candidates = extract_logistics_quote_candidates_from_approval(item)
    first_quote = quote_candidates[0] if quote_candidates else {}

    summary = {
        "transport_mode": detect_approval_transport_mode(transport_mode_raw),
        "transport_mode_raw": _clean(transport_mode_raw),
        "logistics_no": _clean(logistics_no),
        "pre_delivery_date": _clean(pre_delivery_date),
        "pre_delivery_field": pre_delivery_field,
        "destination": _clean(destination),
        "destination_field": destination_field,
        "gross_weight_kg": _to_number_or_none(weight_value),
        "gross_weight_field": weight_field,
        "logistics_quote_field": quote_field,
        "logistics_quote_text": _clean(quote_text),
        "logistics_quote_amount": first_quote.get("amount"),
        "logistics_quote_currency": first_quote.get("currency"),
        "logistics_quote_carrier": first_quote.get("carrier"),
        "logistics_quote_evidence": first_quote.get("evidence_line"),
    }
    source_text = _build_logistics_ai_source_text(form_fields)
    if _should_ai_parse_logistics_text(summary, source_text):
        summary = _merge_ai_logistics_text_summary(
            summary,
            _call_ai_logistics_text_summary(source_text, summary),
        )
    return summary


def _find_component_value(instance: dict, aliases: tuple[str, ...]) -> Any:
    normalized_aliases = [_normalize_key(alias) for alias in aliases]
    for component in _iter_form_components(instance):
        name = _clean(
            component.get("name")
            or component.get("label")
            or component.get("bizAlias")
            or component.get("componentName")
            or component.get("id")
        )
        normalized_name = _normalize_key(name)
        if not any(alias and alias in normalized_name for alias in normalized_aliases):
            continue
        value = _parse_json_text(component.get("value"))
        if value not in (None, ""):
            return value
        ext_value = _parse_json_text(component.get("ext_value") or component.get("extValue"))
        if ext_value not in (None, ""):
            return ext_value
    return ""


def _is_purchase_relate_component(component: dict) -> bool:
    component_type = _clean(component.get("componentType") or component.get("component_type"))
    name = _clean(
        component.get("name")
        or component.get("label")
        or component.get("bizAlias")
        or component.get("componentName")
        or component.get("id")
    )
    normalized_name = _normalize_key(name)
    if component_type == "RelateField":
        return any(_normalize_key(alias) in normalized_name for alias in PURCHASE_RELATE_FIELD_ALIASES)
    return any(_normalize_key(alias) in normalized_name for alias in PURCHASE_RELATE_FIELD_ALIASES)


def _relation_display_values(component: dict) -> list[str]:
    value = _parse_json_text(component.get("value"))
    if isinstance(value, list):
        display_values: list[str] = []
        for item in value:
            if isinstance(item, dict):
                display_values.append(
                    _clean(
                        item.get("title")
                        or item.get("processInstanceTitle")
                        or item.get("name")
                        or item.get("label")
                        or item.get("value")
                    )
                )
            else:
                display_values.append(_clean(item))
        return display_values
    text = _clean(value)
    return [text] if text else []


def _looks_like_linked_approval_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        _clean(value.get(key))
        for key in (
            "businessId",
            "business_id",
            "bizId",
            "approvalNo",
            "approval_no",
            "procInstId",
            "processInstanceId",
            "process_instance_id",
            "instanceId",
            "instance_id",
            "url",
            "detailUrl",
            "officialUrl",
        )
    )


def _iter_linked_approval_payloads(value: Any):
    parsed = _parse_json_text(value)
    if isinstance(parsed, dict):
        if _looks_like_linked_approval_payload(parsed):
            yield parsed
        for child in parsed.values():
            yield from _iter_linked_approval_payloads(child)
    elif isinstance(parsed, list):
        for child in parsed:
            yield from _iter_linked_approval_payloads(child)


def _relation_ext_items(component: dict) -> list:
    ext_value = _parse_json_text(component.get("ext_value") or component.get("extValue"))
    nested_items = list(_iter_linked_approval_payloads(ext_value))
    if nested_items:
        return nested_items
    if isinstance(ext_value, dict):
        for key in ("list", "items", "data", "value"):
            value = ext_value.get(key)
            if isinstance(value, str):
                value = _parse_json_text(value)
            if isinstance(value, list):
                return value
        return [ext_value]
    if isinstance(ext_value, list):
        return ext_value
    return []


def _build_linked_approval_record(component: dict, raw_item: Any, display_name: str = "") -> dict:
    if not isinstance(raw_item, dict):
        return {}

    official_url = _clean(raw_item.get("url") or raw_item.get("detailUrl") or raw_item.get("officialUrl"))
    approval_no = _clean(
        raw_item.get("businessId")
        or raw_item.get("business_id")
        or raw_item.get("bizId")
        or raw_item.get("approvalNo")
        or raw_item.get("approval_no")
    )
    instance_id = _clean(
        raw_item.get("procInstId")
        or raw_item.get("processInstanceId")
        or raw_item.get("process_instance_id")
        or raw_item.get("instanceId")
        or raw_item.get("instance_id")
    )
    if not instance_id:
        instance_id = extract_dingtalk_instance_id(official_url)
    title = _clean(raw_item.get("title") or raw_item.get("processInstanceTitle") or raw_item.get("name") or display_name)
    if not approval_no and not instance_id and not official_url:
        return {}

    payload = build_dingtalk_order_payload(
        approval_no=approval_no,
        instance_id=instance_id,
        official_url=official_url,
    )
    source_field = _clean(component.get("name") or component.get("label") or component.get("id"))
    return {
        "approval_no": approval_no,
        "source_approval_no": approval_no,
        "source_instance_id": instance_id,
        "business_id": approval_no,
        "proc_inst_id": instance_id,
        "title": title,
        "display_name": display_name or title,
        "source_field": source_field,
        "source_dingtalk_url": official_url,
        "open_url": payload.get("open_url") or "",
    }


def _has_purchase_approval_keyword(*values: Any) -> bool:
    normalized_text = _normalize_key(" ".join(_clean(value) for value in values if value not in (None, "")))
    return any(keyword in normalized_text for keyword in PURCHASE_APPROVAL_KEYWORDS)


def extract_linked_purchase_approvals(instance: dict) -> list[dict]:
    """从国际物流 OA 的关联审批控件里提取采购支出审批编号和实例 ID。"""

    approvals: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_record(component: dict, raw_item: Any, display_name: str = "", *, require_keyword: bool = False) -> None:
        record = _build_linked_approval_record(component, raw_item, display_name=display_name)
        if not record:
            return
        if require_keyword and not _has_purchase_approval_keyword(
            record.get("title"),
            record.get("display_name"),
            record.get("source_field"),
            raw_item.get("title") if isinstance(raw_item, dict) else "",
            raw_item.get("processInstanceTitle") if isinstance(raw_item, dict) else "",
        ):
            return
        key = (
            record.get("approval_no", ""),
            record.get("source_instance_id", ""),
            "" if (record.get("approval_no") or record.get("source_instance_id")) else record.get("display_name", ""),
        )
        if key in seen:
            return
        seen.add(key)
        approvals.append(record)

    for component in _iter_form_components(instance):
        if not _is_purchase_relate_component(component):
            continue
        display_values = _relation_display_values(component)
        for index, raw_item in enumerate(_relation_ext_items(component)):
            display_name = display_values[index] if index < len(display_values) else ""
            add_record(component, raw_item, display_name=display_name)

    for raw_item in _iter_linked_approval_payloads(instance):
        add_record({}, raw_item, require_keyword=True)
    return approvals


def _first_dict_value(source: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return ""


def _looks_like_attachment_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    has_file_name = any(_clean(value.get(key)) for key in ATTACHMENT_FILE_NAME_KEYS)
    if not has_file_name:
        return False
    return any(
        _clean(value.get(key))
        for key in (
            *ATTACHMENT_FILE_ID_KEYS,
            *ATTACHMENT_FILE_URL_KEYS,
            *ATTACHMENT_SPACE_ID_KEYS,
            "fileSize",
            "file_size",
            "size",
            "extension",
            "fileType",
            "file_type",
        )
    ) or any(key in value for key in ("fileName", "file_name"))


def _file_extension(file_name: str, payload: dict | None = None) -> str:
    payload = payload or {}
    explicit = _clean(payload.get("extension") or payload.get("fileType") or payload.get("file_type"))
    if explicit:
        return explicit.lower().lstrip(".")
    suffix = Path(file_name).suffix.lower().lstrip(".")
    return suffix


def _guess_oa_attachment_type(file_name: str, payload: dict | None = None) -> str:
    normalized_name = _normalize_key(file_name)
    extension = _file_extension(file_name, payload)
    if any(keyword in normalized_name for keyword in ("完税", "税单", "pedimento", "taxcertificate")):
        return "Tax Certificate"
    if any(keyword in normalized_name for keyword in ("发票", "invoice", "factura")):
        return "Commercial Invoice"
    if any(keyword in normalized_name for keyword in ("装箱", "装柜", "物品清单", "packing", "packinglist", "清单")):
        return "Packing List"
    if any(keyword in normalized_name for keyword in ("运费", "物流", "报价", "燃油", "dhl", "fedex", "ups", "bill")):
        return "Logistics Bill"
    if extension in {"xls", "xlsx", "csv"}:
        return "Packing List"
    return "Other"


def _build_attachment_record(
    payload: dict,
    *,
    source_field: str = "",
    component_type: str = "",
    value_source: str = "",
) -> dict:
    file_name = _clean(_first_dict_value(payload, ATTACHMENT_FILE_NAME_KEYS))
    file_id = _clean(_first_dict_value(payload, ATTACHMENT_FILE_ID_KEYS))
    file_url = _clean(_first_dict_value(payload, ATTACHMENT_FILE_URL_KEYS))
    space_id = _clean(_first_dict_value(payload, ATTACHMENT_SPACE_ID_KEYS))
    file_size = _first_dict_value(payload, ("fileSize", "file_size", "size"))
    extension = _file_extension(file_name, payload)
    attachment_type = _guess_oa_attachment_type(file_name, payload)
    return {
        "source": "oa_form_attachment",
        "source_field": source_field,
        "component_type": component_type,
        "value_source": value_source,
        "file_id": file_id,
        "space_id": space_id,
        "file_name": file_name,
        "file_url": file_url,
        "file_size": file_size,
        "file_ext": extension,
        "attachment_type": attachment_type,
        "raw": payload,
    }


def _extract_attachments_from_value(
    value: Any,
    *,
    source_field: str = "",
    component_type: str = "",
    value_source: str = "",
) -> list[dict]:
    parsed = _parse_json_text(value)
    if isinstance(parsed, dict):
        records: list[dict] = []
        if _looks_like_attachment_payload(parsed):
            records.append(
                _build_attachment_record(
                    parsed,
                    source_field=source_field,
                    component_type=component_type,
                    value_source=value_source,
                )
            )
        for child in parsed.values():
            records.extend(
                _extract_attachments_from_value(
                    child,
                    source_field=source_field,
                    component_type=component_type,
                    value_source=value_source,
                )
            )
        return records
    if isinstance(parsed, list):
        records: list[dict] = []
        for child in parsed:
            records.extend(
                _extract_attachments_from_value(
                    child,
                    source_field=source_field,
                    component_type=component_type,
                    value_source=value_source,
                )
            )
        return records
    return []


def _dedupe_attachment_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        file_name = _clean(record.get("file_name"))
        file_id = _clean(record.get("file_id"))
        file_url = _clean(record.get("file_url"))
        source_field = _clean(record.get("source_field"))
        if not file_name and not file_id and not file_url:
            continue
        key = (file_id, file_url, file_name, source_field)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def extract_form_attachments(instance: dict) -> list[dict]:
    """只从审批发起表单字段提取附件；评论附件暂不纳入。"""

    records: list[dict] = []
    for component in _iter_form_components(instance):
        source_field = _clean(
            component.get("name")
            or component.get("label")
            or component.get("bizAlias")
            or component.get("componentName")
            or component.get("id")
        )
        component_type = _clean(component.get("componentType") or component.get("component_type"))
        if component_type and "attachment" not in component_type.lower():
            continue
        records.extend(
            _extract_attachments_from_value(
                component.get("value"),
                source_field=source_field,
                component_type=component_type,
                value_source="value",
            )
        )
        records.extend(
            _extract_attachments_from_value(
                component.get("ext_value") or component.get("extValue"),
                source_field=source_field,
                component_type=component_type,
                value_source="extValue",
            )
        )
    return _dedupe_attachment_records(records)


def extract_attachments_from_form_fields(form_fields: dict[str, Any]) -> list[dict]:
    """从已拍平的表单字段中兜底提取附件清单。"""

    records: list[dict] = []
    normalized_aliases = tuple(_normalize_key(alias) for alias in ATTACHMENT_FIELD_ALIASES)
    for fieldname, value in (form_fields or {}).items():
        normalized_fieldname = _normalize_key(fieldname)
        if normalized_fieldname and not any(alias in normalized_fieldname for alias in normalized_aliases):
            continue
        records.extend(
            _extract_attachments_from_value(
                value,
                source_field=_clean(fieldname),
                component_type="",
                value_source="form_fields",
            )
        )
    return _dedupe_attachment_records(records)


def is_sea_approval(fields: dict[str, Any], *, sea_keywords: tuple[str, ...] = DEFAULT_SEA_KEYWORDS) -> bool:
    transport_value = _find_field_value(fields, TRANSPORT_FIELD_ALIASES)
    detected = detect_approval_transport_mode(transport_value)
    if detected:
        return detected == "SEA"
    normalized = _normalize_key(transport_value).upper()
    return any(_normalize_key(keyword).upper() in normalized for keyword in sea_keywords)


def detect_approval_transport_mode(fields_or_value: Any) -> str:
    if isinstance(fields_or_value, dict):
        fields_or_value = _find_field_value(fields_or_value, TRANSPORT_FIELD_ALIASES)
    return _normalize_transport_mode(fields_or_value)


def is_transport_approval(fields: dict[str, Any], transport_modes: tuple[str, ...]) -> bool:
    mode = detect_approval_transport_mode(fields)
    return bool(mode and mode in transport_modes)


def is_hidden_approval_status(status: str | None) -> bool:
    """钉钉已撤销/终止审批不进入成本表格。"""

    normalized = _clean(status).upper()
    if not normalized:
        return False
    return any(_clean(hidden).upper() in normalized for hidden in HIDDEN_APPROVAL_STATUSES)


def is_completed_approval_status(status: str | None, *, allow_empty: bool = True) -> bool:
    """判断审批是否已完成；空状态默认放行以兼容部分旧接口响应。"""

    normalized = _clean(status).upper()
    if not normalized:
        return allow_empty
    if is_hidden_approval_status(normalized):
        return False
    return any(_clean(completed).upper() in normalized for completed in COMPLETED_APPROVAL_STATUSES)


def summarize_approval(instance: dict, *, process_instance_id: str = "", include_raw: bool = False) -> dict:
    """整理成系统可回溯的最小审批摘要。"""

    fields = extract_form_fields(instance)
    linked_purchase_approvals = extract_linked_purchase_approvals(instance)
    oa_form_attachments = extract_form_attachments(instance)
    instance_id = (
        _clean(process_instance_id)
        or _clean(instance.get("process_instance_id"))
        or _clean(instance.get("processInstanceId"))
        or extract_dingtalk_instance_id(instance.get("url"))
    )
    approval_no = _clean(
        instance.get("business_id")
        or instance.get("businessId")
        or instance.get("bizId")
        or instance.get("approval_no")
    )
    official_url = _clean(instance.get("url") or instance.get("detailUrl") or instance.get("officialUrl"))
    dingtalk_payload = build_dingtalk_order_payload(
        approval_no=approval_no,
        instance_id=instance_id,
        official_url=official_url,
    )
    transport_mode_raw = _find_field_value(fields, TRANSPORT_FIELD_ALIASES)
    summary = {
        "source_instance_id": instance_id,
        "source_approval_no": approval_no,
        "source_dingtalk_url": official_url,
        "open_url": dingtalk_payload.get("open_url") or "",
        "approval_title": _clean(instance.get("title") or instance.get("process_instance_title") or instance.get("processInstanceTitle")),
        "approval_status": _clean(instance.get("status") or instance.get("approvalStatus")),
        "originator_userid": _clean(instance.get("originator_userid") or instance.get("originatorUserId")),
        "originator_dept_id": _clean(instance.get("originator_dept_id") or instance.get("originatorDeptId")),
        "create_time": instance.get("create_time") or instance.get("createTime") or "",
        "finish_time": instance.get("finish_time") or instance.get("finishTime") or "",
        "transport_mode": detect_approval_transport_mode(transport_mode_raw),
        "transport_mode_raw": transport_mode_raw,
        "logistics_no": _find_field_value(fields, BATCH_NO_FIELD_ALIASES),
        "linked_purchase_count": len(linked_purchase_approvals),
        "linked_purchase_approvals": linked_purchase_approvals,
        "oa_form_attachment_count": len(oa_form_attachments),
        "oa_form_attachments": oa_form_attachments,
        "raw_form_components": _get_form_components(instance),
        "form_fields": fields,
    }
    summary["logistics_fee"] = extract_logistics_fee_from_approval(summary)
    summary["logistics_quote_candidates"] = extract_logistics_quote_candidates_from_approval(summary)
    summary["logistics_text_summary"] = extract_logistics_text_summary_from_approval(summary)
    if include_raw:
        summary["raw_instance"] = instance
    return summary


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _compact_extra_json_for_audit(value: Any) -> dict:
    data = _json_loads_dict(value)
    if not data:
        return {"has_value": bool(_clean(value))}

    trace = data.get("oa_logistics_trace") if isinstance(data.get("oa_logistics_trace"), dict) else data
    linked_approvals = trace.get("linked_purchase_approvals") if isinstance(trace, dict) else []
    linked_approvals = linked_approvals or []
    form_attachments = trace.get("oa_form_attachments") if isinstance(trace, dict) else []
    form_attachments = form_attachments or []
    return {
        "source": data.get("source"),
        "has_form_fields": bool(trace.get("form_fields")) if isinstance(trace, dict) else False,
        "oa_form_attachment_count": len(form_attachments) if isinstance(form_attachments, list) else 0,
        "linked_purchase_count": len(linked_approvals) if isinstance(linked_approvals, list) else 0,
        "linked_purchase_approval_nos": [
            linked.get("approval_no") or linked.get("source_approval_no")
            for linked in linked_approvals
            if isinstance(linked, dict) and (linked.get("approval_no") or linked.get("source_approval_no"))
        ],
    }


def _compact_for_audit(value: Any) -> Any:
    if isinstance(value, dict):
        compacted = {}
        for key, item in value.items():
            if key == "extra_json":
                compacted[key] = _compact_extra_json_for_audit(item)
            else:
                compacted[key] = _compact_for_audit(item)
        return compacted
    if isinstance(value, list):
        return [_compact_for_audit(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 1000:
        return f"{value[:1000]}...<已截断，原长度 {len(value)}>"
    return value


def _json_dumps_for_audit(value: Any) -> str:
    text = json.dumps(_compact_for_audit(value), ensure_ascii=True, default=str)
    if len(text) > MAX_AUDIT_TEXT_LENGTH:
        return f"{text[:MAX_AUDIT_TEXT_LENGTH]}...<已截断，原长度 {len(text)}>"
    return text


def _json_loads_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    text = _clean(value)
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _merge_oa_extra_json(old_value: Any, new_value: Any) -> str:
    old_data = _json_loads_dict(old_value)
    new_data = _json_loads_dict(new_value)
    if not old_data:
        return _json_dumps(new_data) if new_data else _clean(new_value)
    if not new_data:
        return _json_dumps(old_data)

    if old_data.get("source") == "dingtalk_oa_logistics":
        merged = {**old_data, **new_data}
    else:
        merged = dict(old_data)
        merged["oa_logistics_trace"] = {
            "source": new_data.get("source"),
            "transport_mode_raw": new_data.get("transport_mode_raw"),
            "open_url": new_data.get("open_url"),
            "logistics_fee": new_data.get("logistics_fee") or {},
            "logistics_quote_candidates": new_data.get("logistics_quote_candidates") or [],
            "linked_purchase_approvals": new_data.get("linked_purchase_approvals") or [],
            "oa_form_attachments": new_data.get("oa_form_attachments") or [],
            "form_fields": new_data.get("form_fields") or {},
        }
    return _json_dumps(merged)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            if not isinstance(value, str) or value.strip():
                return value
    return ""


def _to_frappe_datetime(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    if text.isdigit():
        number = int(text)
        timestamp = number / 1000 if number > 10_000_000_000 else number
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text


def _has_value(value: Any) -> bool:
    return value not in (None, "")


def _values_match(old_value: Any, new_value: Any) -> bool:
    if old_value in (None, "") and new_value in (None, ""):
        return True
    if isinstance(old_value, datetime):
        old_text = old_value.strftime("%Y-%m-%d %H:%M:%S")
    else:
        old_text = _clean(old_value)
    if isinstance(new_value, datetime):
        new_text = new_value.strftime("%Y-%m-%d %H:%M:%S")
    else:
        new_text = _clean(new_value)
    return old_text == new_text


def _looks_like_container_no(value: Any) -> bool:
    text = _clean(value).replace(" ", "").upper()
    return bool(re.match(r"^[A-Z]{3,4}\d{6,8}$", text))


def _count_dingtalk_attachments(value: Any) -> int:
    parsed = _parse_json_text(value)
    if isinstance(parsed, dict):
        count = 1 if parsed.get("fileId") and parsed.get("fileName") else 0
        return count + sum(_count_dingtalk_attachments(item) for item in parsed.values())
    if isinstance(parsed, list):
        return sum(_count_dingtalk_attachments(item) for item in parsed)
    return 0


def _is_goods_table_field(fieldname: Any) -> bool:
    normalized = _normalize_key(fieldname)
    return any(_normalize_key(alias) in normalized for alias in GOODS_TABLE_FIELD_ALIASES)


def _flatten_dingtalk_table_row(row: Any) -> dict:
    if not isinstance(row, dict):
        return {}
    row_value = _parse_json_text(row.get("rowValue") or row.get("row_value") or row.get("value") or row)
    if isinstance(row_value, dict):
        row_value = row_value.get("rowValue") or row_value.get("row_value") or row_value
    flattened: dict[str, Any] = {}
    if isinstance(row_value, list):
        for cell in row_value:
            if not isinstance(cell, dict):
                continue
            label = _clean(cell.get("label") or cell.get("name") or cell.get("key"))
            value = cell.get("value")
            if label:
                flattened[label] = value
    elif isinstance(row_value, dict):
        for key, value in row_value.items():
            if isinstance(value, dict):
                label = _clean(value.get("label") or value.get("name") or key)
                flattened[label] = value.get("value")
            else:
                flattened[_clean(key)] = value
    if row.get("rowNumber") or row.get("row_number"):
        flattened["_dingtalk_row_number"] = row.get("rowNumber") or row.get("row_number")
    return {key: value for key, value in flattened.items() if key and value not in (None, "")}


def _is_oa_goods_placeholder_row(row: dict) -> bool:
    material_code = _clean(
        row.get("物料编码 Código de material")
        or row.get("物料编码")
        or row.get("material_code")
    )
    product_name = _clean(
        row.get("物料名称（中文）Nombre del material (chino)")
        or row.get("物料名称（中文）")
        or row.get("物料名称")
        or row.get("产品名称")
    )
    quantity = row.get("数量Cantidad") or row.get("数量") or row.get("quantity")
    placeholder_markers = {
        "物料编码",
        "品目编码",
        "物料名称",
        "物料名称中文",
        "产品名称",
        "规格型号",
        "数量",
        "单位",
        "收货人",
        "收件人",
    }
    if material_code in placeholder_markers:
        return True
    if product_name in placeholder_markers and _to_number_or_none(quantity) in (None, 0):
        return True
    values = [_clean(value) for value in row.values()]
    marker_count = sum(1 for value in values if value in placeholder_markers)
    return marker_count >= 3


def _parse_oa_goods_text_rows(value: Any) -> list[dict]:
    """解析普通文本填写的货物信息，兼容“编码-名称-数量pcs”格式。"""

    text = _clean(value)
    if not text:
        return []

    rows: list[dict] = []
    quantity_pattern = re.compile(
        r"^(?P<body>.+?)\s*(?:[-－—]+\s*)?(?P<quantity>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>pcs?|pieces?|pzas?|piezas?|件|个|箱|袋|套|卷|支|台|片|kg|kgs|公斤|千克|吨|m3|cbm|方)\s*$",
        re.IGNORECASE,
    )
    material_code_pattern = re.compile(
        r"^(?P<material_code>[A-Za-z][A-Za-z0-9]*\d[A-Za-z0-9]*)\s*[-－—]\s*(?P<product_name>.+)$"
    )

    for raw_line in re.split(r"[\r\n;；]+", text):
        line = re.sub(r"^\s*(?:\d+[.、)）]\s*)?[-*•]+\s*", "", _clean(raw_line))
        if not line:
            continue
        if re.match(r"^(?:合计|总计|共计|总数|总重量|重量|体积|总体积)", line, re.IGNORECASE):
            continue

        quantity_match = quantity_pattern.match(line)
        if not quantity_match:
            continue

        body = _clean(quantity_match.group("body")).rstrip("-－— ")
        if not body:
            continue
        code_match = material_code_pattern.match(body)
        row = {
            "product_name": _clean(code_match.group("product_name")) if code_match else body,
            "quantity": quantity_match.group("quantity"),
            "unit": normalize_unit(quantity_match.group("unit")),
            "_oa_goods_source": "text",
        }
        if code_match:
            row["material_code"] = _clean(code_match.group("material_code"))
        rows.append(row)
    return rows


def extract_oa_goods_rows(item: dict) -> list[dict]:
    """从钉钉国际物流审批摘要中提取货物信息表格或文本行。"""

    form_fields = item.get("form_fields") or {}
    goods_value = None
    for fieldname, value in form_fields.items():
        if _is_goods_table_field(fieldname):
            goods_value = value
            break
    goods_table = _parse_json_text(goods_value)
    if isinstance(goods_table, list):
        raw_rows = [_flatten_dingtalk_table_row(raw_row) for raw_row in goods_table]
    elif isinstance(goods_value, str):
        raw_rows = _parse_oa_goods_text_rows(goods_value)
    else:
        return []

    common_values = {
        "项目proyecto": form_fields.get("项目proyecto"),
        "物料类别TIPO": form_fields.get("物料类别TIPO"),
        "物流方式Camino Envío": item.get("transport_mode_raw"),
        "柜号/单号Número DE Logística": item.get("logistics_no"),
        "备注otro": form_fields.get("备注otro"),
    }
    rows: list[dict] = []
    for row in raw_rows:
        if not row:
            continue
        if _is_oa_goods_placeholder_row(row):
            continue
        for key, value in common_values.items():
            if value not in (None, "") and key not in row:
                row[key] = value
        rows.append(row)
    return rows


def _to_number_or_none(value: Any):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return value
    text = _clean(value).replace(",", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return value


def _is_purchase_detail_table_field(fieldname: Any) -> bool:
    normalized = _normalize_key(fieldname)
    return any(_normalize_key(alias) in normalized for alias in PURCHASE_DETAIL_TABLE_FIELD_ALIASES)


def _looks_like_purchase_detail_row(row: dict) -> bool:
    normalized_keys = [_normalize_key(key) for key in row]
    return any("物品编码" in key or "codigo" in key for key in normalized_keys) and any(
        "单价" in key or "precio" in key or "总金额" in key or "montototal" in key for key in normalized_keys
    )


def _purchase_text_value(text: str, aliases: tuple[str, ...]) -> str:
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    stop_pattern = (
        r"物品编码|物料编码|品目编码|C[oó]digo|Codigo|Código|SKU|"
        r"物品名称|物料名称|品名|Nombre(?:\s+del\s+art[ií]culo)?|"
        r"物品规格|规格|Especificaci[oó]n|Especificacion|"
        r"数量|Cantidad|Qty|QTY|单位|Unidad|"
        r"单价|Precio|Unit\s*Price|总金额|Monto\s*Total|金额|Total|币种|Moneda"
    )
    match = re.search(
        rf"(?:{alias_pattern})\s*[:：]?\s*(.+?)(?=\s+(?:{stop_pattern})\s*[:：]?|$)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean(match.group(1)) if match else ""


def _purchase_text_number(text: str, aliases: tuple[str, ...]):
    value = _purchase_text_value(text, aliases)
    if not value:
        return None
    match = re.search(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", value)
    return match.group(0) if match else None


def _purchase_text_currency(text: str, default_currency: Any = "") -> str:
    upper = text.upper()
    if any(marker in upper for marker in ("人民币", "RMB", "CNY", "¥")):
        return "人民币RMB"
    if any(marker in upper for marker in ("美元", "USD", "US$")):
        return "美元USD"
    if any(marker in upper for marker in ("MXN", "PESO", "比索")):
        return "墨西哥比索MXN"
    return _clean(default_currency)


def _clean_purchase_product_name(value: str) -> str:
    text = _clean(value)
    text = re.sub(r"^(?:[-－—*•]|\d+[.、)）])\s*", "", text)
    return text.strip(" -－—")


def _parse_purchase_text_chunk(chunk: str, *, currency: Any = "", source_field: str = "") -> dict:
    text = _clean(chunk)
    if not text:
        return {}

    material_code = _purchase_text_value(text, ("物品编码", "物料编码", "品目编码", "Código", "Codigo", "SKU"))
    if not material_code:
        code_match = re.search(r"\b([A-Z]{1,5}\d{3,}[A-Z0-9-]*)\b", text, flags=re.IGNORECASE)
        material_code = _clean(code_match.group(1)).upper() if code_match else ""

    product_name = _purchase_text_value(text, ("物品名称", "物料名称", "品名", "Nombre del artículo", "Nombre del articulo", "Nombre"))
    spec_model = _purchase_text_value(text, ("物品规格", "规格型号", "规格", "Especificación", "Especificacion"))
    quantity = _purchase_text_number(text, ("数量", "Cantidad", "Qty", "QTY"))
    unit = normalize_unit(_purchase_text_value(text, ("单位", "Unidad")))
    unit_price = _purchase_text_number(text, ("单价", "Precio", "Unit Price"))
    goods_value = _purchase_text_number(text, ("总金额", "Monto Total", "金额", "Total"))

    if material_code and not (quantity and unit_price and goods_value):
        after_code = re.split(re.escape(material_code), text, maxsplit=1, flags=re.IGNORECASE)
        tail = after_code[1] if len(after_code) > 1 else text
        numbers = re.findall(r"(?<![A-Z0-9])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", tail, flags=re.IGNORECASE)
        if len(numbers) >= 3:
            quantity = quantity or numbers[-3]
            unit_price = unit_price or numbers[-2]
            goods_value = goods_value or numbers[-1]

    if not product_name and material_code:
        after_code = re.split(re.escape(material_code), text, maxsplit=1, flags=re.IGNORECASE)
        tail = after_code[1] if len(after_code) > 1 else ""
        product_name = re.split(r"\s+(?:数量|Cantidad|Qty|QTY|单价|Precio|总金额|Monto\s*Total|金额|Total)\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]
        if numbers := re.findall(r"(?<![A-Z0-9])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", product_name, flags=re.IGNORECASE):
            product_name = product_name.split(numbers[0], 1)[0]
        product_name = _clean_purchase_product_name(product_name)

    if not (quantity and (unit_price or goods_value) and (material_code or product_name)):
        return {}

    row = {
        "物品编码Código": material_code,
        "物品名称Nombre del artículo": product_name,
        "物品规格Especificacion": spec_model,
        "数量Cantidad": quantity,
        "单位Unidad": unit,
        "单价Precio": unit_price,
        "总金额Monto Total": goods_value,
        "币种Moneda": _purchase_text_currency(text, currency),
        "_dingtalk_table_name": source_field or "文本采购明细",
        "_purchase_text_source": "text",
    }
    return {key: value for key, value in row.items() if value not in (None, "")}


def _parse_purchase_expense_text_rows(value: Any, *, currency: Any = "", source_field: str = "") -> list[dict]:
    text = _clean(value)
    if not text:
        return []

    normalized_text = re.sub(r"[ \t]+", " ", text.replace("\r", "\n"))
    chunks: list[str] = []
    code_matches = list(re.finditer(r"\b[A-Z]{1,5}\d{3,}[A-Z0-9-]*\b", normalized_text, flags=re.IGNORECASE))
    if len(code_matches) > 1:
        for index, match in enumerate(code_matches):
            start = match.start()
            end = code_matches[index + 1].start() if index + 1 < len(code_matches) else len(normalized_text)
            chunks.append(normalized_text[start:end])
    else:
        chunks = [line for line in re.split(r"[\n;；]+", normalized_text) if _clean(line)]
        if len(chunks) <= 1:
            chunks = [normalized_text]

    rows: list[dict] = []
    for chunk in chunks:
        if re.match(r"^\s*(?:合计|总计|小计|total)\b", chunk, flags=re.IGNORECASE):
            continue
        row = _parse_purchase_text_chunk(chunk, currency=currency, source_field=source_field)
        if row:
            rows.append(row)
    return rows


def _is_purchase_text_candidate_field(fieldname: Any, value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    normalized_name = _normalize_key(fieldname)
    name_hit = any(
        marker in normalized_name
        for marker in ("明细", "详情", "物品", "商品", "采购", "备注", "otro", "descripcion", "description", "desglose")
    )
    normalized_text = _normalize_key(text)
    price_hit = any(marker in normalized_text for marker in ("单价", "precio", "金额", "montototal", "total"))
    goods_hit = any(marker in normalized_text for marker in ("物品", "物料", "编码", "codigo", "sku", "名称", "nombre"))
    return name_hit and price_hit and goods_hit


def extract_purchase_expense_rows(instance: dict) -> list[dict]:
    """从采购支出 OA 详情里提取明细行，并补上表单级币种。"""

    currency = _find_component_value(instance, PURCHASE_CURRENCY_FIELD_ALIASES)
    rows: list[dict] = []
    fallback_rows: list[dict] = []
    text_rows: list[dict] = []
    for component in _iter_form_components(instance):
        name = _clean(component.get("name") or component.get("label") or component.get("id"))
        component_type = _clean(component.get("componentType") or component.get("component_type"))
        if component_type != "TableField":
            value = _parse_json_text(component.get("value"))
            if isinstance(value, str) and _is_purchase_text_candidate_field(name, value):
                for row in _parse_purchase_expense_text_rows(value, currency=currency, source_field=name):
                    if currency and "币种Moneda" not in row:
                        row["币种Moneda"] = currency
                    text_rows.append(row)
            continue

        parsed_table = _parse_json_text(component.get("value"))
        if not isinstance(parsed_table, list):
            continue

        table_rows: list[dict] = []
        for raw_row in parsed_table:
            row = _flatten_dingtalk_table_row(raw_row)
            if not row:
                continue
            if currency and "币种Moneda" not in row:
                row["币种Moneda"] = currency
            row["_dingtalk_table_name"] = name
            table_rows.append(row)

        if _is_purchase_detail_table_field(name):
            rows.extend(table_rows)
        else:
            fallback_rows.extend([row for row in table_rows if _looks_like_purchase_detail_row(row)])

    return rows or fallback_rows or text_rows



def build_purchase_expense_item_values_from_approval(instance: dict) -> list[dict]:
    """把采购支出 OA 明细行映射成可回填采购字段的预览结构。"""

    values: list[dict] = []
    for row in extract_purchase_expense_rows(instance):
        mapped = map_purchase_expense_row_to_item(row)
        for fieldname in ("quantity", "unit_price", "goods_value"):
            mapped[fieldname] = _to_number_or_none(mapped.get(fieldname))
        mapped["raw_oa_row"] = row
        values.append(mapped)
    return values


def summarize_purchase_approval(instance: dict, *, process_instance_id: str = "") -> dict:
    """整理采购支出审批详情，供国际物流关联采购单后续补价使用。"""

    instance_id = (
        _clean(process_instance_id)
        or _clean(instance.get("process_instance_id"))
        or _clean(instance.get("processInstanceId"))
        or extract_dingtalk_instance_id(instance.get("url"))
    )
    approval_no = _clean(
        instance.get("business_id")
        or instance.get("businessId")
        or instance.get("bizId")
        or instance.get("approval_no")
    )
    official_url = _clean(instance.get("url") or instance.get("detailUrl") or instance.get("officialUrl"))
    dingtalk_payload = build_dingtalk_order_payload(
        approval_no=approval_no,
        instance_id=instance_id,
        official_url=official_url,
    )
    detail_rows = extract_purchase_expense_rows(instance)
    mapped_items = build_purchase_expense_item_values_from_approval(instance)
    return {
        "source_instance_id": instance_id,
        "source_approval_no": approval_no,
        "source_dingtalk_url": official_url,
        "open_url": dingtalk_payload.get("open_url") or "",
        "approval_title": _clean(instance.get("title") or instance.get("process_instance_title") or instance.get("processInstanceTitle")),
        "approval_status": _clean(instance.get("status") or instance.get("approvalStatus")),
        "originator_userid": _clean(instance.get("originator_userid") or instance.get("originatorUserId")),
        "originator_dept_id": _clean(instance.get("originator_dept_id") or instance.get("originatorDeptId")),
        "create_time": instance.get("create_time") or instance.get("createTime") or "",
        "finish_time": instance.get("finish_time") or instance.get("finishTime") or "",
        "purchase_currency": _find_component_value(instance, PURCHASE_CURRENCY_FIELD_ALIASES),
        "detail_row_count": len(detail_rows),
        "detail_rows": detail_rows,
        "mapped_preview_items": mapped_items,
    }


def pull_linked_purchase_approval_details(
    *,
    token: str,
    linked_approvals: list[dict],
    api_style: str = "auto",
    include_running: bool = False,
) -> list[dict]:
    """按关联审批实例 ID 拉取采购支出详情并返回解析摘要。"""

    summaries: list[dict] = []
    for linked in linked_approvals:
        if not isinstance(linked, dict):
            continue
        instance_id = _clean(linked.get("source_instance_id") or linked.get("proc_inst_id") or linked.get("instance_id"))
        if not instance_id:
            summaries.append(
                {
                    "ok": False,
                    "source_approval_no": linked.get("approval_no") or linked.get("source_approval_no") or "",
                    "source_instance_id": "",
                    "message": "关联采购审批缺少实例 ID，无法拉取详情。",
                }
            )
            continue
        detail = get_process_instance_detail(token=token, process_instance_id=instance_id, api_style=api_style)
        summary = summarize_purchase_approval(detail, process_instance_id=instance_id)
        if is_hidden_approval_status(summary.get("approval_status")):
            summary["ok"] = False
            summary["detail_row_count"] = 0
            summary["detail_rows"] = []
            summary["mapped_preview_items"] = []
            summary["message"] = "采购支出审批已撤销或终止，未用于采购字段同步。"
        elif not include_running and not is_completed_approval_status(summary.get("approval_status")):
            summary["ok"] = False
            summary["detail_row_count"] = 0
            summary["detail_rows"] = []
            summary["mapped_preview_items"] = []
            summary["message"] = "采购支出审批未完成，未用于采购字段同步。"
        else:
            summary["ok"] = True
        summary["linked_from"] = linked
        summaries.append(summary)
    return summaries


def build_oa_item_values_from_approval(item: dict) -> list[dict]:
    """把审批里的货物信息表格转成可写入 Overseas Cost Item 的基础行。"""

    source_approval_no = _clean(item.get("source_approval_no"))
    source_instance_id = _clean(item.get("source_instance_id"))
    source_dingtalk_url = _clean(item.get("source_dingtalk_url"))
    rows = extract_oa_goods_rows(item)
    form_fields = item.get("form_fields") or {}
    total_gross_weight = _to_number_or_none(_find_field_value(form_fields, LOGISTICS_WEIGHT_FIELD_ALIASES))
    values: list[dict] = []
    for index, row in enumerate(rows, start=1):
        mapped = map_oa_row_to_item(row)
        mapped.update(
            {
                "row_no": index,
                "quantity": _to_number_or_none(mapped.get("quantity")),
                "source_type": "oa_logistics",
                "source_doc_no": source_approval_no or source_instance_id,
                "parse_status": "SUCCESS",
                "dingtalk_instance_id": source_instance_id,
                "dingtalk_official_url": source_dingtalk_url,
                "raw_excel_json": _json_dumps(row),
                "extra_json": _json_dumps(
                    {
                        "source": "dingtalk_oa_logistics_form",
                        "approval_no": source_approval_no,
                        "instance_id": source_instance_id,
                        "dingtalk_row_number": row.get("_dingtalk_row_number"),
                    }
                ),
            }
        )
        values.append(mapped)
    if total_gross_weight and values and not any(_to_number_or_none(row.get("gross_weight_kg")) for row in values):
        total_quantity = sum(_to_number_or_none(row.get("quantity")) or 0 for row in values)
        if total_quantity > 0:
            for mapped in values:
                quantity = _to_number_or_none(mapped.get("quantity")) or 0
                mapped["gross_weight_kg"] = round(total_gross_weight * quantity / total_quantity, 6) if quantity else 0
    return values


def build_batch_values_from_approval(item: dict) -> dict:
    """把一条国际物流审批摘要整理成批次头追溯字段。"""

    form_fields = item.get("form_fields") or {}
    logistics_no = _clean(item.get("logistics_no"))
    source_approval_no = _clean(item.get("source_approval_no"))
    source_instance_id = _clean(item.get("source_instance_id"))
    batch_no = _clean(_first_non_empty(logistics_no, source_approval_no, source_instance_id))
    source_dingtalk_url = _clean(item.get("source_dingtalk_url"))
    oa_form_attachments = item.get("oa_form_attachments") or extract_attachments_from_form_fields(form_fields)
    attachment_count = len(oa_form_attachments) if oa_form_attachments else _count_dingtalk_attachments(form_fields)
    transport_mode = _normalize_transport_mode(item.get("transport_mode")) or detect_approval_transport_mode(item.get("transport_mode_raw")) or "SEA"
    subsidiary = extract_subsidiary_from_approval(item)
    values = {
        "batch_no": batch_no,
        "waybill_no": logistics_no,
        "container_no": logistics_no if _looks_like_container_no(logistics_no) else "",
        "transport_mode": transport_mode,
        "subsidiary_code": subsidiary.get("subsidiary_code") or "",
        "source_type": "oa_logistics",
        "source_data_id": source_instance_id or source_approval_no,
        "source_approval_no": source_approval_no,
        "source_instance_id": source_instance_id or extract_dingtalk_instance_id(source_dingtalk_url),
        "source_dingtalk_url": source_dingtalk_url,
        "source_approval_status": _clean(item.get("approval_status")),
        "source_title": _clean(item.get("approval_title")),
        "source_creator_name": _clean(item.get("originator_userid")),
        "source_creator_dept": _clean(item.get("originator_dept_id")),
        "source_created_at": _to_frappe_datetime(item.get("create_time")),
        "source_finished_at": _to_frappe_datetime(item.get("finish_time")),
        "source_attachment_count": attachment_count,
        "status": "Imported",
        "confirm_status": "Pending",
        "writeback_status": "Not Started",
        "version_count": 1,
        "item_count": 0,
        "import_remark": "从钉钉国际物流审批拉取，仅保存追溯字段，未写入物料和金额。",
        "source_remark": _clean(item.get("transport_mode_raw")),
        "extra_json": _json_dumps(
            {
                "source": "dingtalk_oa_logistics",
                "transport_mode": transport_mode,
                "transport_mode_raw": item.get("transport_mode_raw"),
                "open_url": item.get("open_url"),
                "logistics_fee": item.get("logistics_fee") or extract_logistics_fee_from_approval(item),
                "logistics_quote_candidates": item.get("logistics_quote_candidates") or extract_logistics_quote_candidates_from_approval(item),
                "linked_purchase_approvals": item.get("linked_purchase_approvals") or [],
                "oa_form_attachments": oa_form_attachments,
                "subsidiary": subsidiary,
                "form_fields": form_fields,
            }
        ),
    }
    return values


def _filter_batch_values(values: dict) -> dict:
    if frappe is None:
        return dict(values)
    meta = frappe.get_meta("Overseas Cost Batch")
    return {fieldname: value for fieldname, value in values.items() if meta.has_field(fieldname)}


def _filter_item_values(values: dict) -> dict:
    if frappe is None:
        return dict(values)
    meta = frappe.get_meta("Overseas Cost Item")
    return {fieldname: value for fieldname, value in values.items() if meta.has_field(fieldname)}


def _resolve_existing_batch_name(values: dict) -> str:
    if frappe is None:
        return ""
    lookup_specs = [
        ("source_instance_id", values.get("source_instance_id")),
        ("source_approval_no", values.get("source_approval_no")),
        ("batch_no", values.get("batch_no")),
        ("waybill_no", values.get("waybill_no")),
    ]
    for fieldname, value in lookup_specs:
        if not _has_value(value):
            continue
        existing_name = frappe.db.get_value("Overseas Cost Batch", {fieldname: value}, "name")
        if existing_name:
            return existing_name
    return ""


def _insert_batch_audit_log(*, batch_name: str, field_name: str, old_value: Any, new_value: Any, remark: str) -> None:
    if frappe is None:
        return
    operator_name = ""
    session_user = getattr(getattr(frappe, "session", None), "user", None)
    if session_user and session_user != "Guest":
        operator_name = session_user
    frappe.get_doc(
        {
            "doctype": "Overseas Cost Audit Log",
            "batch": batch_name,
            "action_type": "IMPORT",
            "field_name": field_name,
            "old_value": "" if old_value is None else _json_dumps_for_audit(old_value),
            "new_value": "" if new_value is None else _json_dumps_for_audit(new_value),
            "operator_name": operator_name,
            "action_remark": remark,
        }
    ).insert(ignore_permissions=True)


def _ensure_oa_trace_version(batch_name: str, batch_no: str) -> str:
    if frappe is None:
        return ""
    current_version = frappe.db.get_value("Overseas Cost Batch", batch_name, "current_version")
    if current_version:
        return current_version
    existing_name = frappe.db.get_value(
        "Overseas Cost Version",
        {"batch": batch_name, "version_code": "OA追溯"},
        "name",
    )
    if existing_name:
        frappe.db.set_value(
            "Overseas Cost Batch",
            batch_name,
            {"current_version": existing_name, "version_count": 1},
            update_modified=False,
        )
        return existing_name
    version_doc = frappe.get_doc(
        {
            "doctype": "Overseas Cost Version",
            "batch": batch_name,
            "version_code": "OA追溯",
            "version_type": "Estimated",
            "status": "Active",
            "is_current": 1,
            "source_type": "Import",
            "fx_usd_to_rmb": DEFAULT_FX_USD_TO_RMB,
            "fx_rmb_to_mxn": DEFAULT_FX_RMB_TO_MXN,
            "remark": f"钉钉国际物流审批追溯默认版本：{batch_no}",
        }
    ).insert(ignore_permissions=True)
    frappe.db.set_value(
        "Overseas Cost Batch",
        batch_name,
        {"current_version": version_doc.name, "version_count": 1},
        update_modified=False,
    )
    return version_doc.name


def _create_oa_trace_batch(values: dict) -> dict:
    filtered_values = _filter_batch_values(values)
    filtered_values["doctype"] = "Overseas Cost Batch"
    batch_doc = frappe.get_doc(filtered_values).insert(ignore_permissions=True)
    version_name = _ensure_oa_trace_version(batch_doc.name, values.get("batch_no") or batch_doc.name)
    _insert_batch_audit_log(
        batch_name=batch_doc.name,
        field_name="oa_logistics_trace",
        old_value=None,
        new_value={
            "batch_no": values.get("batch_no"),
            "source_approval_no": values.get("source_approval_no"),
            "source_instance_id": values.get("source_instance_id"),
        },
        remark="从钉钉国际物流审批创建批次追溯记录",
    )
    return {"action": "created", "batch_name": batch_doc.name, "version_name": version_name, "changed_fields": list(filtered_values.keys())}


def _update_oa_trace_batch(batch_name: str, values: dict) -> dict:
    current = frappe.db.get_value("Overseas Cost Batch", batch_name, list(_filter_batch_values(values).keys()), as_dict=True) or {}
    updates: dict[str, Any] = {}
    always_refresh_fields = {"transport_mode", "source_approval_status", "source_attachment_count", "source_finished_at"}
    for fieldname, new_value in _filter_batch_values(values).items():
        if fieldname in {"batch_no", "status", "confirm_status", "writeback_status", "version_count", "item_count"}:
            continue
        old_value = current.get(fieldname)
        if fieldname == "extra_json":
            merged_extra_json = _merge_oa_extra_json(old_value, new_value)
            if _has_value(merged_extra_json) and not _values_match(old_value, merged_extra_json):
                updates[fieldname] = merged_extra_json
            continue
        if fieldname in always_refresh_fields:
            if _has_value(new_value) and not _values_match(old_value, new_value):
                updates[fieldname] = new_value
            continue
        if not _has_value(old_value) and _has_value(new_value):
            updates[fieldname] = new_value

    version_name = _ensure_oa_trace_version(batch_name, values.get("batch_no") or batch_name)
    if not updates:
        return {"action": "unchanged", "batch_name": batch_name, "version_name": version_name, "changed_fields": []}

    old_snapshot = {fieldname: current.get(fieldname) for fieldname in updates}
    changed_fields = list(updates.keys())
    new_snapshot = dict(updates)
    frappe.db.set_value("Overseas Cost Batch", batch_name, updates, update_modified=True)
    _insert_batch_audit_log(
        batch_name=batch_name,
        field_name="oa_logistics_trace",
        old_value=old_snapshot,
        new_value=new_snapshot,
        remark="从钉钉国际物流审批补充批次追溯字段",
    )
    return {"action": "updated", "batch_name": batch_name, "version_name": version_name, "changed_fields": changed_fields}


def _sync_oa_goods_items(
    *,
    batch_name: str,
    version_name: str,
    approval_item: dict,
    only_when_empty: bool = True,
) -> dict:
    if frappe is None:
        item_values = build_oa_item_values_from_approval(approval_item)
        return {
            "action": "preview",
            "created_count": 0,
            "skipped": False,
            "item_count": len(item_values),
            "items": item_values,
        }
    if not version_name:
        return {
            "action": "skipped",
            "created_count": 0,
            "skipped": True,
            "reason": "当前批次没有版本，无法写入 OA 基础物料行。",
        }

    existing_count = frappe.db.count("Overseas Cost Item", {"batch": batch_name, "version": version_name})
    if only_when_empty and existing_count:
        return {
            "action": "skipped",
            "created_count": 0,
            "skipped": True,
            "reason": "当前批次已有 SKU 明细，未用 OA 表单覆盖。",
            "existing_count": existing_count,
        }

    item_values = build_oa_item_values_from_approval(approval_item)
    if not item_values:
        return {
            "action": "skipped",
            "created_count": 0,
            "skipped": True,
            "reason": "钉钉审批单未解析到可用的货物信息。",
        }

    created_names: list[str] = []
    for values in item_values:
        doc_values = _filter_item_values(
            {
                **values,
                "doctype": "Overseas Cost Item",
                "batch": batch_name,
                "version": version_name,
            }
        )
        doc_values["doctype"] = "Overseas Cost Item"
        created_names.append(frappe.get_doc(doc_values).insert(ignore_permissions=True).name)

    frappe.db.set_value(
        "Overseas Cost Batch",
        batch_name,
        {
            "item_count": existing_count + len(created_names),
            "status": "Imported",
        },
        update_modified=True,
    )
    _insert_batch_audit_log(
        batch_name=batch_name,
        field_name="oa_logistics_items",
        old_value={"item_count": existing_count},
        new_value={"created_count": len(created_names), "item_count": existing_count + len(created_names)},
        remark="从钉钉国际物流审批表单生成基础物料行",
    )
    return {
        "action": "created",
        "created_count": len(created_names),
        "skipped": False,
        "item_count": existing_count + len(created_names),
        "item_names": created_names,
    }


def _oa_attachment_parse_targets(record: dict) -> list[str]:
    attachment_type = _clean(record.get("attachment_type"))
    extension = _clean(record.get("file_ext")).lower()
    if attachment_type == "Packing List" or extension in {"xls", "xlsx", "csv"}:
        return ["actual_shipped_qty", "gross_weight_kg", "volume_m3", "chargeable_weight_kg"]
    if attachment_type == "Tax Certificate":
        return ["pedimento_no", "tax_totals", "paid_total_mxn", "line_items"]
    if attachment_type == "Logistics Bill":
        return ["logistics_fee", "fuel_surcharge", "currency", "bill_total"]
    if attachment_type == "Commercial Invoice":
        return ["invoice_no", "goods_value", "currency", "line_items"]
    return []


def _oa_attachment_source_doc_no(approval_item: dict, record: dict) -> str:
    approval_no = _clean(approval_item.get("source_approval_no"))
    instance_id = _clean(approval_item.get("source_instance_id"))
    source_no = approval_no or instance_id or "OA"
    file_key = _clean(record.get("file_id") or record.get("file_url") or record.get("file_name"))
    if len(file_key) > 90:
        file_key = file_key[:90]
    return f"{source_no}::{file_key}" if file_key else source_no


def _build_oa_attachment_values(
    *,
    batch_name: str,
    version_name: str,
    approval_item: dict,
    record: dict,
) -> dict:
    parse_snapshot = {
        "source": "dingtalk_oa_form_attachment",
        "comment_attachments_included": False,
        "approval_no": approval_item.get("source_approval_no") or "",
        "instance_id": approval_item.get("source_instance_id") or "",
        "originator_userid": approval_item.get("originator_userid") or "",
        "source_field": record.get("source_field") or "",
        "component_type": record.get("component_type") or "",
        "file_id": record.get("file_id") or "",
        "space_id": record.get("space_id") or "",
        "file_size": record.get("file_size") or "",
        "file_ext": record.get("file_ext") or "",
        "raw_attachment": record.get("raw") or {},
    }
    mapped_snapshot = {
        "parse_targets": _oa_attachment_parse_targets(record),
        "next_step": "待下载钉钉发起表单附件后解析；评论附件暂未纳入。",
    }
    return {
        "batch": batch_name,
        "version": version_name,
        "source_type": "OA",
        "attachment_type": record.get("attachment_type") or "Other",
        "source_doc_no": _oa_attachment_source_doc_no(approval_item, record),
        "file_name": record.get("file_name") or "",
        "file_url": record.get("file_url") or "",
        "parse_status": "Queued",
        "parse_result_json": _json_dumps(parse_snapshot),
        "mapped_result_json": _json_dumps(mapped_snapshot),
        "remark": "钉钉发起表单附件已登记，等待下载和解析；评论附件暂不导入。",
    }


def _find_existing_oa_attachment(values: dict) -> str:
    if frappe is None:
        return ""
    filters = {
        "batch": values.get("batch"),
        "source_type": "OA",
        "source_doc_no": values.get("source_doc_no"),
    }
    if not filters["batch"] or not filters["source_doc_no"]:
        return ""
    return frappe.db.get_value("Overseas Cost Attachment", filters, "name") or ""


def _save_existing_oa_attachment(existing_name: str, values: dict) -> None:
    doc = frappe.get_doc("Overseas Cost Attachment", existing_name)
    if hasattr(doc, "reload"):
        doc.reload()
    for fieldname, value in values.items():
        setattr(doc, fieldname, value)
    try:
        doc.save(ignore_permissions=True)
    except Exception as exc:
        if exc.__class__.__name__ != "TimestampMismatchError":
            raise
        doc = frappe.get_doc("Overseas Cost Attachment", existing_name)
        if hasattr(doc, "reload"):
            doc.reload()
        for fieldname, value in values.items():
            setattr(doc, fieldname, value)
        doc.save(ignore_permissions=True)


def _sync_oa_form_attachments(
    *,
    batch_name: str,
    version_name: str,
    approval_item: dict,
) -> dict:
    attachments = approval_item.get("oa_form_attachments") or extract_attachments_from_form_fields(approval_item.get("form_fields") or {})
    if frappe is None:
        return {
            "action": "preview",
            "attachment_count": len(attachments),
            "created_count": 0,
            "updated_count": 0,
            "items": attachments,
        }
    if not attachments:
        return {
            "action": "skipped",
            "attachment_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "reason": "钉钉发起表单未解析到附件；评论附件本阶段不处理。",
        }

    created_names: list[str] = []
    updated_names: list[str] = []
    for record in attachments:
        values = _build_oa_attachment_values(
            batch_name=batch_name,
            version_name=version_name,
            approval_item=approval_item,
            record=record,
        )
        existing_name = _find_existing_oa_attachment(values)
        if existing_name:
            _save_existing_oa_attachment(existing_name, values)
            updated_names.append(existing_name)
        else:
            doc = frappe.get_doc({"doctype": "Overseas Cost Attachment", **values}).insert(ignore_permissions=True)
            created_names.append(doc.name)

    if created_names or updated_names:
        _insert_batch_audit_log(
            batch_name=batch_name,
            field_name="oa_form_attachments",
            old_value=None,
            new_value={
                "created_count": len(created_names),
                "updated_count": len(updated_names),
                "attachment_count": len(attachments),
                "comment_attachments_included": False,
            },
            remark="登记钉钉发起表单附件，评论附件暂未纳入",
        )

    return {
        "action": "synced",
        "attachment_count": len(attachments),
        "created_count": len(created_names),
        "updated_count": len(updated_names),
        "created_names": created_names,
        "updated_names": updated_names,
    }


def _sync_linked_purchase_fields(
    *,
    batch_name: str,
    version_name: str,
    approval_item: dict,
) -> dict:
    """按国际物流 OA 关联的采购支出审批，自动补采购单价、币种和货值。"""

    linked_approvals = approval_item.get("linked_purchase_approvals") or []
    if not linked_approvals:
        return {
            "action": "skipped",
            "ok": True,
            "linked_purchase_count": 0,
            "updated_count": 0,
            "reason": "当前国际物流 OA 没有关联采购支出审批。",
        }
    if frappe is None:
        return {
            "action": "preview",
            "ok": True,
            "linked_purchase_count": len(linked_approvals),
            "updated_count": 0,
            "reason": "当前未连接 Frappe，仅返回关联采购支出审批数量。",
        }

    try:
        from overseas_costing.services import import_service

        result = import_service.apply_linked_purchase_expense_fillable_fields(
            batch_name=batch_name,
            version_name=version_name,
            linked_purchase_json=_json_dumps(linked_approvals),
            recalculate_after_writeback=False,
        )
    except Exception as exc:
        return {
            "action": "failed",
            "ok": False,
            "linked_purchase_count": len(linked_approvals),
            "updated_count": 0,
            "message": f"关联采购支出 OA 同步失败：{exc}",
        }

    return {
        "action": "synced" if result.get("ok") else "failed",
        "ok": bool(result.get("ok")),
        "linked_purchase_count": len(linked_approvals),
        "updated_count": result.get("updated_count", 0),
        "changed_field_count": result.get("changed_field_count", 0),
        "skipped_count": result.get("skipped_count", 0),
        "unmatched_count": result.get("unmatched_count", 0),
        "ambiguous_count": result.get("ambiguous_count", 0),
        "message": result.get("message") or "",
    }


def _sync_oa_logistics_allocation_rule(
    *,
    batch_name: str,
    version_name: str,
    approval_item: dict,
) -> dict:
    """把国际物流 OA 的物流费用落成整票分摊规则。"""

    fee = approval_item.get("logistics_fee") if isinstance(approval_item.get("logistics_fee"), dict) else {}
    fee = fee or extract_logistics_fee_from_approval(approval_item)
    if not fee and detect_approval_transport_mode(
        approval_item.get("transport_mode") or approval_item.get("transport_mode_raw") or (approval_item.get("form_fields") or {})
    ) == "EXPRESS":
        quote_candidates = approval_item.get("logistics_quote_candidates")
        if not isinstance(quote_candidates, list):
            quote_candidates = extract_logistics_quote_candidates_from_approval(approval_item)
        valid_quotes = [candidate for candidate in quote_candidates if _parse_money_amount(candidate.get("amount")) is not None]
        if len(valid_quotes) == 1:
            selected = valid_quotes[0]
            fee = {
                "amount": selected.get("amount"),
                "currency": selected.get("currency") or "RMB",
                "source_label": "快递物流报价",
                "source_field": selected.get("source_field") or "物流报价",
                "source_value": selected.get("evidence_line") or selected.get("source_value") or "",
            }
    parsed_amount = _parse_money_amount(fee.get("amount")) if fee else None
    if not fee or parsed_amount is None:
        return {
            "action": "skipped",
            "ok": True,
            "created_count": 0,
            "updated_count": 0,
            "reason": "当前国际物流 OA 没有解析到明确物流费用，暂不生成分摊规则。",
        }
    if not version_name:
        return {
            "action": "skipped",
            "ok": True,
            "created_count": 0,
            "updated_count": 0,
            "reason": "当前批次没有版本，无法生成物流费用分摊规则。",
        }

    amount = float(parsed_amount)
    currency = _normalize_currency_code(fee.get("currency")) or "RMB"
    allocation_basis = _normalize_allocation_basis(fee.get("allocation_basis") or approval_item.get("allocation_basis"))
    values = {
        "batch": batch_name,
        "version": version_name,
        "rule_code": "oa_logistics_freight",
        "expense_category": "国际物流费用",
        "allocation_basis": allocation_basis,
        "basis_field": allocation_basis,
        "currency": currency,
        "amount": amount,
        "priority_no": 20,
        "remark": f"从钉钉国际物流 OA {fee.get('source_label') or '物流费用'}生成：{fee.get('source_field') or ''}={fee.get('source_value')}",
        "is_active": 1,
        "is_enabled": 1,
    }

    if frappe is None:
        return {
            "action": "preview",
            "ok": True,
            "created_count": 0,
            "updated_count": 0,
            "rule": values,
            "fee": fee,
        }

    existing_name = frappe.db.get_value(
        "Overseas Cost Allocation Rule",
        {"batch": batch_name, "version": version_name, "rule_code": values["rule_code"]},
        "name",
    )
    if existing_name:
        current = frappe.db.get_value(
            "Overseas Cost Allocation Rule",
            existing_name,
            list(values.keys()),
            as_dict=True,
        ) or {}
        if current and all(_values_match(current.get(fieldname), value) for fieldname, value in values.items()):
            return {
                "action": "unchanged",
                "ok": True,
                "rule_name": existing_name,
                "created_count": 0,
                "updated_count": 0,
                "fee": fee,
            }
        frappe.db.set_value("Overseas Cost Allocation Rule", existing_name, values, update_modified=True)
        action = "updated"
        rule_name = existing_name
        created_count = 0
        updated_count = 1
    else:
        rule_name = frappe.get_doc({"doctype": "Overseas Cost Allocation Rule", **values}).insert(ignore_permissions=True).name
        action = "created"
        created_count = 1
        updated_count = 0

    _insert_batch_audit_log(
        batch_name=batch_name,
        field_name="oa_logistics_freight_rule",
        old_value={"rule_name": existing_name} if existing_name else None,
        new_value={**values, "rule_name": rule_name},
        remark="从钉钉国际物流 OA 生成/更新物流费用分摊规则",
    )
    return {
        "action": action,
        "ok": True,
        "rule_name": rule_name,
        "created_count": created_count,
        "updated_count": updated_count,
        "fee": fee,
        "rule": values,
    }


def _is_database_connection_lost(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "server has gone away",
            "lost connection",
            "connection already closed",
            "mysql server has gone away",
            "(2006",
            "(2013",
        )
    )


def _reset_database_connection() -> None:
    if frappe is None:
        return
    try:
        frappe.db.rollback()
    except Exception:
        pass
    try:
        frappe.db.close()
    except Exception:
        pass
    if hasattr(frappe.db, "connect"):
        frappe.db.connect()


def _run_with_database_retry(operation):
    try:
        return operation()
    except Exception as exc:
        if not _is_database_connection_lost(exc):
            raise
        _reset_database_connection()
        return operation()


def _commit_oa_pull_progress() -> None:
    if frappe is None or not hasattr(frappe.db, "commit"):
        return
    frappe.db.commit()


def _recalculate_after_purchase_sync(
    *,
    batch_name: str,
    version_name: str,
    purchase_sync: dict,
    logistics_fee_sync: dict | None = None,
) -> dict:
    if frappe is None:
        return {"action": "skipped", "reason": "当前未连接 Frappe。"}
    purchase_changed = purchase_sync.get("ok") and int(purchase_sync.get("updated_count") or 0) > 0
    fee_changed = bool(logistics_fee_sync and logistics_fee_sync.get("ok") and logistics_fee_sync.get("action") in {"created", "updated"})
    if not purchase_changed and not fee_changed:
        return {"action": "skipped", "reason": "采购字段和物流费用规则没有新增写入，暂不自动试算。"}
    try:
        from overseas_costing.services.calculate_service import recalculate_batch

        result = recalculate_batch(batch_name=batch_name, version_name=version_name)
        return {"action": "recalculated", "ok": bool(result.get("ok", True)), "result": result}
    except Exception as exc:
        return {"action": "failed", "ok": False, "message": f"采购字段同步后自动试算失败：{exc}"}


def _get_oa_trace_from_extra(extra_json: Any) -> tuple[dict, dict, bool]:
    data = _json_loads_dict(extra_json)
    if data.get("source") == "dingtalk_oa_logistics":
        return data, data, True
    trace = data.get("oa_logistics_trace")
    if isinstance(trace, dict):
        return data, trace, False
    return data, {}, False


def _set_oa_trace_in_extra(root: dict, trace: dict, is_root_trace: bool) -> str:
    if is_root_trace:
        merged = {**root, **trace}
    else:
        merged = dict(root)
        merged["oa_logistics_trace"] = trace
    return _json_dumps(merged)


def _trace_finish_time_candidates(row: dict, trace: dict) -> list[Any]:
    candidates = [
        row.get("source_finished_at"),
        trace.get("finish_time"),
        trace.get("finishTime"),
        trace.get("source_finished_at"),
        trace.get("finished_at"),
        trace.get("completed_at"),
        trace.get("complete_time"),
        trace.get("approval_finished_at"),
    ]
    raw_instance = trace.get("raw_instance") if isinstance(trace.get("raw_instance"), dict) else {}
    if raw_instance:
        candidates.extend(
            [
                raw_instance.get("finish_time"),
                raw_instance.get("finishTime"),
                raw_instance.get("completed_at"),
                raw_instance.get("complete_time"),
            ]
        )
    return candidates


def _resolve_trace_finished_at(row: dict, trace: dict) -> tuple[str, str]:
    for candidate in _trace_finish_time_candidates(row, trace):
        normalized = _to_frappe_datetime(candidate)
        if normalized:
            return normalized, _clean(candidate)
    return "", ""


def sync_existing_oa_finished_times(limit: int | None = 200) -> dict:
    """从已保存的 OA 快照回填批次来源完成时间，仅补空值。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法回填历史批次来源完成时间。",
        }

    page_length = max(1, min(int(limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=[
            "name",
            "batch_no",
            "source_approval_no",
            "source_instance_id",
            "source_finished_at",
            "extra_json",
        ],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    updated_items: list[dict] = []
    skipped_items: list[dict] = []
    for row in rows:
        existing_finished_at = _to_frappe_datetime(row.get("source_finished_at"))
        if existing_finished_at:
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "reason": "已有来源完成时间",
                }
            )
            continue

        _root, trace, _is_root_trace = _get_oa_trace_from_extra(row.get("extra_json"))
        finished_at, raw_finished_at = _resolve_trace_finished_at(row, trace)
        if not finished_at:
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "source_approval_no": row.get("source_approval_no") or trace.get("source_approval_no") or "",
                    "source_instance_id": row.get("source_instance_id") or trace.get("source_instance_id") or "",
                    "reason": "已保存 OA 快照里没有完成时间，需要重拉钉钉详情",
                }
            )
            continue

        frappe.db.set_value(
            "Overseas Cost Batch",
            row.get("name"),
            "source_finished_at",
            finished_at,
            update_modified=False,
        )
        _insert_batch_audit_log(
            batch_name=row.get("name"),
            field_name="source_finished_at",
            old_value=row.get("source_finished_at"),
            new_value=finished_at,
            remark="从已保存钉钉 OA 快照回填来源完成时间，用于缺真实付款日时暂估汇率",
        )
        updated_items.append(
            {
                "batch_name": row.get("name"),
                "batch_no": row.get("batch_no"),
                "source_approval_no": row.get("source_approval_no") or trace.get("source_approval_no") or "",
                "source_instance_id": row.get("source_instance_id") or trace.get("source_instance_id") or "",
                "source_finished_at": finished_at,
                "raw_finished_at": raw_finished_at,
            }
        )

    if updated_items and hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "dry_run": False,
        "scanned_count": len(rows),
        "updated_count": len(updated_items),
        "skipped_count": len(skipped_items),
        "items": updated_items,
        "skipped_items": skipped_items,
        "message": (
            f"已从本地 OA 快照回填 {len(updated_items)} 条批次来源完成时间；"
            f"{len(skipped_items)} 条未处理，缺快照完成时间的需重拉钉钉详情。"
        ),
    }


def refresh_missing_oa_finished_times(
    limit: int | None = 200,
    *,
    env_file: str | None = None,
    api_style: str = "auto",
    access_token: str = "",
) -> dict:
    """回钉钉重拉详情，只补缺失的来源完成时间和审批状态。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法重拉钉钉详情补来源完成时间。",
        }

    resolved_env_file = resolve_dingtalk_env_file(env_file)
    if resolved_env_file:
        load_env_file(resolved_env_file)
    resolved_api_style = _resolve_api_style(api_style)
    token = get_access_token(
        api_style=resolved_api_style,
        access_token=access_token or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
    )

    page_length = max(1, min(int(limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics", "source_finished_at": ["in", ["", None]]},
        fields=[
            "name",
            "batch_no",
            "source_approval_no",
            "source_instance_id",
            "source_dingtalk_url",
            "source_approval_status",
            "source_finished_at",
            "extra_json",
        ],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    updated_items: list[dict] = []
    skipped_items: list[dict] = []
    failed_items: list[dict] = []
    for row in rows:
        root, trace, is_root_trace = _get_oa_trace_from_extra(row.get("extra_json"))
        instance_id = _resolve_batch_source_instance_id(row, trace)
        if not instance_id:
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "reason": "缺少钉钉审批实例 ID，无法重拉详情",
                }
            )
            continue

        try:
            detail = get_process_instance_detail(
                token=token,
                process_instance_id=instance_id,
                api_style=resolved_api_style,
            )
            summary = summarize_approval(detail, process_instance_id=instance_id)
        except Exception as exc:
            failed_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "source_instance_id": instance_id,
                    "reason": str(exc),
                }
            )
            continue

        finished_at = _to_frappe_datetime(summary.get("finish_time"))
        approval_status = _clean(summary.get("approval_status"))
        if not finished_at:
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "source_instance_id": instance_id,
                    "approval_status": approval_status,
                    "reason": "钉钉详情未返回完成时间",
                }
            )
            continue

        updates: dict[str, Any] = {"source_finished_at": finished_at}
        if approval_status and not _values_match(row.get("source_approval_status"), approval_status):
            updates["source_approval_status"] = approval_status

        trace_updates = {
            "source_instance_id": summary.get("source_instance_id") or instance_id,
            "source_approval_no": summary.get("source_approval_no") or row.get("source_approval_no") or trace.get("source_approval_no") or "",
            "source_dingtalk_url": summary.get("source_dingtalk_url") or row.get("source_dingtalk_url") or trace.get("source_dingtalk_url") or "",
            "approval_status": approval_status,
            "finish_time": summary.get("finish_time") or "",
        }
        updates["extra_json"] = _set_oa_trace_in_extra(root, {**trace, **trace_updates}, is_root_trace)
        frappe.db.set_value("Overseas Cost Batch", row.get("name"), updates, update_modified=False)
        _insert_batch_audit_log(
            batch_name=row.get("name"),
            field_name="source_finished_at",
            old_value=row.get("source_finished_at"),
            new_value=updates.get("source_finished_at") or "",
            remark="从钉钉审批详情补充来源完成时间，用于缺真实付款日时暂估汇率",
        )
        updated_items.append(
            {
                "batch_name": row.get("name"),
                "batch_no": row.get("batch_no"),
                "source_approval_no": trace_updates["source_approval_no"],
                "source_instance_id": instance_id,
                "source_approval_status": approval_status,
                "source_finished_at": finished_at,
                "changed_fields": list(updates.keys()),
            }
        )

    if updated_items and hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": not failed_items,
        "dry_run": False,
        "env_file_loaded": bool(resolved_env_file),
        "api_style": resolved_api_style,
        "scanned_count": len(rows),
        "updated_count": len(updated_items),
        "skipped_count": len(skipped_items),
        "failed_count": len(failed_items),
        "items": updated_items,
        "skipped_items": skipped_items,
        "failed_items": failed_items,
        "message": f"已重拉钉钉详情补充 {len(updated_items)} 条来源完成时间；失败 {len(failed_items)} 条。",
    }


def supplement_empty_oa_goods_items(batch_name: str) -> dict:
    """只为没有 SKU 的指定 OA 批次补建表单货物明细，不覆盖已有明细。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法补建历史批次明细。",
        }

    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        _clean(batch_name),
        ["name", "batch_no", "current_version", "source_approval_no", "source_instance_id", "source_dingtalk_url", "source_remark", "extra_json"],
        as_dict=True,
    )
    if not batch:
        return {"ok": False, "message": "未找到指定的海外成本批次。"}

    root, trace, _is_root_trace = _get_oa_trace_from_extra(batch.get("extra_json"))
    form_fields = trace.get("form_fields") or {}
    if not form_fields:
        return {
            "ok": False,
            "batch_name": batch.get("name"),
            "message": "该批次没有保存原始审批字段，需先重拉对应钉钉审批单。",
        }

    approval_item = {
        "source_approval_no": batch.get("source_approval_no") or trace.get("source_approval_no") or "",
        "source_instance_id": batch.get("source_instance_id") or trace.get("source_instance_id") or "",
        "source_dingtalk_url": batch.get("source_dingtalk_url") or trace.get("source_dingtalk_url") or "",
        "transport_mode_raw": trace.get("transport_mode_raw") or batch.get("source_remark") or "",
        "logistics_no": batch.get("batch_no") or "",
        "form_fields": form_fields,
    }
    sync_result = _sync_oa_goods_items(
        batch_name=batch.get("name"),
        version_name=batch.get("current_version") or "",
        approval_item=approval_item,
        only_when_empty=True,
    )
    return {
        "ok": not sync_result.get("skipped") or bool(sync_result.get("existing_count")),
        "batch_name": batch.get("name"),
        "batch_no": batch.get("batch_no"),
        "item_sync": sync_result,
    }


def sync_existing_oa_form_attachments(limit: int | None = 200) -> dict:
    """从已有 OA 批次的 extra_json.form_fields 回填发起表单附件记录。

    只处理发起表单附件，不处理审批评论附件。
    """

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法回填已有批次附件记录。",
        }

    page_length = max(1, min(int(limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=[
            "name",
            "batch_no",
            "current_version",
            "source_approval_no",
            "source_instance_id",
            "extra_json",
            "source_attachment_count",
        ],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    synced_items: list[dict] = []
    skipped_items: list[dict] = []
    total_created = 0
    total_updated = 0

    for row in rows:
        root, trace, is_root_trace = _get_oa_trace_from_extra(row.get("extra_json"))
        form_fields = trace.get("form_fields") or {}
        attachments = trace.get("oa_form_attachments") or extract_attachments_from_form_fields(form_fields)
        if not attachments:
            skipped_items.append({"batch_name": row.get("name"), "batch_no": row.get("batch_no"), "reason": "未找到发起表单附件"})
            continue

        approval_item = {
            "source_approval_no": row.get("source_approval_no") or trace.get("source_approval_no") or "",
            "source_instance_id": row.get("source_instance_id") or trace.get("source_instance_id") or "",
            "form_fields": form_fields,
            "oa_form_attachments": attachments,
        }
        sync_result = _sync_oa_form_attachments(
            batch_name=row.get("name"),
            version_name=row.get("current_version") or "",
            approval_item=approval_item,
        )
        total_created += int(sync_result.get("created_count") or 0)
        total_updated += int(sync_result.get("updated_count") or 0)

        if trace.get("oa_form_attachments") != attachments or int(row.get("source_attachment_count") or 0) != len(attachments):
            trace = {**trace, "oa_form_attachments": attachments}
            frappe.db.set_value(
                "Overseas Cost Batch",
                row.get("name"),
                {
                    "source_attachment_count": len(attachments),
                    "extra_json": _set_oa_trace_in_extra(root, trace, is_root_trace),
                },
                update_modified=False,
            )

        synced_items.append(
            {
                "batch_name": row.get("name"),
                "batch_no": row.get("batch_no"),
                "attachment_count": len(attachments),
                "attachment_sync": sync_result,
            }
        )

    if hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "dry_run": False,
        "scanned_count": len(rows),
        "synced_count": len(synced_items),
        "skipped_count": len(skipped_items),
        "created_count": total_created,
        "updated_count": total_updated,
        "items": synced_items,
        "skipped_items": skipped_items,
        "message": "已有 OA 批次的发起表单附件已登记；评论附件未纳入。",
    }


def _resolve_batch_source_instance_id(row: dict, trace: dict) -> str:
    return (
        _clean(row.get("source_instance_id"))
        or _clean(trace.get("source_instance_id"))
        or extract_dingtalk_instance_id(row.get("source_dingtalk_url"))
        or extract_dingtalk_instance_id(trace.get("source_dingtalk_url") or trace.get("open_url"))
    )


def refresh_existing_oa_logistics_details(
    limit: int | None = 200,
    *,
    target: str = "",
    batch_name: str = "",
    batch_no: str = "",
    source_approval_no: str = "",
    env_file: str | None = None,
    api_style: str = "auto",
    include_non_sea: bool = False,
    access_token: str = "",
) -> dict:
    """重拉已有国际物流 OA 批次详情，并按关联采购支出 OA 自动补采购字段。

    旧批次如果只保存了国际物流基础字段，没有保存 form_fields / linked_purchase_approvals，
    单独执行 sync_existing_linked_purchase_fields 会因为缺少关联采购支出入口而跳过。
    这个函数会先按 source_instance_id 回到钉钉重拉审批详情，再复用 save_sea_approvals_to_erp
    更新批次追溯、附件入口、基础物料行和采购单价/币种/货值。
    """

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法刷新已有 OA 批次详情。",
        }

    resolved_env_file = resolve_dingtalk_env_file(env_file)
    if resolved_env_file:
        load_env_file(resolved_env_file)
    resolved_api_style = _resolve_api_style(api_style)
    token = get_access_token(
        api_style=resolved_api_style,
        access_token=access_token or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
    )

    page_length = max(1, min(int(limit or 200), 1000))
    target_value = _clean(target)
    target_batch_name = _clean(batch_name)
    target_batch_no = _clean(batch_no)
    target_source_approval_no = _clean(source_approval_no)
    filters: dict[str, Any] = {"source_type": "oa_logistics"}
    or_filters: list[dict[str, str]] = []
    if target_value:
        or_filters.extend(
            [
                {"name": target_value},
                {"batch_no": target_value},
                {"source_approval_no": target_value},
            ]
        )
    elif target_batch_name:
        filters["name"] = target_batch_name
    else:
        if target_batch_no and target_source_approval_no:
            or_filters.extend(
                [
                    {"batch_no": target_batch_no},
                    {"source_approval_no": target_source_approval_no},
                ]
            )
        elif target_batch_no:
            filters["batch_no"] = target_batch_no
        elif target_source_approval_no:
            filters["source_approval_no"] = target_source_approval_no

    query_kwargs: dict[str, Any] = {
        "filters": filters,
        "fields": [
            "name",
            "batch_no",
            "waybill_no",
            "current_version",
            "source_approval_no",
            "source_instance_id",
            "source_dingtalk_url",
            "extra_json",
        ],
        "limit_page_length": page_length,
        "order_by": "modified desc",
    }
    if or_filters and not target_batch_name:
        query_kwargs["or_filters"] = or_filters
    rows = frappe.get_all("Overseas Cost Batch", **query_kwargs)

    refreshed_items: list[dict] = []
    skipped_items: list[dict] = []
    failed_items: list[dict] = []

    for row in rows:
        _root, trace, _is_root_trace = _get_oa_trace_from_extra(row.get("extra_json"))
        instance_id = _resolve_batch_source_instance_id(row, trace)
        if not instance_id:
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "reason": "缺少钉钉审批实例 ID，无法回到钉钉重拉详情",
                }
            )
            continue

        try:
            detail = get_process_instance_detail(
                token=token,
                process_instance_id=instance_id,
                api_style=resolved_api_style,
            )
            summary = summarize_approval(detail, process_instance_id=instance_id)
        except Exception as exc:
            failed_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "source_instance_id": instance_id,
                    "reason": str(exc),
                }
            )
            continue

        if is_hidden_approval_status(summary.get("approval_status")):
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "source_instance_id": instance_id,
                    "approval_status": summary.get("approval_status"),
                    "reason": "审批单已撤销或终止，不再刷新到成本表",
                }
            )
            continue

        if not include_non_sea and not is_sea_approval(summary.get("form_fields") or {}):
            skipped_items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "source_instance_id": instance_id,
                    "transport_mode_raw": summary.get("transport_mode_raw"),
                    "reason": "审批详情不是海运，未纳入本次刷新",
                }
            )
            continue

        summary["source_approval_no"] = summary.get("source_approval_no") or row.get("source_approval_no") or trace.get("source_approval_no") or ""
        summary["source_dingtalk_url"] = summary.get("source_dingtalk_url") or row.get("source_dingtalk_url") or trace.get("source_dingtalk_url") or ""
        summary["logistics_no"] = summary.get("logistics_no") or row.get("waybill_no") or row.get("batch_no") or ""
        refreshed_items.append(summary)

    save_result = save_sea_approvals_to_erp({"ok": True, "items": refreshed_items}) if refreshed_items else {
        "ok": True,
        "created_count": 0,
        "updated_count": 0,
        "unchanged_count": 0,
        "items": [],
        "skipped_items": [],
    }
    saved_items = save_result.get("items") or []
    purchase_updated_count = sum(int((item.get("purchase_sync") or {}).get("updated_count") or 0) for item in saved_items)
    purchase_changed_field_count = sum(int((item.get("purchase_sync") or {}).get("changed_field_count") or 0) for item in saved_items)
    linked_purchase_count = sum(int((item.get("purchase_sync") or {}).get("linked_purchase_count") or 0) for item in saved_items)
    attachment_count = sum(int((item.get("attachment_sync") or {}).get("attachment_count") or 0) for item in saved_items)

    return {
        "ok": bool(save_result.get("ok", True)) and not failed_items,
        "dry_run": False,
        "env_file_loaded": bool(resolved_env_file),
        "api_style": resolved_api_style,
        "target": {
            "target": target_value,
            "batch_name": target_batch_name,
            "batch_no": target_batch_no,
            "source_approval_no": target_source_approval_no,
        },
        "scanned_count": len(rows),
        "detail_count": len(refreshed_items),
        "saved_count": len(saved_items),
        "created_count": save_result.get("created_count", 0),
        "updated_count": save_result.get("updated_count", 0),
        "unchanged_count": save_result.get("unchanged_count", 0),
        "purchase_updated_count": purchase_updated_count,
        "purchase_changed_field_count": purchase_changed_field_count,
        "linked_purchase_count": linked_purchase_count,
        "attachment_count": attachment_count,
        "skipped_count": len(skipped_items) + int(save_result.get("skipped_count") or 0),
        "failed_count": len(failed_items),
        "items": saved_items,
        "skipped_items": skipped_items + (save_result.get("skipped_items") or []),
        "failed_items": failed_items,
        "message": (
            f"已重拉 {len(refreshed_items)} 条国际物流 OA 详情，并按关联采购支出 OA 同步采购字段；"
            f"采购字段更新 {purchase_updated_count} 行，变更 {purchase_changed_field_count} 个字段。"
        ),
    }


def refresh_oa_logistics_detail(
    target: str,
    limit: int | None = 50,
    *,
    env_file: str | None = None,
    api_style: str = "auto",
    include_non_sea: bool = False,
    access_token: str = "",
) -> dict:
    """Refresh one OA logistics batch by internal name, batch number, or approval number."""

    return refresh_existing_oa_logistics_details(
        limit=limit,
        target=target,
        env_file=env_file,
        api_style=api_style,
        include_non_sea=include_non_sea,
        access_token=access_token,
    )


def backfill_express_single_quote_freight_rules(limit: int | None = 500) -> dict:
    """为历史快递单补充“唯一明确物流报价”的运费分摊规则并重算。"""

    if frappe is None:
        return {"ok": False, "message": "当前未连接 Frappe。", "updated_count": 0, "skipped_count": 0}

    page_length = max(1, min(int(limit or 500), 5000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"transport_mode": "EXPRESS"},
        fields=["name", "batch_no", "current_version", "extra_json"],
        limit_page_length=page_length,
        order_by="modified desc",
    )
    updated_items: list[dict] = []
    skipped_items: list[dict] = []
    for row in rows:
        version_name = row.get("current_version") or _ensure_oa_trace_version(row["name"], row.get("batch_no") or row["name"])
        payload = _json_loads_dict(row.get("extra_json"))
        trace = payload.get("oa_logistics_trace") if isinstance(payload.get("oa_logistics_trace"), dict) else payload
        if not isinstance(trace, dict):
            skipped_items.append({"batch_name": row["name"], "reason": "缺少 OA 追溯数据"})
            continue
        candidates = trace.get("logistics_quote_candidates")
        if not isinstance(candidates, list):
            candidates = extract_logistics_quote_candidates_from_approval({"form_fields": trace.get("form_fields") or {}})
        valid_candidates = [candidate for candidate in candidates if _parse_money_amount((candidate or {}).get("amount")) is not None]
        if len(valid_candidates) != 1:
            skipped_items.append({"batch_name": row["name"], "reason": f"报价候选数量不是 1：{len(valid_candidates)}"})
            continue

        result = _sync_oa_logistics_allocation_rule(
            batch_name=row["name"],
            version_name=version_name,
            approval_item={
                "transport_mode": "EXPRESS",
                "logistics_quote_candidates": valid_candidates,
            },
        )
        recalculate_result = _recalculate_after_purchase_sync(
            batch_name=row["name"],
            version_name=version_name,
            purchase_sync={"ok": True, "updated_count": 0},
            logistics_fee_sync=result,
        )
        if result.get("action") in {"created", "updated"}:
            updated_items.append(
                {
                    "batch_name": row["name"],
                    "batch_no": row.get("batch_no"),
                    "rule_result": result,
                    "recalculate_result": recalculate_result,
                }
            )
        else:
            skipped_items.append({"batch_name": row["name"], "batch_no": row.get("batch_no"), "reason": result.get("reason") or result.get("action")})

    if updated_items and hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "scanned_count": len(rows),
        "updated_count": len(updated_items),
        "skipped_count": len(skipped_items),
        "updated_items": updated_items[:50],
        "skipped_items": skipped_items[:50],
    }


def detect_purchase_process_codes_from_existing_links(
    limit: int | None = 50,
    *,
    env_file: str | None = None,
    api_style: str = "auto",
    access_token: str = "",
) -> dict:
    """从已有国际物流批次的关联采购单里反查采购支出流程模板号。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法检测采购支出流程号。",
        }

    resolved_env_file = resolve_dingtalk_env_file(env_file)
    if resolved_env_file:
        load_env_file(resolved_env_file)
    resolved_api_style = _resolve_api_style(api_style)
    token = get_access_token(
        api_style=resolved_api_style,
        access_token=access_token or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
    )

    page_length = max(1, min(int(limit or 50), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=["name", "batch_no", "extra_json"],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    detected: dict[str, dict] = {}
    skipped_items: list[dict] = []
    failed_items: list[dict] = []
    for row in rows:
        _root, trace, _is_root_trace = _get_oa_trace_from_extra(row.get("extra_json"))
        linked_approvals = trace.get("linked_purchase_approvals") or []
        if not linked_approvals:
            skipped_items.append({"batch_name": row.get("name"), "batch_no": row.get("batch_no"), "reason": "没有关联采购支出单"})
            continue
        for linked in linked_approvals:
            instance_id = _clean(linked.get("source_instance_id") or linked.get("proc_inst_id") or linked.get("instance_id"))
            if not instance_id:
                skipped_items.append(
                    {
                        "batch_name": row.get("name"),
                        "batch_no": row.get("batch_no"),
                        "approval_no": linked.get("approval_no") or linked.get("source_approval_no"),
                        "reason": "关联采购支出单缺少实例 ID",
                    }
                )
                continue
            try:
                detail = get_process_instance_detail(token=token, process_instance_id=instance_id, api_style=resolved_api_style)
            except Exception as exc:
                failed_items.append(
                    {
                        "batch_name": row.get("name"),
                        "batch_no": row.get("batch_no"),
                        "source_instance_id": instance_id,
                        "reason": str(exc),
                    }
                )
                continue
            process_code = _clean(detail.get("processCode") or detail.get("process_code") or detail.get("processCodeValue"))
            title = _clean(detail.get("title") or detail.get("processInstanceTitle") or detail.get("process_instance_title"))
            if not process_code:
                skipped_items.append(
                    {
                        "batch_name": row.get("name"),
                        "batch_no": row.get("batch_no"),
                        "source_instance_id": instance_id,
                        "approval_title": title,
                        "reason": "采购支出详情里没有返回 processCode",
                    }
                )
                continue
            record = detected.setdefault(
                process_code,
                {
                    "process_code": process_code,
                    "approval_title": title,
                    "sample_instance_id": instance_id,
                    "sample_approval_no": linked.get("approval_no") or linked.get("source_approval_no") or "",
                    "count": 0,
                },
            )
            record["count"] += 1

    return {
        "ok": not failed_items,
        "dry_run": False,
        "env_file_loaded": bool(resolved_env_file),
        "api_style": resolved_api_style,
        "scanned_count": len(rows),
        "detected_count": len(detected),
        "items": list(detected.values()),
        "skipped_count": len(skipped_items),
        "failed_count": len(failed_items),
        "skipped_items": skipped_items,
        "failed_items": failed_items,
        "message": f"已从已有国际物流关联采购单中检测到 {len(detected)} 个采购支出流程号。",
    }


def sync_existing_linked_purchase_fields(limit: int | None = 200) -> dict:
    """给已有国际物流 OA 批次补关联采购支出 OA 的采购字段。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法同步已有批次采购字段。",
        }

    page_length = max(1, min(int(limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=[
            "name",
            "batch_no",
            "current_version",
            "source_approval_no",
            "source_instance_id",
            "extra_json",
        ],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    synced_items: list[dict] = []
    skipped_items: list[dict] = []
    total_updated = 0
    total_changed_fields = 0

    for row in rows:
        _root, trace, _is_root_trace = _get_oa_trace_from_extra(row.get("extra_json"))
        linked_approvals = trace.get("linked_purchase_approvals") or []
        if not linked_approvals:
            skipped_items.append({"batch_name": row.get("name"), "batch_no": row.get("batch_no"), "reason": "未找到关联采购支出审批"})
            continue

        approval_item = {
            "source_approval_no": row.get("source_approval_no") or trace.get("source_approval_no") or "",
            "source_instance_id": row.get("source_instance_id") or trace.get("source_instance_id") or "",
            "linked_purchase_approvals": linked_approvals,
        }
        purchase_sync = _sync_linked_purchase_fields(
            batch_name=row.get("name"),
            version_name=row.get("current_version") or "",
            approval_item=approval_item,
        )
        recalculate_sync = _recalculate_after_purchase_sync(
            batch_name=row.get("name"),
            version_name=row.get("current_version") or "",
            purchase_sync=purchase_sync,
        )
        total_updated += int(purchase_sync.get("updated_count") or 0)
        total_changed_fields += int(purchase_sync.get("changed_field_count") or 0)
        synced_items.append(
            {
                "batch_name": row.get("name"),
                "batch_no": row.get("batch_no"),
                "linked_purchase_count": len(linked_approvals),
                "purchase_sync": purchase_sync,
                "recalculate_sync": recalculate_sync,
            }
        )

    if hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "dry_run": False,
        "scanned_count": len(rows),
        "synced_count": len(synced_items),
        "skipped_count": len(skipped_items),
        "updated_count": total_updated,
        "changed_field_count": total_changed_fields,
        "items": synced_items,
        "skipped_items": skipped_items,
        "message": "已有国际物流 OA 批次已按关联采购支出 OA 尝试同步采购单价、币种和货值。",
    }


def save_sea_approvals_to_erp(result: dict) -> dict:
    """保存国际物流 OA，生成批次，并自动补关联采购支出 OA 的采购字段。

    国际物流 OA 负责批次头、物料基础行、附件记录和采购支出关联。
    采购支出 OA 负责补采购单价、采购币种、总货值。
    装箱单/凭证等附件后续继续补实际发货、重量、体积和税费。
    已有 SKU 明细不会被国际物流 OA 表单覆盖；采购支出 OA 有匹配结果时会直接写入采购字段。
    """

    raw_items = [item for item in result.get("items") or [] if isinstance(item, dict)]
    skipped_items: list[dict] = [
        {
            "reason": "审批单已撤销或终止，不进入成本表格",
            "source_approval_no": item.get("source_approval_no"),
            "source_instance_id": item.get("source_instance_id"),
            "approval_status": item.get("approval_status"),
        }
        for item in raw_items
        if is_hidden_approval_status(item.get("approval_status"))
    ]
    items = [item for item in raw_items if not is_hidden_approval_status(item.get("approval_status"))]
    preview = [build_batch_values_from_approval(item) for item in items]
    preview = [item for item in preview if item.get("batch_no")]
    if frappe is None:
        return {
            "ok": True,
            "dry_run": True,
            "message": "当前未连接 Frappe，仅返回钉钉国际物流审批批次追溯和基础物料行预览。",
            "total": len(raw_items),
            "valid_count": len(preview),
            "created_count": 0,
            "updated_count": 0,
            "unchanged_count": 0,
            "skipped_count": len(raw_items) - len(preview),
            "items": preview,
            "skipped_items": skipped_items,
        }

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    saved_items: list[dict] = []
    for item in items:
        values = build_batch_values_from_approval(item)
        if not values.get("batch_no"):
            skipped_items.append({"reason": "缺少批次号、审批编号和实例ID", "source_instance_id": item.get("source_instance_id")})
            continue
        def save_one_approval():
            existing_name = _resolve_existing_batch_name(values)
            if existing_name:
                saved_row = _update_oa_trace_batch(existing_name, values)
            else:
                saved_row = _create_oa_trace_batch(values)

            item_sync = _sync_oa_goods_items(
                batch_name=saved_row["batch_name"],
                version_name=saved_row.get("version_name") or "",
                approval_item=item,
                only_when_empty=True,
            )
            attachment_sync = _sync_oa_form_attachments(
                batch_name=saved_row["batch_name"],
                version_name=saved_row.get("version_name") or "",
                approval_item=item,
            )
            purchase_sync = _sync_linked_purchase_fields(
                batch_name=saved_row["batch_name"],
                version_name=saved_row.get("version_name") or "",
                approval_item=item,
            )
            logistics_fee_sync = _sync_oa_logistics_allocation_rule(
                batch_name=saved_row["batch_name"],
                version_name=saved_row.get("version_name") or "",
                approval_item=item,
            )
            recalculate_sync = _recalculate_after_purchase_sync(
                batch_name=saved_row["batch_name"],
                version_name=saved_row.get("version_name") or "",
                purchase_sync=purchase_sync,
                logistics_fee_sync=logistics_fee_sync,
            )
            _commit_oa_pull_progress()
            return saved_row, item_sync, attachment_sync, purchase_sync, logistics_fee_sync, recalculate_sync

        saved, item_sync, attachment_sync, purchase_sync, logistics_fee_sync, recalculate_sync = _run_with_database_retry(save_one_approval)

        if saved["action"] == "created":
            created_count += 1
        elif saved["action"] == "updated":
            updated_count += 1
        else:
            unchanged_count += 1
        saved.update(
            {
                "batch_no": values.get("batch_no"),
                "source_approval_no": values.get("source_approval_no"),
                "source_instance_id": values.get("source_instance_id"),
                "logistics_no": values.get("waybill_no"),
                "item_sync": item_sync,
                "attachment_sync": attachment_sync,
                "purchase_sync": purchase_sync,
                "logistics_fee_sync": logistics_fee_sync,
                "recalculate_sync": recalculate_sync,
            }
        )
        saved_items.append(saved)

    _commit_oa_pull_progress()

    return {
        "ok": True,
        "dry_run": False,
        "message": "钉钉国际物流审批已保存到批次；已生成/保留物料行、登记发起附件，并按关联采购支出 OA 同步采购单价、币种和货值，同时把明确的物流费用生成分摊规则。",
        "total": len(raw_items),
        "created_count": created_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "skipped_count": len(skipped_items),
        "items": saved_items,
        "skipped_items": skipped_items,
    }


def save_json_file_to_erp(input_path: str | Path) -> dict:
    path = Path(input_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"未找到钉钉拉取结果文件：{path}")
    return save_sea_approvals_to_erp(json.loads(path.read_text(encoding="utf-8")))


def save_json_file_to_erp_from_env() -> dict:
    input_path = _clean(os.environ.get("DINGTALK_PULL_INPUT")) or _clean(os.environ.get("DINGTALK_PULL_OUTPUT"))
    if not input_path:
        raise ValueError("请设置 DINGTALK_PULL_INPUT 或 DINGTALK_PULL_OUTPUT。")
    return save_json_file_to_erp(input_path)


def pull_logistics_approvals(
    *,
    process_code: str,
    start: str,
    end: str,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    include_raw: bool = False,
    include_all: bool = False,
    access_token: str = "",
    corp_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    app_key: str = "",
    app_secret: str = "",
    transport_modes: tuple[str, ...] | list[str] | str = ("SEA",),
) -> dict:
    """拉取并按运输方式筛选国际物流审批单，不写数据库。"""

    resolved_api_style = _resolve_api_style(api_style)
    resolved_list_api = _resolve_list_api_mode(list_api, resolved_api_style)
    resolved_transport_modes = _parse_transport_modes(transport_modes)
    start_time_ms = _parse_datetime_ms(start)
    end_time_ms = _parse_datetime_ms(end, end_of_day=True)
    token = get_access_token(
        api_style=resolved_api_style,
        access_token=access_token,
        corp_id=corp_id,
        client_id=client_id,
        client_secret=client_secret,
        app_key=app_key,
        app_secret=app_secret,
    )
    instance_ids = list_process_instance_ids(
        token=token,
        process_code=process_code,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        api_style=resolved_api_style,
        list_api=resolved_list_api,
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
    )
    if limit:
        instance_ids = instance_ids[:limit]

    all_items: list[dict] = []
    matched_items: list[dict] = []
    for instance_id in instance_ids:
        detail = get_process_instance_detail(token=token, process_instance_id=instance_id, api_style=resolved_api_style)
        summary = summarize_approval(detail, process_instance_id=instance_id, include_raw=include_raw)
        all_items.append(summary)
        if is_transport_approval(summary["form_fields"], resolved_transport_modes) and not is_hidden_approval_status(summary.get("approval_status")):
            matched_items.append(summary)

    transport_counts = {
        mode: sum(
            1
            for item in all_items
            if not is_hidden_approval_status(item.get("approval_status")) and item.get("transport_mode") == mode
        )
        for mode in TRANSPORT_MODE_LABELS
    }

    result = {
        "ok": True,
        "process_code": process_code,
        "api_style": resolved_api_style,
        "list_api": resolved_list_api,
        "transport_modes": list(resolved_transport_modes),
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "chunk_days": chunk_days,
        "total_instance_count": len(instance_ids),
        "detail_count": len(all_items),
        "transport_counts": transport_counts,
        "filtered_count": len(matched_items),
        "sea_count": transport_counts.get("SEA", 0),
        "items": matched_items,
    }
    if include_all:
        result["all_items"] = all_items
        result["non_matching_items"] = [item for item in all_items if item not in matched_items]
        result["non_sea_items"] = [item for item in all_items if item.get("transport_mode") != "SEA"]
    return result


def pull_sea_approvals(
    *,
    process_code: str,
    start: str,
    end: str,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    include_raw: bool = False,
    include_all: bool = False,
    access_token: str = "",
    corp_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    app_key: str = "",
    app_secret: str = "",
) -> dict:
    """拉取并筛选海运审批单，不写数据库。"""

    return pull_logistics_approvals(
        process_code=process_code,
        start=start,
        end=end,
        api_style=api_style,
        list_api=list_api,
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
        limit=limit,
        include_raw=include_raw,
        include_all=include_all,
        access_token=access_token,
        corp_id=corp_id,
        client_id=client_id,
        client_secret=client_secret,
        app_key=app_key,
        app_secret=app_secret,
        transport_modes=("SEA",),
    )


def pull_purchase_expense_approvals(
    *,
    process_code: str,
    start: str,
    end: str,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    include_raw: bool = False,
    include_running: bool = False,
    access_token: str = "",
    corp_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    app_key: str = "",
    app_secret: str = "",
) -> dict:
    """按采购支出流程批量拉取审批详情，并解析行级单价、币种、总金额。"""

    resolved_process_code = resolve_purchase_process_code(process_code)
    if not resolved_process_code:
        raise ValueError("缺少采购支出流程模板 process_code，请配置 DINGTALK_PURCHASE_PROCESS_CODE。")

    resolved_api_style = _resolve_api_style(api_style)
    resolved_list_api = _resolve_list_api_mode(list_api, resolved_api_style)
    start_time_ms = _parse_datetime_ms(start)
    end_time_ms = _parse_datetime_ms(end, end_of_day=True)
    token = get_access_token(
        api_style=resolved_api_style,
        access_token=access_token,
        corp_id=corp_id,
        client_id=client_id,
        client_secret=client_secret,
        app_key=app_key,
        app_secret=app_secret,
    )
    instance_ids = list_process_instance_ids(
        token=token,
        process_code=resolved_process_code,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        api_style=resolved_api_style,
        list_api=resolved_list_api,
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
    )
    if limit:
        instance_ids = instance_ids[:limit]

    items: list[dict] = []
    skipped_items: list[dict] = []
    for instance_id in instance_ids:
        detail = get_process_instance_detail(token=token, process_instance_id=instance_id, api_style=resolved_api_style)
        summary = summarize_purchase_approval(detail, process_instance_id=instance_id)
        if include_raw:
            summary["raw_instance"] = detail
        if is_hidden_approval_status(summary.get("approval_status")):
            skipped_items.append(
                {
                    "source_instance_id": summary.get("source_instance_id"),
                    "source_approval_no": summary.get("source_approval_no"),
                    "approval_status": summary.get("approval_status"),
                    "reason": "采购支出审批已撤销或终止",
                }
            )
            continue
        if not include_running and not is_completed_approval_status(summary.get("approval_status"), allow_empty=False):
            skipped_items.append(
                {
                    "source_instance_id": summary.get("source_instance_id"),
                    "source_approval_no": summary.get("source_approval_no"),
                    "approval_status": summary.get("approval_status"),
                    "approval_title": summary.get("approval_title"),
                    "reason": "采购支出审批未完成",
                }
            )
            continue
        if not summary.get("detail_row_count") and not _has_purchase_approval_keyword(summary.get("approval_title")):
            skipped_items.append(
                {
                    "source_instance_id": summary.get("source_instance_id"),
                    "source_approval_no": summary.get("source_approval_no"),
                    "approval_title": summary.get("approval_title"),
                    "reason": "未解析到采购支出明细行",
                }
            )
            continue
        summary["ok"] = True
        items.append(summary)

    return {
        "ok": True,
        "process_code": resolved_process_code,
        "api_style": resolved_api_style,
        "list_api": resolved_list_api,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "chunk_days": chunk_days,
        "total_instance_count": len(instance_ids),
        "detail_count": len(items),
        "skipped_count": len(skipped_items),
        "items": items,
        "skipped_items": skipped_items,
    }


def sync_purchase_expenses_from_process(
    *,
    process_code: str = "",
    start: str = "",
    end: str = "",
    env_file: str | None = None,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    batch_limit: int | None = 200,
    include_running: bool = False,
    access_token: str = "",
) -> dict:
    """从采购支出流程批量拉审批，并按物料编码/规格同步已有 OA 批次采购字段。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法批量同步采购支出 OA。",
        }

    resolved_env_file = resolve_dingtalk_env_file(env_file)
    if resolved_env_file:
        load_env_file(resolved_env_file)
    resolved_process_code = resolve_purchase_process_code(process_code)
    if not resolved_process_code:
        return {
            "ok": False,
            "dry_run": False,
            "env_file_loaded": bool(resolved_env_file),
            "message": "缺少采购支出流程模板 process_code，请在环境变量配置 DINGTALK_PURCHASE_PROCESS_CODE 后再自动拉取。",
        }

    pull_result = pull_purchase_expense_approvals(
        process_code=resolved_process_code,
        start=start,
        end=end,
        api_style=_runtime_config_value("DINGTALK_API_STYLE", "overseas_costing_dingtalk_api_style", default=api_style),
        list_api=_runtime_config_value("DINGTALK_LIST_API", "overseas_costing_dingtalk_list_api", default=list_api),
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
        limit=limit,
        include_running=include_running,
        access_token=access_token or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
    )
    purchase_summaries = pull_result.get("items") or []
    if not purchase_summaries:
        return {
            "ok": True,
            "dry_run": False,
            "env_file_loaded": bool(resolved_env_file),
            "pull": pull_result,
            "scanned_count": 0,
            "updated_count": 0,
            "changed_field_count": 0,
            "message": "本次没有拉到可同步的采购支出 OA 明细。",
        }

    page_length = max(1, min(int(batch_limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=["name", "batch_no", "current_version"],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    from overseas_costing.services import import_service

    purchase_summaries_json = _json_dumps(purchase_summaries)
    synced_items: list[dict] = []
    total_updated = 0
    total_changed_fields = 0
    total_unmatched = 0
    total_ambiguous = 0
    for row in rows:
        purchase_sync = import_service.apply_linked_purchase_expense_fillable_fields(
            batch_name=row.get("name"),
            version_name=row.get("current_version") or "",
            purchase_summaries_json=purchase_summaries_json,
            recalculate_after_writeback=False,
        )
        recalculate_sync = _recalculate_after_purchase_sync(
            batch_name=row.get("name"),
            version_name=row.get("current_version") or "",
            purchase_sync=purchase_sync,
        )
        total_updated += int(purchase_sync.get("updated_count") or 0)
        total_changed_fields += int(purchase_sync.get("changed_field_count") or 0)
        total_unmatched += int(purchase_sync.get("unmatched_count") or 0)
        total_ambiguous += int(purchase_sync.get("ambiguous_count") or 0)
        synced_items.append(
            {
                "batch_name": row.get("name"),
                "batch_no": row.get("batch_no"),
                "purchase_sync": purchase_sync,
                "recalculate_sync": recalculate_sync,
            }
        )

    return {
        "ok": True,
        "dry_run": False,
        "env_file_loaded": bool(resolved_env_file),
        "pull": {
            **pull_result,
            "items": [
                {
                    "source_approval_no": item.get("source_approval_no"),
                    "source_instance_id": item.get("source_instance_id"),
                    "approval_title": item.get("approval_title"),
                    "detail_row_count": item.get("detail_row_count"),
                    "purchase_currency": item.get("purchase_currency"),
                }
                for item in purchase_summaries[:20]
            ],
        },
        "scanned_count": len(rows),
        "updated_count": total_updated,
        "changed_field_count": total_changed_fields,
        "unmatched_count": total_unmatched,
        "ambiguous_count": total_ambiguous,
        "items": synced_items,
        "message": (
            f"已拉取 {len(purchase_summaries)} 张采购支出 OA，并尝试同步 {len(rows)} 个国际物流批次；"
            f"采购字段更新 {total_updated} 行，变更 {total_changed_fields} 个字段。"
        ),
    }


def preview_purchase_expenses_from_process(
    *,
    process_code: str = "",
    start: str = "",
    end: str = "",
    env_file: str | None = None,
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int = 20,
    max_pages: int = 20,
    chunk_days: int = 30,
    limit: int | None = None,
    batch_limit: int | None = 200,
    include_running: bool = False,
    access_token: str = "",
) -> dict:
    """从采购支出流程拉明细，并预览可匹配到哪些已有 OA 批次；不写数据库。"""

    if frappe is None:
        return {
            "ok": False,
            "dry_run": True,
            "message": "当前未连接 Frappe，无法预览采购支出 OA 批量匹配。",
        }

    resolved_env_file = resolve_dingtalk_env_file(env_file)
    if resolved_env_file:
        load_env_file(resolved_env_file)
    resolved_process_code = resolve_purchase_process_code(process_code)
    if not resolved_process_code:
        return {
            "ok": False,
            "dry_run": False,
            "env_file_loaded": bool(resolved_env_file),
            "message": "缺少采购支出流程模板 process_code，请在环境变量配置 DINGTALK_PURCHASE_PROCESS_CODE 后再预览。",
        }

    pull_result = pull_purchase_expense_approvals(
        process_code=resolved_process_code,
        start=start,
        end=end,
        api_style=_runtime_config_value("DINGTALK_API_STYLE", "overseas_costing_dingtalk_api_style", default=api_style),
        list_api=_runtime_config_value("DINGTALK_LIST_API", "overseas_costing_dingtalk_list_api", default=list_api),
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
        limit=limit,
        include_running=include_running,
        access_token=access_token or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
    )
    purchase_summaries = pull_result.get("items") or []
    purchase_rows_preview: list[dict] = []
    for summary in purchase_summaries:
        source_approval_no = summary.get("source_approval_no") or ""
        source_instance_id = summary.get("source_instance_id") or ""
        source_dingtalk_url = summary.get("source_dingtalk_url") or ""
        for mapped_row in summary.get("mapped_preview_items") or []:
            if not isinstance(mapped_row, dict):
                continue
            purchase_rows_preview.append(
                {
                    "material_code": mapped_row.get("material_code"),
                    "product_name": mapped_row.get("product_name"),
                    "spec_model": mapped_row.get("spec_model"),
                    "quantity": mapped_row.get("quantity"),
                    "unit_price": mapped_row.get("unit_price"),
                    "goods_value": mapped_row.get("goods_value"),
                    "purchase_currency": mapped_row.get("purchase_currency") or summary.get("purchase_currency"),
                    "source_approval_no": mapped_row.get("source_approval_no") or source_approval_no,
                    "source_instance_id": mapped_row.get("source_instance_id") or source_instance_id,
                    "source_dingtalk_url": mapped_row.get("source_dingtalk_url") or source_dingtalk_url,
                }
            )
    if not purchase_summaries:
        return {
            "ok": True,
            "dry_run": False,
            "env_file_loaded": bool(resolved_env_file),
            "pull": {**pull_result, "items": []},
            "scanned_count": 0,
            "matched_batch_count": 0,
            "writable_batch_count": 0,
            "mapped_purchase_row_count": 0,
            "mapped_purchase_rows": [],
            "message": "本次没有拉到可预览的采购支出 OA 明细。",
        }

    page_length = max(1, min(int(batch_limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=["name", "batch_no", "current_version"],
        limit_page_length=page_length,
        order_by="modified desc",
    )

    from overseas_costing.services import import_service

    purchase_summaries_json = _json_dumps(purchase_summaries)
    items: list[dict] = []
    matched_batch_count = 0
    writable_batch_count = 0
    total_matched_rows = 0
    total_writable_rows = 0
    total_unmatched_rows = 0
    total_ambiguous_rows = 0

    for row in rows:
        preview = import_service.preview_linked_purchase_expense_oa(
            batch_name=row.get("name"),
            version_name=row.get("current_version") or "",
            purchase_summaries_json=purchase_summaries_json,
        )
        writeback = preview.get("writeback_preview") or {}
        matched_count = int(writeback.get("matched_count") or 0)
        writable_count = int(writeback.get("writable_row_count") or 0)
        unmatched_count = int(writeback.get("unmatched_count") or 0)
        ambiguous_count = int(writeback.get("ambiguous_count") or 0)
        if matched_count:
            matched_batch_count += 1
        if writable_count:
            writable_batch_count += 1
        total_matched_rows += matched_count
        total_writable_rows += writable_count
        total_unmatched_rows += unmatched_count
        total_ambiguous_rows += ambiguous_count
        if matched_count or writable_count:
            items.append(
                {
                    "batch_name": row.get("name"),
                    "batch_no": row.get("batch_no"),
                    "matched_count": matched_count,
                    "writable_row_count": writable_count,
                    "fillable_row_count": writeback.get("fillable_row_count", 0),
                    "conflict_row_count": writeback.get("conflict_row_count", 0),
                    "same_row_count": writeback.get("same_row_count", 0),
                    "unmatched_count": unmatched_count,
                    "ambiguous_count": ambiguous_count,
                    "matched_rows": [
                        {
                            "target_row_no": matched.get("target_row_no"),
                            "target_material_code": matched.get("target_material_code"),
                            "target_product_name": matched.get("target_product_name"),
                            "target_spec_model": matched.get("target_spec_model"),
                            "mapped_row": matched.get("mapped_row"),
                            "business_changes": matched.get("business_changes"),
                        }
                        for matched in (writeback.get("matched_rows") or [])[:10]
                    ],
                }
            )

    return {
        "ok": True,
        "dry_run": False,
        "env_file_loaded": bool(resolved_env_file),
        "pull": {
            **pull_result,
            "items": [
                _build_purchase_process_preview_row(item)
                for item in purchase_summaries[:20]
            ],
        },
        "scanned_count": len(rows),
        "matched_batch_count": matched_batch_count,
        "writable_batch_count": writable_batch_count,
        "purchase_summary_count": len(purchase_summaries),
        "mapped_purchase_row_count": len(purchase_rows_preview),
        "mapped_purchase_rows": purchase_rows_preview[:50],
        "matched_row_count": total_matched_rows,
        "writable_row_count": total_writable_rows,
        "unmatched_row_count": total_unmatched_rows,
        "ambiguous_row_count": total_ambiguous_rows,
        "items": items,
        "message": (
            f"已拉取 {len(purchase_summaries)} 张已完成采购支出 OA，预览匹配 {len(rows)} 个国际物流批次；"
            f"命中 {matched_batch_count} 个批次，{total_writable_rows} 行可写入。"
        ),
    }


def _build_purchase_process_preview_row(item: dict) -> dict:
    approval_no = item.get("source_approval_no") or ""
    instance_id = item.get("source_instance_id") or ""
    official_url = item.get("source_dingtalk_url") or ""
    dingtalk_payload = build_dingtalk_order_payload(
        approval_no=approval_no,
        instance_id=instance_id,
        official_url=official_url,
    )
    return {
        "source_approval_no": approval_no,
        "source_instance_id": instance_id,
        "source_dingtalk_url": official_url,
        "approval_title": item.get("approval_title"),
        "approval_status": item.get("approval_status"),
        "detail_row_count": item.get("detail_row_count"),
        "purchase_currency": item.get("purchase_currency"),
        "open_url": dingtalk_payload.get("open_url") or "",
        "open_mode": dingtalk_payload.get("open_mode") or "unavailable",
        "can_open": bool(dingtalk_payload.get("can_open")),
    }


def save_json(result: dict, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def save_csv(items: list[dict], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_instance_id",
        "source_approval_no",
        "source_dingtalk_url",
        "open_url",
        "approval_title",
        "approval_status",
        "originator_userid",
        "create_time",
        "finish_time",
        "transport_mode",
        "transport_mode_raw",
        "logistics_no",
        "linked_purchase_count",
        "oa_form_attachment_count",
        "linked_purchase_approval_nos",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            row = {fieldname: item.get(fieldname, "") for fieldname in fieldnames}
            linked_approvals = item.get("linked_purchase_approvals") or []
            row["linked_purchase_approval_nos"] = "；".join(
                _clean(linked.get("approval_no") or linked.get("source_approval_no"))
                for linked in linked_approvals
                if isinstance(linked, dict) and _clean(linked.get("approval_no") or linked.get("source_approval_no"))
            )
            writer.writerow(row)


def build_console_summary(result: dict, *, output: str = "", csv_output: str = "") -> dict:
    return {
        "ok": result.get("ok"),
        "process_code": result.get("process_code"),
        "api_style": result.get("api_style"),
        "list_api": result.get("list_api"),
        "chunk_days": result.get("chunk_days"),
        "total_instance_count": result.get("total_instance_count"),
        "detail_count": result.get("detail_count"),
        "transport_modes": result.get("transport_modes"),
        "transport_counts": result.get("transport_counts"),
        "filtered_count": result.get("filtered_count"),
        "sea_count": result.get("sea_count"),
        "output": output,
        "csv": csv_output,
        "preview": [
            {
                "source_approval_no": item.get("source_approval_no"),
                "source_instance_id": item.get("source_instance_id"),
                "transport_mode": item.get("transport_mode"),
                "transport_mode_raw": item.get("transport_mode_raw"),
                "logistics_no": item.get("logistics_no"),
                "approval_status": item.get("approval_status"),
                "linked_purchase_count": item.get("linked_purchase_count"),
                "oa_form_attachment_count": item.get("oa_form_attachment_count"),
            }
            for item in (result.get("items") or [])[:5]
        ],
    }


def pull_from_env() -> dict:
    """从环境变量读取参数，适合 bench execute 调试。"""

    load_env_file(os.environ.get("DINGTALK_ENV_FILE"))
    result = pull_logistics_approvals(
        process_code=resolve_logistics_process_code(),
        start=_clean(os.environ.get("DINGTALK_PULL_START")),
        end=_clean(os.environ.get("DINGTALK_PULL_END")),
        api_style=_clean(os.environ.get("DINGTALK_API_STYLE")) or "auto",
        list_api=_clean(os.environ.get("DINGTALK_LIST_API")) or "auto",
        page_size=int(os.environ.get("DINGTALK_PAGE_SIZE") or 20),
        max_pages=int(os.environ.get("DINGTALK_MAX_PAGES") or 20),
        chunk_days=int(os.environ.get("DINGTALK_CHUNK_DAYS") or 30),
        limit=int(os.environ.get("DINGTALK_LIMIT") or 0) or None,
        include_raw=os.environ.get("DINGTALK_INCLUDE_RAW") in ("1", "true", "True", "yes"),
        include_all=os.environ.get("DINGTALK_INCLUDE_ALL") in ("1", "true", "True", "yes"),
        transport_modes=os.environ.get("DINGTALK_TRANSPORT_MODES") or os.environ.get("DINGTALK_TRANSPORT_MODE") or "SEA",
    )
    output = _clean(os.environ.get("DINGTALK_PULL_OUTPUT"))
    csv_output = _clean(os.environ.get("DINGTALK_PULL_CSV"))
    if output:
        save_json(result, output)
    if csv_output:
        save_csv(result["items"], csv_output)
    return result


def diagnose_business_entity_from_env() -> dict:
    """只拉取钉钉审批详情并诊断业务主体字段，不写入数据库。"""

    load_env_file(os.environ.get("DINGTALK_ENV_FILE"))
    result = pull_logistics_approvals(
        process_code=resolve_logistics_process_code(),
        start=_clean(os.environ.get("DINGTALK_PULL_START")),
        end=_clean(os.environ.get("DINGTALK_PULL_END")),
        api_style=_clean(os.environ.get("DINGTALK_API_STYLE")) or "auto",
        list_api=_clean(os.environ.get("DINGTALK_LIST_API")) or "auto",
        page_size=int(os.environ.get("DINGTALK_PAGE_SIZE") or 20),
        max_pages=int(os.environ.get("DINGTALK_MAX_PAGES") or 20),
        chunk_days=int(os.environ.get("DINGTALK_CHUNK_DAYS") or 30),
        limit=int(os.environ.get("DINGTALK_LIMIT") or 1) or 1,
        include_raw=True,
        include_all=True,
        transport_modes=os.environ.get("DINGTALK_TRANSPORT_MODES") or os.environ.get("DINGTALK_TRANSPORT_MODE") or "SEA",
    )
    items = result.get("items") or []
    first = items[0] if items else {}
    extra_json = first.get("extra_json") or {}
    subsidiary = extra_json.get("subsidiary") if isinstance(extra_json, dict) else {}
    return {
        "ok": bool(result.get("ok")),
        "total_instance_count": result.get("total_instance_count", 0),
        "detail_count": result.get("detail_count", 0),
        "filtered_count": result.get("filtered_count", 0),
        "first_item": {
            "source_instance_id": first.get("source_instance_id") or "",
            "source_approval_no": first.get("source_approval_no") or "",
            "approval_title": first.get("approval_title") or "",
            "transport_mode": first.get("transport_mode") or "",
            "subsidiary_code": first.get("subsidiary_code") or "",
            "business_entity_name": subsidiary.get("business_entity_name") or "",
            "business_entity_id": subsidiary.get("business_entity_id") or "",
            "source_field": subsidiary.get("source_field") or "",
            "form_field_keys": sorted((first.get("form_fields") or {}).keys())[:80],
            "business_entity_candidates": _collect_business_entity_debug_candidates(first),
            "raw_form_component_count": len(first.get("raw_form_components") or []),
        },
    }


def pull_purchase_expenses_from_env() -> dict:
    """从环境变量拉采购支出 OA 预览，不写数据库，适合 bench execute 调试。"""

    resolved_env_file = resolve_dingtalk_env_file()
    if resolved_env_file:
        load_env_file(resolved_env_file)
    start = (
        _clean(os.environ.get("DINGTALK_PURCHASE_PULL_START"))
        or _clean(os.environ.get("DINGTALK_PULL_START"))
        or "2026-01-01"
    )
    end = (
        _clean(os.environ.get("DINGTALK_PURCHASE_PULL_END"))
        or _clean(os.environ.get("DINGTALK_PULL_END"))
        or datetime.now().strftime("%Y-%m-%d")
    )
    limit = int(os.environ.get("DINGTALK_PURCHASE_PULL_LIMIT") or os.environ.get("DINGTALK_LIMIT") or 5)
    include_running = os.environ.get("DINGTALK_PURCHASE_INCLUDE_RUNNING") in ("1", "true", "True", "yes")
    result = pull_purchase_expense_approvals(
        process_code=resolve_purchase_process_code(),
        start=start,
        end=end,
        api_style=_runtime_config_value("DINGTALK_API_STYLE", "overseas_costing_dingtalk_api_style", default="auto"),
        list_api=_runtime_config_value("DINGTALK_LIST_API", "overseas_costing_dingtalk_list_api", default="auto"),
        page_size=_runtime_config_int("DINGTALK_PAGE_SIZE", default=20),
        max_pages=_runtime_config_int("DINGTALK_MAX_PAGES", default=20),
        chunk_days=_runtime_config_int("DINGTALK_CHUNK_DAYS", default=30),
        limit=limit or None,
        include_running=include_running,
        access_token=_runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
    )
    return {
        **result,
        "env_file_loaded": bool(resolved_env_file),
        "preview_items": [
            {
                "source_approval_no": item.get("source_approval_no"),
                "source_instance_id": item.get("source_instance_id"),
                "approval_title": item.get("approval_title"),
                "approval_status": item.get("approval_status"),
                "purchase_currency": item.get("purchase_currency"),
                "detail_row_count": item.get("detail_row_count"),
                "mapped_preview_items": [
                    {
                        "material_code": row.get("material_code"),
                        "product_name": row.get("product_name"),
                        "spec_model": row.get("spec_model"),
                        "quantity": row.get("quantity"),
                        "unit_price": row.get("unit_price"),
                        "goods_value": row.get("goods_value"),
                        "purchase_currency": row.get("purchase_currency"),
                    }
                    for row in (item.get("mapped_preview_items") or [])[:5]
                ],
            }
            for item in (result.get("items") or [])[:5]
        ],
        "items": [],
    }


def pull_and_save_to_erp_from_env() -> dict:
    """从钉钉拉取国际物流审批，并保存为 ERP 批次追溯记录。"""

    result = pull_from_env()
    save_result = save_sea_approvals_to_erp(result)
    return {
        "ok": save_result.get("ok"),
        "pull": build_console_summary(
            result,
            output=_clean(os.environ.get("DINGTALK_PULL_OUTPUT")),
            csv_output=_clean(os.environ.get("DINGTALK_PULL_CSV")),
        ),
        "save": save_result,
    }


def pull_latest_logistics_approvals_to_erp(
    *,
    start: str | None = "",
    end: str | None = "",
    transport_modes: tuple[str, ...] | list[str] | str = "ALL",
    limit: int | None = 200,
    env_file: str | None = None,
    process_code: str | None = "",
    api_style: str = "auto",
    list_api: str = "auto",
    page_size: int | None = None,
    max_pages: int | None = None,
    chunk_days: int | None = None,
    access_token: str = "",
) -> dict:
    """手动拉取指定时间范围内的国际物流 OA，并保存/更新为成本批次。

    该入口给前端“钉钉拉取”使用；不清空历史批次，不删除已有明细。
    新审批单会创建批次，已有审批单只补追溯、附件、采购字段和明确费用规则。
    """

    resolved_env_file = resolve_dingtalk_env_file(env_file)
    env_file_loaded = False
    if resolved_env_file:
        load_env_file(resolved_env_file)
        env_file_loaded = True

    if not _has_dingtalk_pull_credentials() and not _clean(access_token):
        return {
            "ok": True,
            "skipped": True,
            "reason": "未配置钉钉拉取凭据，本次未执行拉取。",
            "env_file_loaded": env_file_loaded,
        }

    resolved_start = _clean(start)
    resolved_end = _clean(end)
    if not resolved_start or not resolved_end:
        default_start, default_end = _build_scheduled_pull_window()
        resolved_start = resolved_start or default_start
        resolved_end = resolved_end or default_end

    pull_result = pull_logistics_approvals(
        process_code=resolve_logistics_process_code(
            process_code
            or _runtime_config_value(
                "DINGTALK_LOGISTICS_PROCESS_CODE",
                "overseas_costing_dingtalk_logistics_process_code",
            )
        ),
        start=resolved_start,
        end=resolved_end,
        api_style=api_style or _runtime_config_value("DINGTALK_API_STYLE", "overseas_costing_dingtalk_api_style", default="auto"),
        list_api=list_api or _runtime_config_value("DINGTALK_LIST_API", "overseas_costing_dingtalk_list_api", default="auto"),
        page_size=page_size
        or _runtime_config_int("DINGTALK_SCHEDULE_PAGE_SIZE", "DINGTALK_PAGE_SIZE", default=20),
        max_pages=max_pages
        or _runtime_config_int("DINGTALK_SCHEDULE_MAX_PAGES", "DINGTALK_MAX_PAGES", default=20),
        chunk_days=chunk_days
        or _runtime_config_int("DINGTALK_SCHEDULE_CHUNK_DAYS", "DINGTALK_CHUNK_DAYS", default=30),
        limit=limit or None,
        include_raw=False,
        include_all=False,
        access_token=access_token or _runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
        corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
        client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
        client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
        app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
        app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
        transport_modes=transport_modes or "ALL",
    )
    save_result = save_sea_approvals_to_erp(pull_result)
    summary = {
        "ok": bool(save_result.get("ok")),
        "manual": True,
        "env_file_loaded": env_file_loaded,
        "start": resolved_start,
        "end": resolved_end,
        "transport_modes": pull_result.get("transport_modes"),
        "pull": {
            "total_instance_count": pull_result.get("total_instance_count", 0),
            "detail_count": pull_result.get("detail_count", 0),
            "transport_counts": pull_result.get("transport_counts", {}),
            "filtered_count": pull_result.get("filtered_count", 0),
        },
        "save": {
            "created_count": save_result.get("created_count", 0),
            "updated_count": save_result.get("updated_count", 0),
            "unchanged_count": save_result.get("unchanged_count", 0),
            "skipped_count": save_result.get("skipped_count", 0),
            "message": save_result.get("message"),
        },
        "items": (save_result.get("items") or [])[:20],
        "skipped_items": (save_result.get("skipped_items") or [])[:20],
    }
    _log_scheduled_pull_summary(summary)
    return summary


def _build_scheduled_pull_window() -> tuple[str, str]:
    start = _runtime_config_value(
        "DINGTALK_SCHEDULE_PULL_START",
        "overseas_costing_dingtalk_schedule_pull_start",
    )
    end = _runtime_config_value(
        "DINGTALK_SCHEDULE_PULL_END",
        "overseas_costing_dingtalk_schedule_pull_end",
    )
    if start and end:
        return start, end

    lookback_days = max(
        _runtime_config_int(
            "DINGTALK_SCHEDULE_LOOKBACK_DAYS",
            "overseas_costing_dingtalk_schedule_lookback_days",
            default=30,
        ),
        1,
    )
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days - 1)
    return start or start_date.strftime("%Y-%m-%d"), end or end_date.strftime("%Y-%m-%d")


def _log_scheduled_pull_summary(summary: dict) -> None:
    if frappe is None:
        return
    try:
        logger = frappe.logger("overseas_costing", allow_site=True) if hasattr(frappe, "logger") else None
        if logger:
            logger.info(_json_dumps(summary))
    except Exception:
        return


def _log_scheduled_pull_error(exc: Exception) -> None:
    if frappe is None or not hasattr(frappe, "log_error"):
        return
    try:
        message = frappe.get_traceback() if hasattr(frappe, "get_traceback") else str(exc)
        frappe.log_error(title="海外成本钉钉自动拉取失败", message=message)
    except Exception:
        return


def scheduled_pull_logistics_approvals() -> dict:
    """Frappe 定时任务：每天自动拉取最近几天的国际物流 OA 并写入/更新批次。"""

    try:
        if _runtime_config_bool(
            "DINGTALK_SCHEDULE_DISABLED",
            "overseas_costing_dingtalk_schedule_disabled",
            default=False,
        ):
            return {"ok": True, "skipped": True, "reason": "钉钉国际物流自动拉取已关闭。"}

        env_file = resolve_dingtalk_env_file(
            _runtime_config_value(
                "DINGTALK_SCHEDULE_ENV_FILE",
                "DINGTALK_ENV_FILE",
                "overseas_costing_dingtalk_env_file",
            )
        )
        env_file_loaded = False
        if env_file:
            load_env_file(env_file)
            env_file_loaded = True

        if not _has_dingtalk_pull_credentials():
            return {"ok": True, "skipped": True, "reason": "未配置钉钉拉取凭据，自动拉取跳过。", "env_file_loaded": env_file_loaded}

        start, end = _build_scheduled_pull_window()
        transport_modes = _runtime_config_value(
            "DINGTALK_SCHEDULE_TRANSPORT_MODES",
            "DINGTALK_TRANSPORT_MODES",
            "DINGTALK_TRANSPORT_MODE",
            "overseas_costing_dingtalk_schedule_transport_modes",
            default="ALL",
        )
        result = pull_logistics_approvals(
            process_code=resolve_logistics_process_code(
                _runtime_config_value(
                    "DINGTALK_LOGISTICS_PROCESS_CODE",
                    "overseas_costing_dingtalk_logistics_process_code",
                )
            ),
            start=start,
            end=end,
            api_style=_runtime_config_value("DINGTALK_API_STYLE", "overseas_costing_dingtalk_api_style", default="auto"),
            list_api=_runtime_config_value("DINGTALK_LIST_API", "overseas_costing_dingtalk_list_api", default="auto"),
            page_size=_runtime_config_int("DINGTALK_SCHEDULE_PAGE_SIZE", "DINGTALK_PAGE_SIZE", default=20),
            max_pages=_runtime_config_int("DINGTALK_SCHEDULE_MAX_PAGES", "DINGTALK_MAX_PAGES", default=20),
            chunk_days=_runtime_config_int("DINGTALK_SCHEDULE_CHUNK_DAYS", "DINGTALK_CHUNK_DAYS", default=30),
            limit=_runtime_config_int(
                "DINGTALK_SCHEDULE_LIMIT",
                "overseas_costing_dingtalk_schedule_limit",
                default=200,
            )
            or None,
            include_raw=False,
            include_all=False,
            access_token=_runtime_config_value("DINGTALK_ACCESS_TOKEN", "overseas_costing_dingtalk_access_token"),
            corp_id=_runtime_config_value("DINGTALK_CORP_ID", "overseas_costing_dingtalk_corp_id"),
            client_id=_runtime_config_value("DINGTALK_CLIENT_ID", "overseas_costing_dingtalk_client_id"),
            client_secret=_runtime_config_value("DINGTALK_CLIENT_SECRET", "overseas_costing_dingtalk_client_secret"),
            app_key=_runtime_config_value("DINGTALK_APP_KEY", "DINGTALK_APPKEY", "overseas_costing_dingtalk_app_key"),
            app_secret=_runtime_config_value("DINGTALK_APP_SECRET", "DINGTALK_APPSECRET", "overseas_costing_dingtalk_app_secret"),
            transport_modes=transport_modes,
        )
        save_result = save_sea_approvals_to_erp(result)
        summary = {
            "ok": bool(save_result.get("ok")),
            "scheduled": True,
            "env_file_loaded": env_file_loaded,
            "start": start,
            "end": end,
            "transport_modes": result.get("transport_modes"),
            "pull": {
                "total_instance_count": result.get("total_instance_count", 0),
                "detail_count": result.get("detail_count", 0),
                "transport_counts": result.get("transport_counts", {}),
                "filtered_count": result.get("filtered_count", 0),
            },
            "save": {
                "created_count": save_result.get("created_count", 0),
                "updated_count": save_result.get("updated_count", 0),
                "unchanged_count": save_result.get("unchanged_count", 0),
                "skipped_count": save_result.get("skipped_count", 0),
                "message": save_result.get("message"),
            },
        }
        _log_scheduled_pull_summary(summary)
        return summary
    except Exception as exc:
        _log_scheduled_pull_error(exc)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="拉取钉钉国际物流审批单并按运输方式筛选")
    parser.add_argument("--env-file", default=os.environ.get("DINGTALK_ENV_FILE", ""), help="加载指定 .env，例如预算管理系统 server\\.env")
    parser.add_argument("--process-code", default="", help=f"国际物流审批流程模板 process_code，默认 {DEFAULT_LOGISTICS_PROCESS_CODE}")
    parser.add_argument("--start", default=os.environ.get("DINGTALK_PULL_START", ""), help="开始时间，例如 2026-07-01")
    parser.add_argument("--end", default=os.environ.get("DINGTALK_PULL_END", ""), help="结束时间，例如 2026-07-21")
    parser.add_argument("--api-style", choices=["auto", "new", "legacy"], default=os.environ.get("DINGTALK_API_STYLE", "auto"), help="钉钉 token/详情接口风格，默认自动判断")
    parser.add_argument("--list-api", choices=["auto", "old", "new", "both"], default=os.environ.get("DINGTALK_LIST_API", "auto"), help="审批实例列表接口，预算系统默认 old，也可 both")
    parser.add_argument("--access-token", default=os.environ.get("DINGTALK_ACCESS_TOKEN", ""), help="已有 access_token，可选")
    parser.add_argument("--corp-id", default=os.environ.get("DINGTALK_CORP_ID", ""), help="新版 OpenAPI corp_id")
    parser.add_argument("--client-id", default=os.environ.get("DINGTALK_CLIENT_ID", ""), help="新版 OpenAPI client_id")
    parser.add_argument("--client-secret", default=os.environ.get("DINGTALK_CLIENT_SECRET", ""), help="新版 OpenAPI client_secret")
    parser.add_argument("--app-key", default=os.environ.get("DINGTALK_APP_KEY", ""), help="旧版或兼容 app_key")
    parser.add_argument("--app-secret", default=os.environ.get("DINGTALK_APP_SECRET", ""), help="旧版或兼容 app_secret")
    parser.add_argument("--page-size", type=int, default=int(os.environ.get("DINGTALK_PAGE_SIZE") or 20), help="每页数量，钉钉通常最大 20")
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("DINGTALK_MAX_PAGES") or 20), help="最多拉取页数，避免误拉过大范围")
    parser.add_argument("--chunk-days", type=int, default=int(os.environ.get("DINGTALK_CHUNK_DAYS") or 30), help="按多少天分段拉取，旧版钉钉接口建议 30")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("DINGTALK_LIMIT") or 0), help="最多读取多少个实例详情，0 表示不限制")
    parser.add_argument("--transport-mode", default=os.environ.get("DINGTALK_TRANSPORT_MODES") or os.environ.get("DINGTALK_TRANSPORT_MODE") or "SEA", help="运输方式：SEA、AIR、EXPRESS、ALL，可用逗号分隔")
    parser.add_argument("--include-raw", action="store_true", help="JSON 中包含完整审批详情原文")
    parser.add_argument("--include-all", action="store_true", help="JSON 中同时包含未命中当前运输方式的审批摘要，便于调试字段名")
    parser.add_argument("--output", default=os.environ.get("DINGTALK_PULL_OUTPUT", ""), help="输出 JSON 路径")
    parser.add_argument("--csv", default=os.environ.get("DINGTALK_PULL_CSV", ""), help="输出 CSV 路径")
    parser.add_argument("--save-to-erp", action="store_true", help="保存海运审批追溯到 Frappe 批次头；不写物料和金额")
    return parser


def main() -> None:
    _preload_env_file_from_argv(sys.argv[1:])
    args = build_parser().parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    result = pull_logistics_approvals(
        process_code=resolve_logistics_process_code(args.process_code),
        start=args.start,
        end=args.end,
        api_style=args.api_style,
        list_api=args.list_api,
        page_size=args.page_size,
        max_pages=args.max_pages,
        chunk_days=args.chunk_days,
        limit=args.limit or None,
        include_raw=args.include_raw,
        include_all=args.include_all,
        access_token=args.access_token,
        corp_id=args.corp_id,
        client_id=args.client_id,
        client_secret=args.client_secret,
        app_key=args.app_key,
        app_secret=args.app_secret,
        transport_modes=args.transport_mode,
    )
    if args.output:
        save_json(result, args.output)
    if args.csv:
        save_csv(result["items"], args.csv)
    if args.save_to_erp:
        save_result = save_sea_approvals_to_erp(result)
        printable = {
            "ok": save_result.get("ok"),
            "pull": build_console_summary(result, output=args.output, csv_output=args.csv),
            "save": save_result,
        }
    else:
        printable = build_console_summary(result, output=args.output, csv_output=args.csv) if args.output or args.csv else result
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
