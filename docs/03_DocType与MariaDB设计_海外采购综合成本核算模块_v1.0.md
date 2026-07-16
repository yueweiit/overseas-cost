# DocType 与数据库设计：海外采购综合成本核算模块 V1.0

更新时间：2026-07-07

## 1. 文档目标

本文档给开发使用，输出“海外采购综合成本核算模块”在 `Frappe + MariaDB` 技术栈下的一期数据模型设计。

目标：

1. 明确 DocType 结构
2. 明确各 DocType 的字段职责
3. 明确哪些字段必须独立建列
4. 明确哪些字段可进入 JSON 扩展区
5. 明确索引、版本、留痕、回写预留方式

---

## 2. 总体建模原则

## 2.1 推荐使用独立 DocType，而不是全部塞进一个主单

一期虽然页面看起来像“一张大表”，但数据库不能只做一张超大表。

建议拆成 6 个核心 DocType：

1. `Overseas Cost Batch`
2. `Overseas Cost Version`
3. `Overseas Cost Item`
4. `Overseas Cost Allocation Rule`
5. `Overseas Cost Attachment`
6. `Overseas Cost Audit Log`

## 2.2 SKU 明细建议用独立 DocType，不建议只用 Child Table

原因：

1. SKU 数量可能很多
2. 需要单独查询、筛选、编辑、留痕
3. 需要做版本复制和差异比对
4. 后面可能按 SKU 回写或联动 ERP 单据

因此：

`Overseas Cost Item` 建议做独立 DocType，用 Link 指向批次和版本。

## 2.3 关键查询字段要单独建列

例如：

1. 报关单号
2. 运单号
3. 产品名称
4. 海关进口名称
5. 海关分类编码
6. 大类
7. 运输方式
8. 版本类型

这些字段不能只存在 JSON 里，否则后期查询性能差，也不方便列表筛选。

## 2.4 Excel 全量列顺序信息要保留

虽然核心字段要拆列，但同时还要保留：

1. Excel 原始值
2. 扩展字段
3. 后续新加列兼容能力

建议：

1. 核心字段拆列
2. 全量 Excel 映射再放一个 JSON 字段

---

## 3. DocType 清单

## 3.1 Overseas Cost Batch

### 作用

表示一票海运批次的主单。

### 建议命名

`Overseas Cost Batch`

### 建议字段

#### 基础标识

1. `batch_no`
2. `customs_no`
3. `waybill_no`
4. `transport_mode`
5. `project_collection`

#### 来源追溯

6. `source_type`
7. `source_file_name`
8. `source_sheet`
9. `source_range`
10. `source_data_id`
11. `source_approval_no`
12. `source_instance_id`
13. `source_dingtalk_url`
14. `source_approval_status`
15. `source_title`
16. `source_creator_name`
17. `source_creator_dept`
18. `source_created_at`
19. `source_finished_at`
20. `source_attachment_count`
21. `source_remark`

#### 当前状态

22. `status`
23. `current_version`
24. `is_locked`
25. `confirm_status`
26. `writeback_status`
27. `version_count`

#### 摘要信息

28. `item_count`
29. `total_goods_value`
30. `total_gross_weight_kg`
31. `estimated_total_cost_rmb`
32. `actual_total_cost_rmb`

#### 附加信息

33. `import_remark`
34. `extra_json`

### 来源类型建议枚举

`source_type`

1. `excel`
2. `oa_logistics`
3. `erp_purchase`
4. `manual`
5. `attachment_parse`

### 钉钉跳转相关字段说明

1. `source_instance_id`：钉钉审批实例 ID，用于拼装客户端唤起链接。
2. `source_dingtalk_url`：钉钉官方 PC 网页链接，用于实例 ID 缺失时兜底打开。

### 状态建议枚举

`status`

1. `Draft`
2. `Imported`
3. `Dirty`
4. `Calculated`
5. `Confirmed`
6. `Writeback Failed`
7. `Written Back`

### 确认状态建议枚举

`confirm_status`

1. `Pending`
2. `Partially Confirmed`
3. `Confirmed`

### 回写状态建议枚举

`writeback_status`

1. `Not Started`
2. `Pending`
3. `Failed`
4. `Success`

### 索引建议

