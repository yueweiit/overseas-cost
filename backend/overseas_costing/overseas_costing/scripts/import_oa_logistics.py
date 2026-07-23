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
from datetime import datetime, time as dt_time
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
from overseas_costing.utils.field_mapper import map_oa_row_to_item, map_purchase_expense_row_to_item

NEW_TOKEN_PATH = "/v1.0/oauth2/{corp_id}/token"
NEW_LIST_INSTANCE_IDS_PATH = "/v1.0/workflow/processes/instanceIds/query"
NEW_INSTANCE_DETAIL_PATH = "/v1.0/workflow/processInstances?processInstanceId={process_instance_id}"
NEW_APPROVAL_ATTACHMENT_DOWNLOAD_PATH = "/v1.0/workflow/processInstances/spaces/files/urls/download"

LEGACY_TOKEN_PATH = "/gettoken"
LEGACY_LIST_INSTANCE_IDS_PATH = "/topapi/processinstance/listids?access_token={access_token}"
LEGACY_INSTANCE_DETAIL_PATH = "/topapi/processinstance/get?access_token={access_token}"

DEFAULT_SEA_KEYWORDS = ("海运", "SEA", "OCEAN", "MARITIMO", "MARÍTIMO")
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
GOODS_TABLE_FIELD_ALIASES = ("货物信息", "Bienes")
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

    return (
        _clean(process_code)
        or _clean(os.environ.get("DINGTALK_LOGISTICS_PROCESS_CODE"))
        or DEFAULT_LOGISTICS_PROCESS_CODE
    )


def resolve_purchase_process_code(process_code: str | None = "") -> str:
    """解析采购支出流程号。

    采购支出流程没有安全默认值，必须显式传入或配置环境变量，避免误把预算/其它审批流当采购来源。
    """

    process_codes = _parse_json_text(_clean(os.environ.get("DINGTALK_PROCESS_CODES")))
    purchase_code_from_list = ""
    if isinstance(process_codes, list) and len(process_codes) > 1:
        purchase_code_from_list = _clean(process_codes[1])

    return (
        _clean(process_code)
        or _clean(os.environ.get("DINGTALK_PURCHASE_PROCESS_CODE"))
        or _clean(os.environ.get("DINGTALK_PURCHASE_EXPENSE_PROCESS_CODE"))
        or purchase_code_from_list
    )


def _api_url() -> str:
    return (_clean(os.environ.get("DINGTALK_API_URL")) or "https://api.dingtalk.com").rstrip("/")


def _oapi_url() -> str:
    return (_clean(os.environ.get("DINGTALK_OAPI_URL")) or "https://oapi.dingtalk.com").rstrip("/")


def _resolve_api_style(api_style: str = "auto") -> str:
    requested = (_clean(api_style) or "auto").lower()
    if requested in ("legacy", "old"):
        return "legacy"
    if requested == "new":
        return "new"
    if requested != "auto":
        raise ValueError(f"不支持的钉钉接口风格：{api_style}")

    has_new = bool(_clean(os.environ.get("DINGTALK_CORP_ID")) and _clean(os.environ.get("DINGTALK_CLIENT_ID")))
    has_legacy = bool(_clean(os.environ.get("DINGTALK_APP_KEY")) and _clean(os.environ.get("DINGTALK_APP_SECRET")))
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

    token = _clean(access_token) or _clean(os.environ.get("DINGTALK_ACCESS_TOKEN"))
    if token:
        return token

    resolved_api_style = _resolve_api_style(api_style)

    if resolved_api_style == "legacy":
        resolved_app_key = _clean(app_key) or _clean(os.environ.get("DINGTALK_APP_KEY"))
        resolved_app_secret = _clean(app_secret) or _clean(os.environ.get("DINGTALK_APP_SECRET"))
        if not resolved_app_key or not resolved_app_secret:
            raise ValueError("旧版钉钉接口需要 DINGTALK_APP_KEY 和 DINGTALK_APP_SECRET。")
        query = urlencode({"appkey": resolved_app_key, "appsecret": resolved_app_secret})
        result = _request_json(f"{_oapi_url()}{LEGACY_TOKEN_PATH}?{query}", api_style="legacy")
        _ensure_dingtalk_success(result, api_style="legacy")
        return _clean(result.get("access_token"))

    resolved_corp_id = _clean(corp_id) or _clean(os.environ.get("DINGTALK_CORP_ID"))
    resolved_client_id = _clean(client_id) or _clean(os.environ.get("DINGTALK_CLIENT_ID")) or _clean(os.environ.get("DINGTALK_APP_KEY"))
    resolved_client_secret = _clean(client_secret) or _clean(os.environ.get("DINGTALK_CLIENT_SECRET")) or _clean(os.environ.get("DINGTALK_APP_SECRET"))
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
    requested = (_clean(list_api) or _clean(os.environ.get("DINGTALK_LIST_API")) or "auto").lower()
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


