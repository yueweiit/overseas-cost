#!/usr/bin/env bash
# 用途：修复「业务主体」（subsidiary_code）字段落库后，在本地 bench 回填历史批次。
# 背景：subsidiary_code 字段此前误加到了嵌套冗余副本 doctype，已改到正确文件并提交；
#       本脚本负责把列建出来，并回填已有 OA 批次。
#
# 用法（在 bench 环境执行，例如 WSL 的 ~/frappe-bench）：
#   SITE=development.localhost \
#   DINGTALK_ENV_FILE="/path/to/.env" \
#   bash /mnt/e/Yuewei开发/海外采购综合成本核算项目/overseas-cost/backend/overseas_costing/overseas_costing/scripts/backfill_subsidiary_code.sh
#
# 可选：只回填单个批次（先小范围验证）：
#   DINGTALK_TARGET_BATCH_NO="HPCU5155607" bash .../backfill_subsidiary_code.sh

set -euo pipefail

SITE="${SITE:-development.localhost}"
ENV_FILE="${DINGTALK_ENV_FILE:-}"

echo "==> 1/3 迁移建列（让 subsidiary_code 真正建到 DB）"
bench --site "$SITE" migrate

echo "==> 2/3 诊断：拉一条审批单，确认业务主体能提取出来（不写库）"
DINGTALK_ENV_FILE="$ENV_FILE" DINGTALK_LIMIT=1 \
  bench --site "$SITE" execute overseas_costing.scripts.import_oa_logistics.diagnose_business_entity_from_env

echo "==> 3/3 回填：重拉已有国际物流 OA 批次，补齐 subsidiary_code"
if [ -n "${DINGTALK_TARGET_BATCH_NO:-}" ]; then
  DINGTALK_ENV_FILE="$ENV_FILE" \
    bench --site "$SITE" execute overseas_costing.scripts.import_oa_logistics.refresh_existing_oa_logistics_details \
      --kwargs "{\"batch_no\": \"$DINGTALK_TARGET_BATCH_NO\"}"
else
  DINGTALK_ENV_FILE="$ENV_FILE" \
    bench --site "$SITE" execute overseas_costing.scripts.import_oa_logistics.refresh_existing_oa_logistics_details
fi

echo "==> 完成。可打开工作台抽屉复核「业务主体」是否已回填。"
