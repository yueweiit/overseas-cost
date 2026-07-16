# 应用目录说明

适用目录：`backend/overseas_costing`

这是后续要接入 ERP 的 Frappe 自定义 app 根目录。

## 当前用途

1. 放 Frappe 标准 app 结构
2. 放海外采购综合成本核算模块后端代码
3. 放后续 DocType、API、服务和脚本

## 目录清单

| 路径 | 中文名 | 用途 |
| --- | --- | --- |
| `setup.py` | 安装配置文件 | 让 app 可被 Frappe/bench 识别和安装 |
| `modules.txt` | 模块声明文件 | 声明应用模块名 |
| `patches.txt` | 补丁登记文件 | 预留后续 patch |
| `requirements.txt` | 依赖文件 | 记录后续额外依赖 |
| `license.txt` | 许可证文件 | 当前先占位 |
| `overseas_costing/` | 应用 Python 包 | 正式后端代码主体 |
| `.gitignore` | Git忽略文件 | 忽略缓存、编译文件和测试输出 |

## 当前开发建议

1. 先从 `overseas_costing/doctype` 开始
2. 再补 `api`
3. 再补 `services`
4. 最后接 `page`
