"""中文用途：批次重算脚本。

用法示例：
bench --site development.localhost execute overseas_costing.scripts.recalculate_batch.recalculate --kwargs "{'batch_name':'HPCU5155607'}"
OVERSEAS_COST_BATCH=HPCU5155607 bench --site development.localhost execute overseas_costing.scripts.recalculate_batch.recalculate_from_env
python -m overseas_costing.scripts.recalculate_batch --batch HPCU5155607
"""

from __future__ import annotations

import argparse
import json
import os

from overseas_costing.services.calculate_service import recalculate_batch


def recalculate(batch_name: str, version_name: str | None = None) -> dict:
    """重算单个批次，供 bench execute 或本地调试复用。"""

    return recalculate_batch(batch_name=batch_name, version_name=version_name)


def recalculate_from_env() -> dict:
    """从环境变量读取批次，避免 bench execute 跨 shell 传参引号问题。"""

    batch_name = os.environ.get("OVERSEAS_COST_BATCH", "").strip()
    version_name = os.environ.get("OVERSEAS_COST_VERSION", "").strip() or None
    if not batch_name:
        return {"ok": False, "message": "缺少环境变量 OVERSEAS_COST_BATCH。"}
    return recalculate(batch_name=batch_name, version_name=version_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="重算某个批次")
    parser.add_argument("--batch", required=True, help="批次主键或批次号")
    parser.add_argument("--version", default="", help="版本名，可选")
    args = parser.parse_args()
    result = recalculate(batch_name=args.batch, version_name=args.version or None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