1. `batch_no`
2. `customs_no`
3. `waybill_no`
4. `source_approval_no`
5. `source_instance_id`
6. `source_data_id`
7. `transport_mode`
8. `status`

---

## 3.2 Overseas Cost Version

### 作用

表示同一批次下的成本版本。

### 建议命名

`Overseas Cost Version`

### 建议字段

1. `batch`
2. `version_code`
3. `version_type`
4. `is_current`
5. `source_type`
6. `fx_usd_to_rmb`
7. `fx_rmb_to_mxn`
8. `rule_snapshot_json`
9. `summary_snapshot_json`
10. `remark`
11. `created_by_name`

### 版本类型建议枚举

1. `Estimated`
2. `Actual`
3. `Adjustment`

### 来源类型建议枚举

1. `Import`
2. `Clone`
3. `Manual`

### 索引建议

1. `batch`
2. `version_type`
3. `is_current`

---

## 3.3 Overseas Cost Item

### 作用

表示一行 SKU / 物料成本明细。

### 建议命名

`Overseas Cost Item`

### 建议字段

#### 关联字段

1. `batch`
2. `version`
3. `row_no`
4. `excel_row_no`

#### Excel A ~ BE 正式字段

5. `material_code`
6. `product_name`
7. `unit_price`
8. `quantity`
9. `goods_value`
10. `import_name`
11. `hs_code`
12. `category`

#### 单据信息

13. `customs_no`
14. `waybill_no`

#### 国内段费用

15. `china_misc_rmb`
16. `china_misc_mxn`
17. `china_ocean_usd`

#### 核心税费字段

18. `cc_rate`
19. `cc_anti_dumping`
20. `igi_rate`
21. `igi_amount`
22. `iva_rate`
23. `iva_amount`
24. `goods_value_ratio`
25. `dta`
26. `prv_duty`
27. `prv_iva`
28. `import_tax_total`

#### 清关费用字段

29. `revalidacion`
30. `maniobras`
31. `muellaje`
32. `entrega_mercancia`
33. `previo`
34. `service_aa`
35. `almacenajes`
36. `reconocimiento_aduanero`
37. `honorarios`
38. `complemento_maniobras`
39. `desconsolidacion`
40. `maniobra_falso`
41. `arrastre`
42. `patio_regulador`
43. `entrega_vacio`
44. `limpieza_contenedor`

#### 墨西哥段费用

45. `mexico_customs_mxn`
46. `mexico_customs_rmb`
47. `mexico_customs_usd`
48. `mexico_inland_mxn`
49. `mexico_misc_mxn`
50. `mexico_inland_misc_rmb`
51. `china_to_mexico_freight_rmb`

#### 重量与分摊结果

52. `gross_weight_kg`
53. `weight_ratio`
54. `freight_alloc_rmb`
55. `freight_alloc_mxn`
56. `total_logistics_mxn`
57. `alloc_price_mxn`
58. `total_cost_rmb`
59. `total_unit_rmb`

#### 业务归集

60. `project_collection`
61. `transport_mode`

#### 扩展与追溯字段

62. `source_remark`
63. `raw_excel_json`
64. `derived_json`
65. `extra_json`

### 设计说明

1. `material_code` 作为正式 `A列` 字段使用，不再用作备注承载字段。
2. 历史 Excel `A列` 的备注、汇率换算说明、人工补充说明统一保留在 `source_remark`。
3. `goods_value` 允许导入原值，也允许在后端按 `unit_price * quantity` 自动补算。
4. `raw_excel_json` 保存原始导入内容，方便核对。
5. `derived_json` 保存系统计算中间结果，例如费用明细分摊拆解。
6. `extra_json` 保存后续新增字段，例如体积、体积重、供应商等。

### 索引建议

1. `batch`
2. `version`
3. `customs_no`
4. `waybill_no`
5. `product_name`
6. `import_name`
7. `hs_code`
8. `category`
9. `transport_mode`

---

## 3.4 Overseas Cost Allocation Rule

### 作用

表示每个版本下的费用项分摊规则。

### 建议字段

1. `batch`
2. `version`
3. `fee_key`
4. `fee_label`
5. `amount`
6. `currency`
7. `allocation_basis`
8. `basis_field`
9. `is_enabled`
10. `priority_no`
11. `remark`

### 分摊口径建议枚举

