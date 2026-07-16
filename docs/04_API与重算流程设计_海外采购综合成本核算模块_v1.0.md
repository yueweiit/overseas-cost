# 首批 API 与重算流程设计：Frappe 版 V1.0

更新时间：2026-07-14

## 1. 文档目标

本文档用于输出“海外采购综合成本核算模块”一期首批 API 和重算流程设计，面向 Frappe 开发落地。

目标：

1. 明确首批需要暴露哪些接口
2. 明确每个接口负责什么
3. 明确重算流程如何走
4. 明确版本切换、留痕、回写如何串起来

---

## 2. 一期最小接口范围

一期建议只围绕 5 条主线暴露接口：

1. 批次查询
2. 导入建批次
3. 钉钉来源补数
4. 明细编辑与重算
5. 版本管理

---

## 3. 首批 API 清单

以下接口均建议放在：

`overseas_costing/api/`

并通过 `frappe.whitelist()` 暴露。

---

## 3.1 批次查询类

### 3.1.1 获取批次列表

#### 建议方法

`overseas_costing.api.batch.get_batch_list`

#### 入参

1. `batch_no`
2. `customs_no`
3. `waybill_no`
4. `transport_mode`
5. `status`
6. `version_type`
7. `page_no`
8. `page_size`

#### 出参

1. 批次基础信息
2. 当前版本
3. 当前状态
4. SKU 数
5. 综合成本摘要

---

### 3.1.2 获取批次详情

#### 建议方法

`overseas_costing.api.batch.get_batch_detail`

#### 入参

1. `batch_id`
2. `version_id` 可选

#### 出参

1. 批次主信息
2. 当前版本信息
3. 统计摘要
4. 分摊规则摘要

---

### 3.1.3 获取批次明细表

#### 建议方法

`overseas_costing.api.batch.get_batch_items`

#### 入参

1. `batch_id`
2. `version_id`
3. `customs_no`
4. `waybill_no`
5. `product_name`
6. `import_name`
7. `hs_code`
8. `category`
9. `keyword`

#### 出参

1. `A ~ BE` 顺序字段
2. 行明细
3. 命中数量

说明：

前端要求按 Excel 列顺序直接展示，所以这个接口返回顺序要稳定。

---

### 3.1.4 打开钉钉订单

#### 建议方法

`overseas_costing.api.batch.open_dingtalk_order`

#### 入参

1. `batch_name`

#### 作用

1. 后端读取批次上的 `source_instance_id` 与 `source_dingtalk_url`
2. 优先生成 `dingtalk://` PC 客户端唤起链接
3. 若实例 ID 缺失，则回退到钉钉官方网页链接
4. 前端按钮可直接把 href 指向该接口，无需自己拼接协议链接

#### 补充接口

`overseas_costing.api.batch.get_dingtalk_order_link`

用于前端先取 JSON 跳转信息，再自行控制打开方式。

---

## 3.2 导入类

### 3.2.1 导入主表并生成批次

#### 建议方法

`overseas_costing.api.import_api.import_main_excel`

#### 入参

1. 上传文件
2. `source_sheet`
3. `transport_mode`
4. `project_collection`
5. `version_type`

#### 核心动作

1. 读取 Excel
2. 识别 `2026年YUEWEI`
3. 提取海运块
4. 生成 `Batch`
5. 生成默认 `Version`
6. 生成 `Item`
7. 生成默认分摊规则
8. 自动触发首轮试算
9. 写入审计日志

#### 出参

1. 批次数
2. 明细数
3. 生成的 batch_id 列表

---

### 3.2.2 上传附件并挂到批次

#### 建议方法

`overseas_costing.api.import_api.upload_attachment`

#### 入参

1. `batch_id`
2. `version_id`
3. `attachment_type`
4. 文件

#### 出参

1. 附件 ID
2. 状态

---

### 3.2.3 从采购支出 OA 补采购单价

#### 建议方法

`overseas_costing.api.import_api.import_purchase_expense_oa`

#### 入参

1. `batch_id`
2. `source_instance_id` 或采购支出 OA 单号
3. `version_id`

#### 核心动作

1. 读取采购支出 OA 主表与明细
2. 匹配物料编码 / 采购单号
3. 回填采购单价、采购币种、总货值来源信息
4. 写入来源单号与解析日志
5. 将批次状态改为 `Dirty`

#### 出参

1. 成功匹配行数
2. 未匹配行数
3. 解析日志 ID

---

### 3.2.4 解析装箱单附件

#### 建议方法

`overseas_costing.api.import_api.parse_packing_list_attachment`

#### 入参

1. `batch_id`
2. `attachment_id`
3. `version_id`
4. `template_name` 可选

#### 核心动作

1. 读取钉钉附件中的装箱单
2. 解析 `实际发货数量 / 毛重 / 体积 / 体积重 / 计费重`
3. 按物料编码、规格、采购单号匹配明细行
4. 回填字段并记录解析来源
5. 对未识别行输出异常结果，等待人工修正
6. 将批次状态改为 `Dirty`

#### 出参

1. 成功匹配行数
2. 未匹配行数
3. 解析异常行
4. 解析日志 ID

---

## 3.3 编辑与重算类

### 3.3.1 更新单行明细字段

#### 建议方法

`overseas_costing.api.calculate.update_item_field`

#### 入参

1. `item_id`
2. `field_name`
3. `field_value`
4. `remark`

#### 核心动作

1. 校验是否允许编辑
2. 更新字段
3. 写审计日志
4. 将批次状态改为 `Dirty`

#### 说明

不建议前端直接整行全部覆盖，优先按字段修改，便于留痕。

---

### 3.3.2 批量更新字段

#### 建议方法

