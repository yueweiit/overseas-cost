"""
中文用途：OA 国际物流单导入脚本骨架。

后续可用于：
1. 命令行调试导入
2. 一次性批量导入历史 OA 数据
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 OA 国际物流单样例")
    parser.add_argument("--source", required=True, help="OA 导出文件路径")
    parser.add_argument("--transport-mode", default="SEA", help="运输方式，默认海运")
    args = parser.parse_args()
    print({"source": args.source, "transport_mode": args.transport_mode, "message": "导入脚本骨架已创建"})


if __name__ == "__main__":
    main()
