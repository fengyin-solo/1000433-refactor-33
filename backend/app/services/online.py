"""在线仪表业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "online"
REQUIRED_FIELDS = ["仪表编号", "仪表类型", "测量范围"]
STATUS_ORDER = ["待校准", "在运正常", "数据异常", "已停用"]

# 状态与列表筛选口径保持一致：待处理、异常标记都由状态推导，不再按动作各算各的
PENDING_STATUSES = {"待校准", "数据异常"}
ABNORMAL_STATUSES = {"数据异常"}

# 动作只声明差异：目标状态、是否先做测量范围校验、重复执行时的提示；
# 共用的前置校验收在 _check_action 里，校准与停用不再各写一遍。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "提交校准": {"target": "在运正常", "check_range": True, "repeat_tip": "校准已提交且仪表在运正常，请勿重复校准"},
    "确认正常": {"target": "在运正常", "check_range": False, "repeat_tip": "仪表已在运正常，无需重复确认"},
    "停用仪表": {"target": "已停用", "check_range": True, "repeat_tip": "仪表已停用，无需重复停用"},
}


def _check_measure_range(entry: dict[str, Any]) -> str | None:
    """提交校准与停用仪表共用的测量范围校验：空值时返回说明，通过时返回 None。"""
    if not str(entry.get("测量范围") or "").strip():
        return "测量范围为空，请先补全测量范围再执行该动作"
    return None


def _check_action(entry: dict[str, Any], action: str, rule: dict[str, Any]) -> str | None:
    """校准、确认、停用共用的前置校验；返回说明文字表示动作被拦下。"""
    target = str(rule["target"])
    if target not in STATUS_ORDER:
        return f"目标状态「{target}」不在允许的状态序列里"
    if rule["check_range"]:
        problem = _check_measure_range(entry)
        if problem is not None:
            return problem
    current = str(entry.get("status") or "")
    if current == target:
        return str(rule["repeat_tip"])
    if current == STATUS_ORDER[-1]:
        return f"仪表已停用，无法{action}"
    return None


def _apply_status(entry: dict[str, Any], status: str) -> None:
    """写入状态并同步待处理/异常标记，保证校准、停用与列表状态口径一致。"""
    entry["status"] = status
    entry["pending"] = status in PENDING_STATUSES
    entry["abnormal"] = status in ABNORMAL_STATUSES


class OnlineService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("仪表编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        _apply_status(entry, STATUS_ORDER[0])
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"在线仪表 {entry_id} 不存在或已归档"
        rule = ACTION_RULES.get(action)
        if rule is None:
            return None, f"动作「{action}」不属于在线仪表可执行范围"
        problem = _check_action(entry, action, rule)
        if problem is not None:
            return None, problem
        _apply_status(entry, str(rule["target"]))
        return entry, f"在线仪表已{action}"
