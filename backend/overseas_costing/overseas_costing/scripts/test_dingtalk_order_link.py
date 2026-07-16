"""
中文用途：本地测试钉钉订单跳转链接生成脚本。

适用场景：
1. 当前机器还没装 Frappe，先独立验证钉钉跳转链接是否拼接正确
2. 联调前先确认 instance_id、审批编号、官方链接是否能生成可用结果

运行示例：
python overseas_costing/scripts/test_dingtalk_order_link.py --instance-id PROC-TEST-001 --approval-no OA-20260709-001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
PACKAGE_ROOT = CURRENT_FILE.parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from overseas_costing.utils.dingtalk import build_dingtalk_order_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="测试钉钉订单跳转链接生成")
    parser.add_argument("--batch-name", default="HPCU5155607", help="批次号，仅用于输出展示")
    parser.add_argument("--approval-no", default="OA-20260709-001", help="审批编号")
    parser.add_argument("--instance-id", default="", help="钉钉审批实例ID")
    parser.add_argument(
        "--official-url",
        default="https://oa.dingtalk.com/approval/detail",
        help="钉钉官方网页链接，instance_id 缺失时会回退到这里",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = build_dingtalk_order_payload(
        batch_name=args.batch_name,
        approval_no=args.approval_no,
        instance_id=args.instance_id,
        official_url=args.official_url,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
