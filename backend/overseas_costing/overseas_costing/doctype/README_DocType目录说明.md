# DocType 目录说明

适用目录：`overseas_costing/doctype`

## 当前核心 DocType

| 目录 | 中文名 | 用途 |
| --- | --- | --- |
| `overseas_cost_batch` | 海外成本批次主单 | 表示一票海运/空运/快递批次主单 |
| `overseas_cost_version` | 海外成本版本单 | 表示暂估版/实际版/调整版 |
| `overseas_cost_item` | 海外成本明细行 | 表示单行 SKU / 物料成本明细 |
| `overseas_cost_allocation_rule` | 海外成本分摊规则 | 表示每个费用池的分摊规则 |
| `overseas_cost_attachment` | 海外成本附件单 | 表示附件、凭证、解析任务登记 |
| `overseas_cost_audit_log` | 海外成本审计日志 | 表示编辑、重算、版本切换日志 |

## 每个 DocType 目录内文件用途

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `*.json` | DocType 元数据定义 | 定义字段、权限、列表展示、排序等 |
| `*.py` | DocType 控制器 | 放校验逻辑和后续单据行为 |
| `__init__.py` | 包入口文件 | 让 Frappe / Python 识别目录 |

## 当前阶段说明

这一版 JSON 先放“第一版最小字段骨架”，
后续会继续根据：

1. Excel A~BE 字段
2. OA 国际物流单映射
3. 版本、留痕、回写需求

继续补全字段。
