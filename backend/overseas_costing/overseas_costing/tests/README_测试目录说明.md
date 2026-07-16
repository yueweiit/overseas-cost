# 测试目录说明

适用目录：`overseas_costing/tests`

## 文件清单

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `test_currency.py` | 汇率工具测试 | 校验金额换算和保留位数 |
| `test_dingtalk.py` | 钉钉跳转工具测试 | 校验审批链接和唤起链接生成结果 |
| `test_field_mapper.py` | 字段映射测试 | 校验 OA 字段映射结果 |

## 当前约定

1. 先从纯函数测试开始
2. 后续再补 Frappe 集成测试
