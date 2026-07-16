"""
中文用途：后端全局常量定义文件。

后续所有状态枚举、版本类型、运输方式、分摊方式尽量统一从这里取值，
避免业务代码里散落硬编码字符串。
"""

TRANSPORT_MODES = ("SEA", "AIR", "EXPRESS")
TRANSPORT_MODE_LABELS = {
    "SEA": "海运",
    "AIR": "空运",
    "EXPRESS": "快递",
}

BATCH_STATUSES = (
    "Draft",
    "Imported",
    "Dirty",
    "Calculated",
    "Confirmed",
    "Writeback Failed",
    "Written Back",
)

BATCH_SOURCE_TYPES = (
    "excel",
    "oa_logistics",
    "erp_purchase",
    "manual",
    "attachment_parse",
)

BATCH_CONFIRM_STATUSES = ("Pending", "Partially Confirmed", "Confirmed")
BATCH_WRITEBACK_STATUSES = ("Not Started", "Pending", "Failed", "Success")

VERSION_TYPES = ("Estimated", "Actual", "Adjustment")
VERSION_SOURCE_TYPES = ("Import", "Clone", "Manual")

ALLOCATION_BASES = ("goods_value", "gross_weight", "volume")

AUDIT_ACTION_TYPES = (
    "IMPORT",
    "EDIT",
    "BATCH_EDIT",
    "RECALCULATE",
    "CREATE_VERSION",
    "SWITCH_VERSION",
    "UPLOAD_ATTACHMENT",
    "WRITEBACK",
)
