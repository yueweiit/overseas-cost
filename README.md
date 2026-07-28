# 海外采购综合成本核算

本仓库用于开发海外采购综合成本核算模块。当前模块落在 Frappe/ERPNext 中，目标是把钉钉 OA、Excel、完税凭证等资料归集到同一批次下，完成采购货值、物流费用、税费、分摊金额和综合单价的核算，并保留可回溯的资料来源。

## 当前定位

一期先做最小可用闭环：

1. 从钉钉国际物流 OA 拉取报关/来源单批次。
2. 从钉钉采购支出 OA 或稳定附件补入采购单价、币种、采购金额等字段。
3. 对 Excel、结构化文本等规则清楚的数据做导入或字段补齐。
4. 对图片、截图、合同、聊天记录、杂乱 PDF 等发起附件，只做归集、预览、下载和人工复核，不自动写入成本字段。
5. 按采购货值、重量等规则分摊费用，生成综合成本和综合物品单价。
6. 后续用完税凭证做最终核对，处理多退少补差异，并保留人工处理记录。

核心原则：能结构化拉取的自动拉取；不确定的附件保留原件给财务复核；金额类字段不靠不稳定 OCR 自动覆盖。

## 当前已实现

- Frappe 工作台页面：`/app/overseas-cost-workbench`
- 报关/来源单层级列表，支持展开 SKU 明细。
- 钉钉审批单跳转，可回到对应钉钉原单。
- 钉钉国际物流 OA 拉取，已撤销审批单不展示。
- 发起附件清单、附件下载到本地、附件预览。
- 采购支出 OA 关联预览和字段写入逻辑。
- Excel 导入和文件解析预览入口。
- 采购货值、费用池、分摊金额、综合单价等试算逻辑。
- 完税凭证解析记录、系统金额对比、人工差异处理记录。
- 修改记录，支持查看字段从旧值改为新值。

## 明确不做的内容

当前不做“杂乱附件全自动解析并入库”。

原因是国际物流 OA 下的发起附件格式差异很大，可能包含微信截图、合同、报关资料、报价对比、图片、扫描件等。OCR 即使识别出文字，也无法稳定判断哪些字段应进入成本表。强行写入会污染核算数据，最后仍需人工复核。

当前处理方式是：系统自动归集资料，财务在系统内预览原件、下载原件、核对字段，确认后再用于成本核算。

## 目录说明

| 目录 | 用途 |
| --- | --- |
| `backend` | Frappe / Python / API / DocType / 计算服务正式代码 |
| `frontend-demo` | 早期独立版前端 Demo，主要用于对照交互和布局 |
| `docs` | PRD、字段口径、架构设计、计算逻辑、OA 映射等文档 |
| `data` | 测试样例、Excel 样例、导入实验数据 |
| `archive` | 旧页面、旧脚本、阶段性历史版本归档 |

## 运行环境

本地代码路径：

```text
E:\Yuewei开发\海外采购综合成本核算项目\overseas-cost
```

WSL 运行副本：

```text
/home/frappe/frappe-bench/apps/overseas_costing
```

Frappe bench：

```text
/home/frappe/frappe-bench
```

开发站点：

```text
http://development.localhost:8000/app/overseas-cost-workbench
```

## 常用操作

前端或后端代码改完后，需要同步到 WSL 的 Frappe app，再构建并清缓存：

```bash
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
  /mnt/e/Yuewei开发/海外采购综合成本核算项目/overseas-cost/backend/overseas_costing/ \
  /home/frappe/frappe-bench/apps/overseas_costing/

cd /home/frappe/frappe-bench
bench build --app overseas_costing
bench --site development.localhost clear-cache
```

如果 DocType 字段有变化，除 `bench migrate` 外，必要时需要 reload-doc：

```bash
bench --site development.localhost reload-doc overseas_costing doctype overseas_cost_batch
bench --site development.localhost reload-doc overseas_costing doctype overseas_cost_item
bench --site development.localhost migrate
```

## 验证命令

前端语法检查：

```bash
node --check backend/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check backend/overseas_costing/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
```

后端相关测试：

```bash
python -m pytest backend/overseas_costing/overseas_costing/tests/test_dingtalk.py backend/overseas_costing/overseas_costing/tests/test_import_service.py
```

## 开发注意事项

1. 页面文件有两份，需要同步修改：
   - `backend/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
   - `backend/overseas_costing/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`
   - CSS 同理也有两份。
2. 本地改完不代表 Frappe 页面已更新，必须同步到 WSL 并执行 build/clear-cache。
3. 提交信息统一使用中文。
4. 不要把测试假数据当成正式数据长期保留。
5. 不要把杂乱附件 OCR 结果直接写入金额字段，除非业务确认附件格式稳定且字段口径明确。

## 当前下一步

建议继续围绕 MVP 收口：

1. 稳定钉钉 OA 批次拉取和采购字段写入。
2. 补齐关键核算字段的来源说明和空值检查。
3. 保持附件原件可预览、可下载、可回溯。
4. 完善费用分摊和综合单价展示。
5. 用真实完税凭证做最终金额对比和人工差异处理。