`overseas_costing.api.calculate.batch_update_items`

#### 适用场景

1. 导入修正
2. 批量改汇率
3. 批量改费用项

---

### 3.3.3 重新试算

#### 建议方法

`overseas_costing.api.calculate.recalculate_batch`

#### 入参

1. `batch_id`
2. `version_id`
3. `fx_usd_to_rmb`
4. `fx_rmb_to_mxn`
5. `recalculate_scope`
6. `remark`

#### 核心动作

1. 读取当前版本下全部明细
2. 读取当前版本分摊规则
3. 重新计算货值比 / 重量比 / 体积比
4. 重新计算费用分摊结果
5. 重写综合成本字段
6. 更新版本快照
7. 写审计日志

---

### 3.3.4 更新分摊规则

#### 建议方法

`overseas_costing.api.calculate.update_allocation_rule`

#### 入参

1. `rule_id`
2. `amount`
3. `currency`
4. `allocation_basis`
5. `is_enabled`

#### 核心动作

1. 更新规则
2. 写日志
3. 标记批次为 `Dirty`

---

## 3.4 版本类

### 3.4.1 获取版本列表

#### 建议方法

`overseas_costing.api.batch.get_version_list`

#### 入参

1. `batch_id`

#### 出参

1. 全部版本
2. 当前版本标记
3. 汇率快照
4. 摘要信息

---

### 3.4.2 创建新版本

#### 建议方法

`overseas_costing.api.calculate.create_version`

#### 入参

1. `batch_id`
2. `version_type`
3. `clone_from_version_id`
4. `remark`

#### 核心动作

1. 复制源版本
2. 复制规则
3. 复制明细
4. 创建新版本
5. 写日志

---

### 3.4.3 切换当前版本

#### 建议方法

`overseas_costing.api.calculate.switch_version`

#### 入参

1. `batch_id`
2. `target_version_id`

#### 核心动作

1. 更新当前版本指针
2. 写日志

---

## 3.5 回写类

一期可以先预留，不一定立即全做。

### 3.5.1 预检查是否允许回写

#### 建议方法

`overseas_costing.api.writeback.check_writeback_ready`

#### 检查内容

1. 是否已确认版本
2. 是否有当前版本
3. 是否还有脏数据未重算
4. 是否必填单据完整

---

### 3.5.2 执行 ERP 回写

#### 建议方法

`overseas_costing.api.writeback.writeback_to_erp`

#### 入参

1. `batch_id`
2. `version_id`

#### 核心动作

1. 汇总当前版本成本
2. 转成 ERP 需要的结构
3. 执行回写
4. 记录回写结果
5. 写日志

---

## 4. 重算流程设计

## 4.1 一期重算输入

重算的输入至少包括：

1. SKU 明细数据
2. 汇率快照
3. 分摊规则
4. 费用项金额
5. 毛重 / 货值 / 体积基础值

---

## 4.2 一期重算步骤

### 第一步：读取当前版本上下文

读取：

1. `Batch`
2. `Version`
3. `Item`
4. `Allocation Rule`

### 第二步：生成统计基数

计算：

1. 总货值
2. 总毛重
3. 总体积或总体积重

### 第三步：逐费用项计算分摊比例

例如：

1. 中国运输杂费按货值比
2. 海运费按重量比
3. 后续如果有体积费用则按体积比分摊

### 第四步：逐 SKU 回写计算结果

计算并回写：

1. `goods_value_ratio`
2. `weight_ratio`
3. `freight_alloc_rmb`
4. `freight_alloc_mxn`
5. `total_logistics_mxn`
6. `alloc_price_mxn`
7. `total_cost_rmb`
8. `total_unit_rmb`

### 第五步：更新版本摘要

例如：

1. 版本总成本
2. 版本总物流成本
3. 试算时间

### 第六步：写审计日志

记录：

1. 谁触发重算
2. 哪个版本
3. 使用了什么汇率
4. 使用了哪些规则

---

## 5. 一期推荐默认分摊逻辑

建议先写死为可配置默认规则：

1. `中国运输及相关杂费 RMB` 按 `货值`
2. `中国到墨西哥运费 RMB` 按 `重量`
3. `墨西哥内陆运输 / 杂费` 先按 `重量`

后面再开放成可视化规则配置。

---

## 6. 版本流转设计

建议版本流转如下：

1. 导入生成 `Estimated`
2. 编辑后重算仍在 `Estimated`
3. 财务确认后复制生成 `Actual`
4. 后续补差再生成 `Adjustment`

不要直接在一个版本上反复覆盖所有历史。

---

## 7. 状态流转设计

### 批次状态

1. `Draft`
2. `Imported`
3. `Dirty`
4. `Calculated`
5. `Confirmed`
6. `Written Back`
7. `Writeback Failed`

### 版本状态

1. `Active`
2. `Confirmed`
3. `Archived`

---

## 8. 权限建议

一期至少区分两类角色：

### 财务操作人

可：

1. 导入
2. 查看
3. 编辑
4. 重算
5. 创建版本
6. 确认版本

### 管理员 / ERP 对接人

可：

1. 维护规则
2. 执行回写
3. 查看全部日志

---

## 9. 异步任务建议

以下动作建议走 `frappe.enqueue`：

1. 大 Excel 导入
2. 大批次重算
3. 附件解析
4. ERP 回写

理由：

1. 避免页面阻塞
2. 避免请求超时
3. 便于记录任务状态

---

## 10. 一句话结论

一期不要一上来铺太多接口，优先把以下 4 件事做好：

1. 导入
2. 查询
3. 编辑 + 重算
4. 版本切换

只要这 4 条链路稳定，后面再接 ERP 回写和附件解析就会顺很多。
