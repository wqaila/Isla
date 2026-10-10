# -*- coding: utf-8 -*-
"""第 4 周:自然语言查询与请求采集 —— 意图解析。

设计原则
--------
1. **规则式、可离线运行**:不依赖任何大模型 API,课程环境下一定能跑通。
2. **可解释**:解析结果同时返回命中的关键词,前端能展示"我是怎么理解的",
   判错了用户一眼能看出来,而不是黑箱。
3. **绝不编造**:解析不出意图就返回 `unknown` + 候选提示,不猜。
4. 只负责"听懂",不负责"执行" —— 执行在 `app.py` 的 `/api/nlq` 里,
   这样解析器可以单独用脚本测试。

支持的意图
----------
- latest        当前/最新的加速度是多少
- stats         最近 N 分钟的 X/Y/Z/合加速度 的 最大/最小/平均/标准差/峰峰值
- device_status 设备在线吗 / 信号怎么样
- count         有多少条数据
- sample        采集一次(会真的下发任务)
- pause/resume  暂停/恢复周期上报
- events        最近有几次按键触发
- help          能做什么
"""

import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- 中文数字

_CN_DIGITS = {
    "零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _parse_number(s: str) -> Optional[float]:
    """把 '5' / '5.5' / '五' / '十五' 转成数字。"""
    s = s.strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    # 纯中文数字(支持到九十九)
    if all(ch in _CN_DIGITS for ch in s):
        if s == "十":
            return 10.0
        if len(s) == 1:
            return float(_CN_DIGITS[s])
        if "十" in s:
            a, _, b = s.partition("十")
            tens = _CN_DIGITS.get(a, 1) if a else 1
            ones = _CN_DIGITS.get(b, 0) if b else 0
            return float(tens * 10 + ones)
    return None


# ---------------------------------------------------------------- 时间范围

_UNIT_MS = {
    "秒": 1000, "秒钟": 1000, "s": 1000, "sec": 1000,
    "分": 60_000, "分钟": 60_000, "m": 60_000, "min": 60_000,
    "小时": 3_600_000, "时": 3_600_000, "h": 3_600_000, "钟头": 3_600_000,
    "天": 86_400_000, "日": 86_400_000, "d": 86_400_000,
}

_RANGE_PATTERNS = [
    # 最近/近/过去 + 数字 + 单位
    r"(?:最近|近|过去|最后)\s*(\d+(?:\.\d+)?|[一二两三四五六七八九十]+)\s*"
    r"(秒钟|秒|分钟|分|小时|时|钟头|天|日|s|sec|m|min|h|d)",
    # 数字 + 单位 + 内/之内/以来
    r"(\d+(?:\.\d+)?|[一二两三四五六七八九十]+)\s*"
    r"(秒钟|秒|分钟|分|小时|时|钟头|天|日|s|sec|m|min|h|d)\s*(?:之内|以内|内|以来|里)",
]


def _parse_range_ms(text: str) -> Optional[int]:
    """解析'最近 5 分钟'这类时间范围,返回毫秒;没写范围返回 None(=全部)。"""
    for pat in _RANGE_PATTERNS:
        m = re.search(pat, text)
        if m:
            n = _parse_number(m.group(1))
            unit = _UNIT_MS.get(m.group(2))
            if n and unit:
                return int(n * unit)
    # 不写数字的兜底说法
    if re.search(r"(全部|所有|整个|一直|从头)", text):
        return None
    if re.search(r"(这一小时|这一小时|当前小时)", text):
        return 3_600_000
    return None


# ---------------------------------------------------------------- 指标

_METRIC_RULES = [
    (r"(合加速度|合成加速度|合加速度模|模长|矢量和|合量|总加速度)", "mag"),
    (r"(x\s*轴|acc_x|x轴|x方向)", "x"),
    (r"(y\s*轴|acc_y|y轴|y方向)", "y"),
    (r"(z\s*轴|acc_z|z轴|z方向)", "z"),
]

_AGG_RULES = [
    (r"(最大值|最大|最高|峰值|peak|max)", "max"),
    (r"(最小值|最小|最低|谷值|min)", "min"),
    (r"(平均值|平均|均值|avg|mean)", "avg"),
    (r"(标准差|方差|波动|抖动|std)", "std"),
    (r"(峰峰值|峰谷值|变化范围|极差|p2p)", "peak_to_peak"),
]

_METRIC_CN = {"x": "X 轴", "y": "Y 轴", "z": "Z 轴", "mag": "合加速度"}
_AGG_CN = {
    "max": "最大值", "min": "最小值", "avg": "平均值",
    "std": "标准差", "peak_to_peak": "峰峰值",
}


def _first_match(rules, text: str):
    for pat, val in rules:
        if re.search(pat, text, flags=re.I):
            return val
    return None


# ---------------------------------------------------------------- 意图

# 顺序即优先级:
#   1) 动作类(sample/pause/resume)放最前,避免「采集一次」被当成查询
#   2) device_status 必须放在 stats 前面 —— stats 里有「怎么样/情况」这类泛词,
#      「信号怎么样」会被误判成统计
#   3) latest 放最后,它只靠「多少/数值」这类弱特征兜底
_INTENT_RULES: List[tuple] = [
    # 口语说法要覆盖全:「帮我采一次」里没有"采集"二字,只有"采一次",
    # 所以按「动词 + 可选数量 + 量词」组合匹配,而不是穷举词表。
    ("sample", r"(采集|采样|采|测|量|取|抓|读)(一|1|两|俩|几)?(次|下|回|遍|组|批)"
               r"|采集|采样|取个值|采个值|读个数|来一次"),
    ("pause", r"(暂停|停一下|别传了|停止上报|停止上传)"),
    ("resume", r"(恢复|继续|重新开始|接着传|恢复上报|重新上传)"),
    ("device_status", r"(在线|离线|掉线|还活着|状态如何|信号|rssi|连接着|通不通|还在|设备状态|板子状态)"),
    ("count", r"(多少条|几条|数据量|样本数|有多少数据|多少数据|共几条|条数)"),
    ("events", r"(按键|按钮|触发|boot|按了几|几次按下|事件)"),
    ("stats", r"(最大|最小|平均|均值|标准差|方差|波动|峰峰|极差|统计|汇总|怎么样|情况)"),
    ("latest", r"(当前|现在|此刻|最新|实时|多少|读数|数值|加速度)"),
    ("help", r"(能做什么|能干什么|怎么用|帮助|help|支持什么|会什么)"),
]

_HELP_TEXT = (
    "我可以帮你做这些:\n"
    "• 查当前值 ——「现在加速度是多少」\n"
    "• 查统计 ——「最近 5 分钟合加速度的最大值」「X 轴平均值」\n"
    "• 查设备 ——「设备还在线吗」「信号怎么样」\n"
    "• 查数据量 ——「有多少条数据」\n"
    "• 查按键 ——「最近有几次按键触发」\n"
    "• 远程采集 ——「采集一次」(会真的给板子下发任务并等结果)\n"
    "• 控制上报 ——「暂停上报」「恢复上报」"
)


def parse(text: str) -> Dict[str, Any]:
    """解析一句自然语言,返回 {intent, slots, matched, confidence}。"""
    raw = (text or "").strip()
    # 统一全角标点与大小写,方便匹配
    t = raw.replace("，", ",").replace("？", "?").replace("。", ".")
    t = t.replace("吗", "")  # 「在吗」「在线吗」→「在」「在线」
    t = t.strip()

    if not t:
        return {"intent": "empty", "slots": {}, "matched": [], "confidence": 0.0}

    matched: List[str] = []
    intent = "unknown"
    for name, pat in _INTENT_RULES:
        m = re.search(pat, t, flags=re.I)
        if m:
            intent = name
            matched.append(m.group(0))
            break

    slots: Dict[str, Any] = {}
    range_ms = _parse_range_ms(t)
    if range_ms is not None:
        slots["since_ms"] = range_ms
        matched.append(f"时间范围={_human_ms(range_ms)}")
    else:
        slots["since_ms"] = None

    metric = _first_match(_METRIC_RULES, t)
    agg = _first_match(_AGG_RULES, t)
    if metric:
        slots["metric"] = metric
        matched.append(f"指标={_METRIC_CN[metric]}")
    if agg:
        slots["agg"] = agg
        matched.append(f"聚合={_AGG_CN[agg]}")

    # 兜底:问统计却没说指标 → 默认合加速度;没说聚合 → 默认平均值
    if intent == "stats":
        slots.setdefault("metric", "mag")
        slots.setdefault("agg", "avg")
    if intent == "latest" and metric:
        slots["metric"] = metric

    confidence = 0.5
    if intent != "unknown":
        confidence = 0.7 + 0.1 * min(len(matched), 3)

    return {
        "intent": intent,
        "slots": slots,
        "matched": matched,
        "confidence": round(min(confidence, 0.99), 2),
        "text": raw,
    }


def _human_ms(ms: int) -> str:
    if ms % 86_400_000 == 0:
        return f"{ms // 86_400_000} 天"
    if ms % 3_600_000 == 0:
        return f"{ms // 3_600_000} 小时"
    if ms % 60_000 == 0:
        return f"{ms // 60_000} 分钟"
    return f"{ms / 1000:.0f} 秒"


# 公开别名:app.py 的 /api/nlq 要用,避免跨模块访问下划线私有成员
human_ms = _human_ms
HELP_TEXT = _HELP_TEXT


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    cases = [
        "现在加速度是多少",
        "最近 5 分钟合加速度的最大值",
        "最近五分钟X轴平均值",
        "过去 2 小时 Z 轴的波动情况",
        "设备还在线吗",
        "信号怎么样",
        "有多少条数据",
        "采集一次",
        "帮我采一次",        # 口语:没有"采集"二字
        "采一下",
        "再测一次",
        "帮我量一下",
        "暂停上报",
        "恢复上报",
        "最近有几次按键触发",
        "你能做什么",
        "数据量有多少",      # 反向:不能误判成 sample
        "一共有多少条数据",  # 反向
        "帮我看看今天的天气",
    ]
    for c in cases:
        r = parse(c)
        print(f"{c:<22} → {r['intent']:<14} {r['slots']}  {r['matched']}")