def get_process_attachment_download_url(*, token: str, process_instance_id: str, file_id: str) -> dict:
    """换取钉钉审批发起表单附件的临时下载地址。"""

    instance_id = _clean(process_instance_id)
    resolved_file_id = _clean(file_id)
    if not instance_id:
        raise ValueError("缺少钉钉审批实例 ID。")
    if not resolved_file_id:
        raise ValueError("缺少钉钉附件 file_id。")

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
    _ensure_dingtalk_success(result, api_style="new")
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
        "download_uri": download_uri,
        "raw_response": result,
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
    normalized_aliases = [_normalize_key(alias) for alias in aliases]
    for key, value in fields.items():
        normalized_key = _normalize_key(key)
        if any(alias and alias in normalized_key for alias in normalized_aliases):
            if value not in (None, ""):
                return value
    return ""


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
    for fieldname, value in (form_fields or {}).items():
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
    normalized = _normalize_key(transport_value).upper()
    return any(_normalize_key(keyword).upper() in normalized for keyword in sea_keywords)


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
        "transport_mode_raw": _find_field_value(fields, TRANSPORT_FIELD_ALIASES),
        "logistics_no": _find_field_value(fields, BATCH_NO_FIELD_ALIASES),
        "linked_purchase_count": len(linked_purchase_approvals),
        "linked_purchase_approvals": linked_purchase_approvals,
        "oa_form_attachment_count": len(oa_form_attachments),
        "oa_form_attachments": oa_form_attachments,
        "form_fields": fields,
    }
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


def extract_oa_goods_rows(item: dict) -> list[dict]:
    """从钉钉国际物流审批摘要中提取货物信息表格行。"""

    form_fields = item.get("form_fields") or {}
    goods_table = None
    for fieldname, value in form_fields.items():
        if _is_goods_table_field(fieldname):
            goods_table = _parse_json_text(value)
            break
    if not isinstance(goods_table, list):
        return []

    common_values = {
        "项目proyecto": form_fields.get("项目proyecto"),
        "物料类别TIPO": form_fields.get("物料类别TIPO"),
        "物流方式Camino Envío": item.get("transport_mode_raw"),
        "柜号/单号Número DE Logística": item.get("logistics_no"),
        "备注otro": form_fields.get("备注otro"),
    }
    rows: list[dict] = []
    for raw_row in goods_table:
        row = _flatten_dingtalk_table_row(raw_row)
        if not row:
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


def extract_purchase_expense_rows(instance: dict) -> list[dict]:
    """从采购支出 OA 详情里提取明细行，并补上表单级币种。"""

    currency = _find_component_value(instance, PURCHASE_CURRENCY_FIELD_ALIASES)
    rows: list[dict] = []
    fallback_rows: list[dict] = []
    for component in _iter_form_components(instance):
        name = _clean(component.get("name") or component.get("label") or component.get("id"))
        if _clean(component.get("componentType") or component.get("component_type")) != "TableField":
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

    return rows or fallback_rows


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
    return values


