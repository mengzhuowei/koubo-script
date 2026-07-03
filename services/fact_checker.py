"""事实检查（V0.4）：事实冲突检测 + 脚本事实引用检查。

两类检查：
1. 资料卡 core_facts 之间的事实冲突（数值/版本/日期矛盾）
2. 脚本正文中具体事实（版本号、价格、日期）是否有资料卡来源支撑
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 数值/版本/价格/日期模式
# 用单一捕获组覆盖所有分支，使 findall 一致返回字符串（而非元组），GPT/Claude/Gemini 型号也能被提取
VERSION_RE = re.compile(r"\b(v?\d+\.\d+(?:\.\d+)?)\b|(GPT-\d+(?:\.\d+)?)|(Claude-\d+(?:\.\d+)?)|(Gemini-\d(?:\.\d+)?)", re.IGNORECASE)
PRICE_RE = re.compile(r"\$\d+(?:\.\d+)?|￥\d+|人民币\s*\d+|\d+\s*元/月|\d+\s*credits", re.IGNORECASE)
DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{0,2}日?|\d+月\d+日|今天|昨天|本周|上周")
NUMBER_RE = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万|亿|%|倍|个|条|次|token|参数)")

# 冲突检测：同一类事实但数值不同
CONFLICT_KEYS = ["版本", "价格", "日期", "数量", "支持", "不支持", "可以", "不能"]


@dataclass
class FactCheckResult:
    """事实检查结果。"""
    conflicts: list[dict] = field(default_factory=list)  # 资料卡内事实冲突
    unverified_claims: list[dict] = field(default_factory=list)  # 脚本中无来源支撑的事实
    total_facts: int = 0
    verified_facts: int = 0
    risk_level: str = "low"  # low/medium/high


def check_card_facts(card_data: dict) -> list[dict]:
    """检测资料卡 core_facts 之间的事实冲突。

    返回冲突列表，每项 {fact_a, fact_b, conflict_type, description}。
    """
    facts = card_data.get("core_facts") or []
    conflicts = []
    seen_values: dict[str, list[tuple[int, str, str]]] = {}  # key -> [(idx, claim, value)]

    for i, f in enumerate(facts):
        claim = f.get("claim", "")
        # 提取数值类事实
        for pattern, ftype in [(VERSION_RE, "版本"), (PRICE_RE, "价格"), (DATE_RE, "日期")]:
            for val in _iter_pattern_matches(pattern, claim):
                key = f"{ftype}:{_normalize_fact_value(val)}"
                if key not in seen_values:
                    seen_values[key] = []
                seen_values[key].append((i, claim, val))

    # 同类型不同值之间检查冲突
    type_values: dict[str, list[tuple[int, str, str]]] = {}
    for i, f in enumerate(facts):
        claim = f.get("claim", "")
        for pattern, ftype in [(VERSION_RE, "版本"), (PRICE_RE, "价格")]:
            vals = list(_iter_pattern_matches(pattern, claim))
            if vals:
                type_values.setdefault(ftype, []).append((i, claim, vals[0]))

    for ftype, items in type_values.items():
        if len(items) < 2:
            continue
        # 同类型有多个不同值，标记为潜在冲突
        values = {_normalize_fact_value(v) for _, _, v in items}
        if len(values) > 1:
            conflicts.append({
                "fact_a": items[0][1][:100],
                "fact_b": items[1][1][:100],
                "conflict_type": ftype,
                "description": f"资料卡内 {ftype} 存在多个不同值：{items[0][2]} vs {items[1][2]}",
            })

    return conflicts


def check_script_facts(script_body: str, card_data: dict) -> list[dict]:
    """检查脚本正文中的具体事实是否有资料卡来源支撑。

    返回未验证的事实列表，每项 {claim, fact_type, value, suggestion}。
    """
    facts = card_data.get("core_facts") or []
    # 资料卡中已有的事实文本（用于匹配脚本是否引用了资料卡内事实）
    card_claims = " ".join(f.get("claim", "") for f in facts).lower()

    unverified = []
    body = script_body or ""

    # 提取脚本中的具体数值
    for pattern, ftype in [(VERSION_RE, "版本号"), (PRICE_RE, "价格"), (DATE_RE, "日期")]:
        for val in _iter_pattern_matches(pattern, body):
            normalized = _normalize_fact_value(val).lower()
            # 检查这个值是否在资料卡事实中出现过
            if normalized and normalized not in card_claims:
                # 找到包含该值的脚本句子
                sentence = _find_sentence(body, val)
                unverified.append({
                    "claim": sentence[:150],
                    "fact_type": ftype,
                    "value": val,
                    "suggestion": f"脚本中提到的 {ftype}「{val}」未在资料卡来源中找到，建议核实",
                })

    return unverified


def run_full_check(*, script_body: str, card_data: dict) -> FactCheckResult:
    """执行完整事实检查：资料卡冲突 + 脚本未验证事实。"""
    conflicts = check_card_facts(card_data)
    unverified = check_script_facts(script_body, card_data)

    facts = card_data.get("core_facts") or []
    total = len(facts)
    # 简化：有来源 URL 的算已验证
    verified = sum(1 for f in facts if f.get("source_url"))

    # 风险等级
    risk = "low"
    if conflicts or len(unverified) >= 3:
        risk = "high"
    elif unverified:
        risk = "medium"

    return FactCheckResult(
        conflicts=conflicts,
        unverified_claims=unverified,
        total_facts=total,
        verified_facts=verified,
        risk_level=risk,
    )


def _normalize_fact_value(val: str) -> str:
    """归一化事实值，便于比对。"""
    return re.sub(r"[\s$￥元/月 credits.,]", "", str(val).lower())


def _iter_pattern_matches(pattern: re.Pattern, text: str):
    """统一提取正则匹配值。

    findall 在无捕获组时返回 str 列表，有捕获组时返回 tuple 列表（每个 tuple 含所有组，
    未匹配的组为空串）。这里统一返回首个非空组的值，兼容两类模式。
    """
    for m in pattern.findall(text):
        if isinstance(m, str):
            yield m
            continue
        for g in m:
            if g:
                yield g
                break


def _find_sentence(body: str, value: str) -> str:
    """找到包含某值的句子。"""
    idx = body.find(value)
    if idx < 0:
        return value
    # 向前找句号/换行（rfind 找不到返回 -1，max 会自动忽略）
    start = max(0, body.rfind("。", 0, idx), body.rfind("\n", 0, idx))
    # 向后找句号/换行（find 找不到返回 -1，必须先过滤掉，否则 min 会误取 -1）
    end_candidates = [c for c in (body.find("。", idx), body.find("\n", idx)) if c >= 0]
    end = min(end_candidates) if end_candidates else len(body)
    end = min(len(body), end)
    return body[start:end].strip()
