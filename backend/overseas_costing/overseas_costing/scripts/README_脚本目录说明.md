# 脚本目录说明

适用目录：`overseas_costing/scripts`

## 文件清单

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `import_oa_logistics.py` | OA导入脚本骨架 | 后续做一次性导入或调试导入 |
| `import_parsed_excel_blocks.py` | 已解析Excel块导入脚本 | 从 `frontend-demo/excel-imported-blocks.js` 导入 `2026年YUEWEI` 普通海运批次；默认排除“海运双清” |
| `recalculate_batch.py` | 批次重算脚本骨架 | 后续做命令行重算或批量重算 |
| `test_dingtalk_order_link.py` | 钉钉跳转测试脚本 | 本地验证审批实例链接和钉钉唤起链接生成 |

## 当前约定

1. 脚本适合做调试和一次性处理
2. 正式业务流程仍应优先走 API + service
3. 一期普通海运解析数据可先执行 `preview_2026_yuewei_sea` 预览，再执行 `import_2026_yuewei_sea` 导入
