# 海外采购综合成本核算

海外采购综合成本核算是一个 Frappe / ERPNext 应用模块，用于归集钉钉国际物流 OA、采购支出 OA、Excel、发起附件、补传资料和完税凭证等来源数据，辅助财务核算采购货值、物流费用、税费、分摊金额、综合成本和综合物品单价。

## 功能概览

- 国际物流 OA 批次拉取和钉钉原单跳转
- 报关/来源单层级列表和 SKU 明细展开
- 海运、空运、快递三种运输方式筛选
- 发起附件查看、预览、下载和补传资料归集
- 采购支出 OA 关联和采购单价、币种、货值写入
- Excel 导入和结构化文件解析预览
- 采购货值、物流费用、税费和综合单价试算
- 完税凭证金额对比和人工差异处理记录
- 字段修改记录和数据来源追溯

## 运输方式

| 运输方式 | 资料重点 | 当前口径 |
| --- | --- | --- |
| 海运 | 装箱单、提单/运单、商业发票、报关资料、货代账单、清关资料、完税凭证 | 主核算场景，支持批次、SKU、费用分摊和综合单价试算 |
| 空运 | 空运运单、装箱单、商业发票、报关资料、空运账单、清关资料、完税凭证 | 已支持独立筛选、资料清单和数据检查，空运费按单票费用进入核算 |
| 快递 | 快递面单/运单、货品明细、商业发票、快递账单、双清费用、付款/对账凭证、完税凭证（如有） | 已支持独立筛选、资料清单和数据检查，费用以快递账单、双清费用或 OA 明确费用为准 |

快递、双清类单据不一定都有正式完税凭证；没有可靠来源的数据可以留空，由财务查看原件后人工确认或修改。

## 技术栈

- Frappe / ERPNext
- Python
- JavaScript / CSS
- MariaDB
- 钉钉 OA OpenAPI
- openpyxl

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `backend/overseas_costing` | Frappe app 正式代码 |
| `archive` | 历史归档文件 |
| `data` | 本地测试样例目录，不提交正式数据 |
| `docs` | 本地开发文档目录，已加入 `.gitignore`，不上传 GitHub |
| `frontend-demo` | 本地早期前端 Demo，已加入 `.gitignore`，不作为正式交付代码 |
| `00_目录与文件中文说明.md` | 本地目录说明 |

## 安装

本项目不是独立网站，需要安装到已有 Frappe bench 中。

```bash
cd ~/frappe-bench
bench get-app https://github.com/yueweiit/overseas-cost.git
bench --site 你的站点名 install-app overseas_costing
bench --site 你的站点名 migrate
bench build --app overseas_costing
bench --site 你的站点名 clear-cache
```

安装后访问：

```text
/app/overseas-cost-workbench
```

## 配置

钉钉对接配置不提交到仓库。部署环境需要自行准备：

- 钉钉 AppKey
- 钉钉 AppSecret
- 国际物流流程 Code
- 采购支出流程 Code
- 可下载审批附件的钉钉 UserID

具体配置方式以目标 Frappe 站点环境为准，不要把 `.env`、密钥、真实附件或真实业务数据提交到 GitHub。

## 本地开发

当前本地开发路径：

```text
E:\Yuewei开发\海外采购综合成本核算项目\overseas-cost
```

当前 WSL Frappe app 运行副本：

```text
/home/frappe/frappe-bench/apps/overseas_costing
```

本地开发站点：

```text
http://development.localhost:8000/app/overseas-cost-workbench
```

本地代码改完后，需要同步到 WSL 的 Frappe app，并重新构建资源：

```bash
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
  /mnt/e/Yuewei开发/海外采购综合成本核算项目/overseas-cost/backend/overseas_costing/ \
  /home/frappe/frappe-bench/apps/overseas_costing/

cd /home/frappe/frappe-bench
bench build --app overseas_costing
bench --site development.localhost clear-cache
```

如果 DocType 字段有变化，执行：

```bash
bench --site development.localhost reload-doc overseas_costing doctype overseas_cost_batch
bench --site development.localhost reload-doc overseas_costing doctype overseas_cost_item
bench --site development.localhost migrate
```

## 检查命令

前端语法检查：

```bash
node --check backend/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check backend/overseas_costing/overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
```

后端测试：

```bash
python -m pytest backend/overseas_costing/overseas_costing/tests/test_dingtalk.py backend/overseas_costing/overseas_costing/tests/test_import_service.py
```

## 开发注意事项

- 提交信息统一使用中文。
- 页面文件目前有两份重复路径，修改工作台 JS / CSS 时需要保持同步。
- `docs/`、`frontend-demo/`、本地测试数据、`.env` 和密钥不上传 GitHub。
- 杂乱图片、截图、合同、聊天记录等附件只做归集和人工复核，不直接自动写入金额字段。
- 测试数据不要作为正式数据长期保留。