def build_batch_values_from_approval(item: dict) -> dict:
    """把一条海运审批摘要整理成批次头追溯字段。"""

    form_fields = item.get("form_fields") or {}
    logistics_no = _clean(item.get("logistics_no"))
    source_approval_no = _clean(item.get("source_approval_no"))
    source_instance_id = _clean(item.get("source_instance_id"))
    batch_no = _clean(_first_non_empty(logistics_no, source_approval_no, source_instance_id))
    source_dingtalk_url = _clean(item.get("source_dingtalk_url"))
    oa_form_attachments = item.get("oa_form_attachments") or extract_attachments_from_form_fields(form_fields)
    attachment_count = len(oa_form_attachments) if oa_form_attachments else _count_dingtalk_attachments(form_fields)
    values = {
        "batch_no": batch_no,
        "waybill_no": logistics_no,
        "container_no": logistics_no if _looks_like_container_no(logistics_no) else "",
        "transport_mode": "SEA",
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
                "transport_mode_raw": item.get("transport_mode_raw"),
                "open_url": item.get("open_url"),
                "linked_purchase_approvals": item.get("linked_purchase_approvals") or [],
                "oa_form_attachments": oa_form_attachments,
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
    always_refresh_fields = {"source_approval_status", "source_attachment_count", "source_finished_at"}
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
            "reason": "钉钉审批单未解析到货物信息表格。",
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
            doc = frappe.get_doc("Overseas Cost Attachment", existing_name)
            for fieldname, value in values.items():
                setattr(doc, fieldname, value)
            doc.save(ignore_permissions=True)
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


def _recalculate_after_purchase_sync(*, batch_name: str, version_name: str, purchase_sync: dict) -> dict:
    if frappe is None:
        return {"action": "skipped", "reason": "当前未连接 Frappe。"}
    if not purchase_sync.get("ok") or int(purchase_sync.get("updated_count") or 0) <= 0:
        return {"action": "skipped", "reason": "采购字段没有新增写入，暂不自动试算。"}
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
    token = get_access_token(api_style=resolved_api_style, access_token=access_token)

    page_length = max(1, min(int(limit or 200), 1000))
    rows = frappe.get_all(
        "Overseas Cost Batch",
        filters={"source_type": "oa_logistics"},
        fields=[
            "name",
            "batch_no",
            "waybill_no",
            "current_version",
            "source_approval_no",
            "source_instance_id",
            "source_dingtalk_url",
            "extra_json",
        ],
        limit_page_length=page_length,
        order_by="modified desc",
    )

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
    token = get_access_token(api_style=resolved_api_style, access_token=access_token)

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
            "message": "当前未连接 Frappe，仅返回钉钉海运审批批次追溯和基础物料行预览。",
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
        existing_name = _resolve_existing_batch_name(values)
        if existing_name:
            saved = _update_oa_trace_batch(existing_name, values)
        else:
            saved = _create_oa_trace_batch(values)

        if saved["action"] == "created":
            created_count += 1
        elif saved["action"] == "updated":
            updated_count += 1
        else:
            unchanged_count += 1
        item_sync = _sync_oa_goods_items(
            batch_name=saved["batch_name"],
            version_name=saved.get("version_name") or "",
            approval_item=item,
            only_when_empty=True,
        )
        attachment_sync = _sync_oa_form_attachments(
            batch_name=saved["batch_name"],
            version_name=saved.get("version_name") or "",
            approval_item=item,
        )
        purchase_sync = _sync_linked_purchase_fields(
            batch_name=saved["batch_name"],
            version_name=saved.get("version_name") or "",
            approval_item=item,
        )
        recalculate_sync = _recalculate_after_purchase_sync(
            batch_name=saved["batch_name"],
            version_name=saved.get("version_name") or "",
            purchase_sync=purchase_sync,
        )
        saved.update(
            {
                "batch_no": values.get("batch_no"),
                "source_approval_no": values.get("source_approval_no"),
                "source_instance_id": values.get("source_instance_id"),
                "logistics_no": values.get("waybill_no"),
                "item_sync": item_sync,
                "attachment_sync": attachment_sync,
                "purchase_sync": purchase_sync,
                "recalculate_sync": recalculate_sync,
            }
        )
        saved_items.append(saved)

    if hasattr(frappe.db, "commit"):
        frappe.db.commit()

    return {
        "ok": True,
        "dry_run": False,
        "message": "钉钉海运审批已保存到批次；已生成/保留物料行、登记发起附件，并按关联采购支出 OA 同步采购单价、币种和货值。",
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
    sea_items: list[dict] = []
    for instance_id in instance_ids:
        detail = get_process_instance_detail(token=token, process_instance_id=instance_id, api_style=resolved_api_style)
        summary = summarize_approval(detail, process_instance_id=instance_id, include_raw=include_raw)
        all_items.append(summary)
        if is_sea_approval(summary["form_fields"]) and not is_hidden_approval_status(summary.get("approval_status")):
            sea_items.append(summary)

    result = {
        "ok": True,
        "process_code": process_code,
        "api_style": resolved_api_style,
        "list_api": resolved_list_api,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "chunk_days": chunk_days,
        "total_instance_count": len(instance_ids),
        "detail_count": len(all_items),
        "sea_count": len(sea_items),
        "items": sea_items,
    }
    if include_all:
        result["all_items"] = all_items
        result["non_sea_items"] = [item for item in all_items if item not in sea_items]
    return result


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
        api_style=api_style,
        list_api=list_api,
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
        limit=limit,
        include_running=include_running,
        access_token=access_token,
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
        api_style=api_style,
        list_api=list_api,
        page_size=page_size,
        max_pages=max_pages,
        chunk_days=chunk_days,
        limit=limit,
        include_running=include_running,
        access_token=access_token,
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
        "sea_count": result.get("sea_count"),
        "output": output,
        "csv": csv_output,
        "preview": [
            {
                "source_approval_no": item.get("source_approval_no"),
                "source_instance_id": item.get("source_instance_id"),
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
    result = pull_sea_approvals(
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
    )
    output = _clean(os.environ.get("DINGTALK_PULL_OUTPUT"))
    csv_output = _clean(os.environ.get("DINGTALK_PULL_CSV"))
    if output:
        save_json(result, output)
    if csv_output:
        save_csv(result["items"], csv_output)
    return result


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
        api_style=_clean(os.environ.get("DINGTALK_API_STYLE")) or "auto",
        list_api=_clean(os.environ.get("DINGTALK_LIST_API")) or "auto",
        page_size=int(os.environ.get("DINGTALK_PAGE_SIZE") or 20),
        max_pages=int(os.environ.get("DINGTALK_MAX_PAGES") or 20),
        chunk_days=int(os.environ.get("DINGTALK_CHUNK_DAYS") or 30),
        limit=limit or None,
        include_running=include_running,
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
    """从钉钉拉取海运审批，并保存为 ERP 批次追溯记录。"""

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="拉取钉钉国际物流审批单并筛选海运")
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
    parser.add_argument("--include-raw", action="store_true", help="JSON 中包含完整审批详情原文")
    parser.add_argument("--include-all", action="store_true", help="JSON 中同时包含未命中海运的审批摘要，便于调试字段名")
    parser.add_argument("--output", default=os.environ.get("DINGTALK_PULL_OUTPUT", ""), help="输出 JSON 路径")
    parser.add_argument("--csv", default=os.environ.get("DINGTALK_PULL_CSV", ""), help="输出 CSV 路径")
    parser.add_argument("--save-to-erp", action="store_true", help="保存海运审批追溯到 Frappe 批次头；不写物料和金额")
    return parser


def main() -> None:
    _preload_env_file_from_argv(sys.argv[1:])
    args = build_parser().parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    result = pull_sea_approvals(
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
