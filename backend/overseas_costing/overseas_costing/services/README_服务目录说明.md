# 服务目录说明

适用目录：`overseas_costing/services`

## 文件清单

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `batch_service.py` | 批次服务 | 查批次、查明细、检查回写状态 |
| `category_service.py` | 商品品类归类服务 | 规则优先生成归类建议，预留 AI 分类接入点 |
| `import_service.py` | 导入服务 | 导入 Excel / OA 主表、登记附件 |
| `calculate_service.py` | 重算服务 | 编辑字段、批量更新、重算、切换版本 |
| `allocation_service.py` | 分摊服务 | 货值/重量/体积分摊规则占位 |
| `version_service.py` | 版本服务 | 版本摘要、版本复制辅助逻辑 |
| `audit_service.py` | 审计服务 | 写修改日志、重算日志、版本日志 |
| `attachment_parse_service.py` | 附件解析服务 | 装箱单解析任务、完税凭证 PDF 预览解析、解析快照保存、后续 OCR/AI 解析入口 |

## 当前约定

1. 真正的业务逻辑放服务层
2. API 层尽量不要直接算业务
3. 后续数据库读写优先从这里集中收口
