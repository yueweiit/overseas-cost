# 后端目录规划与用途

适用目录：`backend`

当前这个目录已经开始落第一版 Frappe / Python 后端骨架。

## 当前用途

1. 作为正式后端开发入口
2. 放 Frappe 自定义 app
3. 放导入服务、成本计算服务、重算服务、回写服务
4. 放后端中文文件说明，便于后续开发接手

## 当前目录结构

| 当前目录/文件 | 中文名 | 用途 |
| --- | --- | --- |
| `00_后端文件中文说明.md` | 后端文件总说明 | 查看所有后端文件的中文名和用途 |
| `overseas_costing/` | Frappe应用根目录 | 后续正式 app 主体 |
| `overseas_costing/overseas_costing/api/` | 接口目录 | 放导入、查询、保存、重算、回写接口 |
| `overseas_costing/overseas_costing/services/` | 服务目录 | 放计算逻辑、映射、汇率、分摊等服务 |
| `overseas_costing/overseas_costing/doctype/` | 单据模型目录 | 放批次、版本、SKU、规则、附件、日志骨架 |
| `overseas_costing/overseas_costing/page/` | 页面目录 | 预留 Frappe 页面入口 |
| `overseas_costing/overseas_costing/tests/` | 测试目录 | 放纯函数测试和后续集成测试 |
| `overseas_costing/overseas_costing/scripts/` | 辅助脚本目录 | 放一次性导入脚本和重算脚本骨架 |

## 当前建议优先级

1. 先完善 DocType JSON 和字段定义
2. 再接 OA / Excel 导入
3. 再做成本重算
4. 最后接前端整表接口
