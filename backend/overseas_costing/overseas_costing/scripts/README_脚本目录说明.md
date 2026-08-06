# 脚本目录说明

适用目录：`overseas_costing/scripts`

## 文件清单

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `import_oa_logistics.py` | 钉钉国际物流审批拉取脚本 | 按流程模板和时间范围拉审批单，先筛选海运，只输出本地 JSON/CSV，不写 ERP |
| `import_excel_workbook.py` | 通用Excel工作簿导入脚本 | 预览/导入真实 xlsx，支持自动识别 `2026年YUEWEI` 或国际物流审批附件明细 |
| `import_parsed_excel_blocks.py` | 已解析Excel块导入脚本 | 从 `frontend-demo/excel-imported-blocks.js` 导入 `2026年YUEWEI` 普通海运批次；默认排除“海运双清” |
| `recalculate_batch.py` | 批次重算脚本 | 调用正式重算服务，支持 bench execute 或命令行调试单个批次 |
| `compare_manual_excel_baseline.py` | 人工Excel对照脚本 | 读取人工核算表指定批次，与系统当前批次试算结果生成 xlsx 对照表 |
| `restore_hpcu_demo.py` | HPCU5155607演示批次恢复脚本 | `restore` 按装箱单解析恢复；`restore_manual_baseline` 按人工核算表 22 行恢复经理演示基准版 |
| `test_dingtalk_order_link.py` | 钉钉跳转测试脚本 | 本地验证审批实例链接和钉钉唤起链接生成 |

## 当前约定

1. 脚本适合做调试和一次性处理
2. 正式业务流程仍应优先走 API + service
3. 一期普通海运解析数据可先执行 `preview_2026_yuewei_sea` 预览，再执行 `import_2026_yuewei_sea` 导入
4. 单批次重算可执行 `OVERSEAS_COST_BATCH=HPCU5155607 bench --site development.localhost execute overseas_costing.scripts.recalculate_batch.recalculate_from_env`
5. 任意真实 Excel 可先执行 `OVERSEAS_COST_EXCEL_FILE=/path/to/file.xlsx bench --site development.localhost execute overseas_costing.scripts.import_excel_workbook.preview_from_env` 预览，再执行 `import_from_env` 导入
6. 演示对照表可执行 `OVERSEAS_COST_BATCH=HPCU5155607 bench --site development.localhost execute overseas_costing.scripts.compare_manual_excel_baseline.build_hpcu_manual_comparison_from_env`
7. 如果经理演示需要和历史人工核算表口径一致，可执行 `bench --site development.localhost execute overseas_costing.scripts.restore_hpcu_demo.restore_manual_baseline`，它会把 HPCU5155607 恢复为人工核算表 22 行基准版，同时保留装箱单、完税凭证和人工表作为追溯附件。

## 钉钉国际物流审批拉取

最小目标：先拉一批 `国际物流 Logística Internacional` 审批单，筛出物流方式为海运的记录，保留审批实例 ID、审批编号、钉钉原单链接、审批状态、柜号/运单号等追溯字段。

当前脚本还会从国际物流表单的 `关联审批单Asociar órdenes de compra.` 控件中读取隐藏的 `businessId / procInstId`，把关联采购支出审批单保存到输出 JSON 的 `linked_purchase_approvals` 中。后续补采购单价、币种、货值时，应优先使用这些关联采购支出审批单。

本脚本默认不会写入 ERP/Frappe，只输出本地文件；确认数据正确后，可以再显式执行保存入口导入追溯字段。

可以直接复用预算管理系统的 `.env`，例如本机：

```powershell
python -m overseas_costing.scripts.import_oa_logistics `
  --env-file "E:\Yuewei开发\预算管理系统\dingtalk-budget-main\server\.env" `
  --start 2026-07-01 `
  --end 2026-07-21 `
  --output data/dingtalk_sea_approvals.json `
  --csv data/dingtalk_sea_approvals.csv
```

说明：

1. 国际物流流程号已内置为 `PROC-RIYJTXWV-CN52YRK70C5499JG0TJ03-3GSSHZQJ-5`。
2. 预算管理系统 `.env` 只复用 `DINGTALK_APP_KEY / DINGTALK_APP_SECRET` 等连接信息；里面的 `DINGTALK_PROCESS_CODE` 不作为本脚本默认流程号，避免误拉预算审批流。
3. 本脚本默认 `--api-style auto`，会自动识别旧版 appKey/appSecret 配置。
4. `DINGTALK_LIST_API=old/new/both` 会控制审批实例列表接口，预算系统默认走 old。
5. 详情接口会先尝试新版详情，失败后回退旧版详情，和预算管理系统保持一致。

确认拉取结果没问题后，如果只想把审批单作为“可回溯批次头”保存到本地 Frappe，可以在 bench 环境执行：

```bash
cd ~/frappe-bench
DINGTALK_PULL_INPUT=/mnt/e/Yuewei开发/海外采购综合成本核算项目/overseas-cost/data/dingtalk_sea_approvals_2026.json \
bench --site development.localhost execute overseas_costing.scripts.import_oa_logistics.save_json_file_to_erp_from_env
```

这一步保存批次头追溯字段和当前版本；如果批次还没有 SKU 明细，会用 OA 表单里的基础物料清单生成第一轮明细。已有批次不会用 OA 表单覆盖 SKU 明细，不写单价、费用和税费。已有批次只补空的审批编号、实例 ID、钉钉链接等追溯字段；审批状态、附件数量、关联采购审批追溯这类非金额字段允许刷新。

如果后续换成新版 OpenAPI 环境变量：

```powershell
$env:DINGTALK_CORP_ID="dingxxx"
$env:DINGTALK_CLIENT_ID="your_client_id"
$env:DINGTALK_CLIENT_SECRET="your_client_secret"
$env:DINGTALK_LOGISTICS_PROCESS_CODE="PROC-xxxx"
```

拉取示例：

```powershell
python -m overseas_costing.scripts.import_oa_logistics `
  --process-code $env:DINGTALK_LOGISTICS_PROCESS_CODE `
  --start 2026-07-01 `
  --end 2026-07-21 `
  --output data/dingtalk_sea_approvals.json `
  --csv data/dingtalk_sea_approvals.csv
```

如果已经手动拿到 `access_token`，也可以直接：

```powershell
python -m overseas_costing.scripts.import_oa_logistics `
  --access-token "access_token_here" `
  --process-code "PROC-xxxx" `
  --start 2026-07-01 `
  --end 2026-07-21
```
