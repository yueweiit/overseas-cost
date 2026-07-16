"""
中文用途：审计日志服务。

后续这里统一收口：
1. 字段修改日志
2. 批量更新日志
3. 重算日志
4. 版本切换日志
5. 回写日志
"""

from __future__ import annotations


def build_audit_stub(action_type: str, payload: dict) -> dict:
    return {
        "action_type": action_type,
        "payload": payload,
    }
