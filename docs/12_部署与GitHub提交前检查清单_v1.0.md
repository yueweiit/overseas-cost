# 部署与 GitHub 提交前检查清单 V1.0

更新时间：2026-07-16

## 1. 当前代码范围

本次建议以 `overseas-cost` 目录作为 Git 仓库根目录。

不建议把上级目录整体提交到 GitHub，因为上级目录还包含 `TEST独立版`、`TEST多模块版`、`初版`、`方案文档` 等历史资料和对照文件，容易把非交付内容混入正式仓库。

## 2. 提交前必须确认

1. 前端页面脚本语法检查通过。
2. 后端测试通过。
3. 本地代码已同步到 WSL Frappe 开发环境并完成 `bench build`。
4. 测试 Excel、临时导入文件、缓存文件不提交。
5. `.gitignore` 已覆盖 Python 缓存、Node 缓存、日志、数据库文件和 `data/*.xlsx` 等本地数据文件。

## 3. 测试数据处理

以下内容仅用于开发验证，不应进入生产 ERP 数据库：

1. `HPCU5155607` 测试批次。
2. `MVPSEA20260716A`、`MVPSEA20260716B` 测试批次。
3. `data/mvp_yuewei_import_test_20260716.xlsx` 测试 Excel。
4. 手工新增/删除物料产生的演示修改记录。

正式部署前，应在生产环境只导入真实业务 Excel 或真实 OA/凭证来源数据。

## 4. 当前验证命令

在 `overseas-cost` 目录执行：

```powershell
node --check backend\overseas_costing\overseas_costing\page\overseas_cost_workbench\overseas_cost_workbench.js
node --check backend\overseas_costing\overseas_costing\overseas_costing\page\overseas_cost_workbench\overseas_cost_workbench.js
```

在 `overseas-cost\backend\overseas_costing` 目录执行：

```powershell
python -m pytest -q
```

当前最近一次结果：`36 passed`。

## 5. WSL 开发环境同步命令

当前本地代码是主版本，WSL 中的 Frappe app 是运行版本。

```powershell
wsl -d Ubuntu -u frappe -- bash -lc 'set -e; cd ~/frappe-bench; rsync -a --exclude=__pycache__ --exclude="*.pyc" "/mnt/e/Yuewei开发/海外采购综合成本核算项目/overseas-cost/backend/overseas_costing/" apps/overseas_costing/; bench build --app overseas_costing; bench --site development.localhost clear-cache'
```

## 6. 正式 ERP 部署建议步骤

1. 生产 ERP 服务器先备份数据库和站点文件。
2. 在生产服务器拉取 GitHub 最新代码。
3. 将 Frappe app 更新到 bench 的 `apps/overseas_costing`。
4. 执行：

```bash
bench --site <site-name> migrate
bench build --app overseas_costing
bench --site <site-name> clear-cache
bench restart
```

5. 检查 DocType 字段是否已迁移。
6. 配置角色权限和页面入口。
7. 使用一票真实海运数据做验收。
8. 验收通过后再开放给业务用户。

## 7. 上线前业务确认项

1. 货值分摊费用池范围。
2. 重量分摊费用池范围。
3. 汇率来源和生效规则。
4. 海运双清是否纳入一期。
5. 修改后是否必须重算才能回写 ERP。
6. 删除批次在生产是否改为“作废”而非硬删除。
7. ERP 成本回写字段和触发时机。

## 8. GitHub 操作建议

首次提交建议只提交 `overseas-cost` 仓库。

当前处理建议：

1. `frontend-demo` 目录内有独立 `.git`，首次交付仓库暂不纳入，避免 GitHub 只提交成子模块指针。
2. 如后续确实要把 demo 一起提交，应先决定是保留为独立仓库，还是备份/移除 `frontend-demo/.git` 后作为普通目录纳入主仓库。
3. `data/*.xlsx`、`data/*.xlsm` 已默认忽略，测试 Excel 不随代码提交。

```powershell
cd E:\Yuewei开发\海外采购综合成本核算项目\overseas-cost
git status
git add .
git commit -m "feat: overseas cost MVP"
git branch -M main
git remote add origin <GitHub仓库地址>
git push -u origin main
```

如果 GitHub 仓库已经存在，应先确认远端地址和分支策略，再执行 `remote add` 或 `remote set-url`。