`allocation_basis`

1. `Goods Value`
2. `Weight`
3. `Volume`

### 币种建议枚举

1. `RMB`
2. `USD`
3. `MXN`

### 说明

一期至少需要两类默认规则：

1. 中国运输及相关杂费按货值分摊
2. 中国到墨西哥运费按重量分摊

---

## 3.5 Overseas Cost Attachment

### 作用

用于保存导入文件、账单、完税凭证、发票、物流附件。

### 建议字段

1. `batch`
2. `version`
3. `attachment_type`
4. `file_url`
5. `file_name`
6. `parse_status`
7. `parse_result_json`
8. `mapped_result_json`
9. `remark`

### 附件类型建议枚举

1. `Excel Main Table`
2. `Logistics Bill`
3. `Commercial Invoice`
4. `Tax Certificate`
5. `Other`

### 解析状态建议枚举

1. `Pending`
2. `Parsed`
3. `Matched`
4. `Failed`

---

## 3.6 Overseas Cost Audit Log

### 作用

记录所有关键操作日志。

### 建议字段

1. `batch`
2. `version`
3. `item_id`
4. `action_type`
5. `field_name`
6. `before_value`
7. `after_value`
8. `operator_type`
9. `operator_name`
10. `remark`

### 操作类型建议枚举

1. `Import Batch`
2. `Update Item`
3. `Update Rule`
4. `Recalculate`
5. `Create Version`
6. `Switch Version`
7. `Confirm Version`
8. `Writeback ERP`

### 操作人类型建议枚举

1. `System`
2. `Manual`
3. `API`

---

## 4. 字段分组建议

虽然前端展示按 Excel 顺序，但数据库建议分 3 层字段：

## 4.1 核心查询字段

必须独立建列：

1. 报关单号
2. 运单号
3. 产品名称
4. 海关进口名称
5. 海关分类编码
6. 大类
7. 运输方式
8. 版本类型

## 4.2 核心计算字段

建议独立建列：

1. 单价
2. 数量
3. 总货值
4. 税率
5. 税额
6. 清关费用
7. 墨西哥段费用
8. 毛重
9. 分摊结果
10. 综合成本

## 4.3 扩展兼容字段

适合放 JSON：

1. 原 Excel 原始结构
2. 导入来源备注
3. 后续补充体积相关字段
4. AI 解析返回结果

---

## 5. MariaDB 落表建议

Frappe 最终会自动生成 `tabDocTypeName` 表。

建议注意：

1. 高频过滤字段尽量 Short Data / Data
2. 金额类尽量 Currency / Float
3. 比例类尽量 Percent / Float
4. JSON 建议 Long Text 存序列化内容，或采用 Frappe 可接受的 JSON 字段方案

---

## 6. 版本建模建议

版本不要只存在批次主表一个状态字段里，而是要独立表。

原因：

1. 暂估版和实际版可能同时存在
2. 后续可能有补差版
3. 要支持差异追踪
4. 要支持按版本重算和回写

推荐：

1. `Batch` 只记录 `current_version`
2. 全部实际数据放在 `Version + Item`

---

## 7. 审计设计建议

不建议只依赖 Frappe 自带的修改历史。

原因：

1. 财务更关心“业务字段怎么改的”
2. 还要记录重算、切版、导入、回写
3. 需要业务化描述

所以建议独立一张：

`Overseas Cost Audit Log`

---

## 8. ERP 回写预留建议

一期即使暂时不做真实回写，也建议先预留字段：

在 `Overseas Cost Batch` 中至少预留：

1. `writeback_status`
2. `writeback_time`
3. `writeback_message`
4. `erp_target_doc`

---

## 9. 一期最小可用数据模型

如果开发资源有限，最低也建议先做：

1. `Overseas Cost Batch`
2. `Overseas Cost Version`
3. `Overseas Cost Item`
4. `Overseas Cost Allocation Rule`
5. `Overseas Cost Audit Log`

附件可稍后补。

---

## 10. 一句话结论

数据库设计不要按“一个 Excel 一张表”来做，而应该按：

1. `批次`
2. `版本`
3. `SKU 明细`
4. `规则`
5. `附件`
6. `日志`

这 6 类对象拆开建模，才能支撑后面的重算、补差、回写和审计。
