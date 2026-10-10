# -*- coding: utf-8 -*-
"""第 4 周当堂验证:自然语言查询与请求采集(自动部分)。

用法:
    python server/app.py            # 先起服务
    python scripts/verify_week4.py  # 再跑本脚本

覆盖三类检查
------------
1. 意图识别:13 句话 → 期望的 intent。
2. 答案可核对:同一句统计问话,`/api/nlq` 给的数值必须与 `/api/stats` 完全一致
   (两者共用 `_describe_all()`,若哪天被改歪了这里会立刻红)。
3. 动作类(sample/pause/resume)确实走了第 2 周的任务通道:返回 request_id,
   状态机一致。板子在线时才跑真实等待;离线时验证"如实超时、不谎报成功"。

需要人工确认的部分见 docs/week4-verification.md。
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
TIMEOUT = 30

# (问话, 期望 intent)
INTENT_CASES = [
    ("现在加速度是多少", "latest"),
    ("最新读数", "latest"),
    ("最近 5 分钟合加速度的最大值", "stats"),
    ("最近五分钟X轴平均值", "stats"),
    ("过去 2 小时 Z 轴的波动情况", "stats"),
    ("设备还在线吗", "device_status"),
    ("信号怎么样", "device_status"),
    ("有多少条数据", "count"),
    ("最近有几次按键触发", "events"),
    ("你能做什么", "help"),
    ("帮我看看今天的天气", "unknown"),
    ("", "empty"),
]

ACTION_CASES = [
    ("暂停上报", "pause"),
    ("恢复上报", "resume"),
]


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    passed = failed = 0

    print("=" * 72)
    print("第 4 周自动验证:自然语言查询")
    print("=" * 72)

    # 前置:服务在跑吗
    try:
        h = get("/api/health")
    except Exception as e:
        print(f"[FATAL] 服务不可达 {BASE}:{e}")
        return 2
    print(f"[ok] 服务在线,内存记录 {h['count']} 条\n")

    # ---------------------------------------------------------------- 1 意图
    print("-" * 72)
    print("1) 意图识别")
    print("-" * 72)
    for text, want in INTENT_CASES:
        try:
            r = post("/api/nlq", {"text": text})
        except urllib.error.HTTPError as e:
            print(f"[FAIL] {text!r} → HTTP {e.code}")
            failed += 1
            continue
        got = r.get("intent")
        ok = got == want
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        tag = "ok  " if ok else "FAIL"
        ans = (r.get("answer") or "").replace("\n", " / ")[:58]
        print(f"[{tag}] {text!r:<24} → {got:<14} {ans}")

    # ------------------------------------------------- 2 统计值与 /api/stats 一致
    print("-" * 72)
    print("2) 数值可核对:/api/nlq 的统计 == /api/stats 的统计")
    print("-" * 72)
    # 窗口用 24 小时:板子若离线,近几分钟必然没数据,那样核对就没意义了
    for text, metric, agg, since_ms in [
        ("最近一天合加速度的最大值", "acc_magnitude", "max", 86_400_000),
        ("最近 24 小时 X 轴的平均值", "acc_x", "avg", 86_400_000),
        ("最近 10 小时 Z 轴的最小值", "acc_z", "min", 36_000_000),
    ]:
        a = post("/api/nlq", {"text": text})
        b = get(f"/api/stats?since_ms={int(time.time() * 1000) - since_ms}")
        if a.get("data", {}).get("stat") is None:
            print(f"[skip] {text!r} → 该时间范围内无数据(服务刚启动属正常)")
            print(f"       answer: {a.get('answer')}")
            continue
        v1 = a["data"]["stat"][agg]
        v2 = b[metric][agg]
        n1 = a["data"]["stat"]["count"]
        n2 = b[metric]["count"]
        ok = abs((v1 or 0) - (v2 or 0)) < 1e-9 and n1 == n2
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        tag = "ok  " if ok else "FAIL"
        print(f"[{tag}] {text!r}")
        print(f"       nlq={v1}(n={n1})  stats={v2}(n={n2})")

    # ------------------------------------------------------------- 3 动作类
    print("-" * 72)
    print("3) 动作类:复用第 2 周任务通道(不下发成功就不算成功)")
    print("-" * 72)
    for text, want in ACTION_CASES:
        r = post("/api/nlq", {"text": text, "wait": False})
        got, task = r.get("intent"), r.get("task") or {}
        ok = got == want and bool(task.get("request_id"))
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        tag = "ok  " if ok else "FAIL"
        print(f"[{tag}] {text!r} → {got} request_id={task.get('request_id')} status={task.get('status')}")

    # 真实等待:板子在线才跑,离线则验证"如实超时"
    health = get("/api/health")
    latest = get("/api/latest")
    online = False
    if latest.get("ok") and latest.get("record"):
        age = int(time.time() * 1000) - int(latest["record"].get("received_at_ms") or 0)
        online = age < 10_000
    print()
    if online:
        print("[..] 板子在线,跑一次真实的「采集一次」(最多等 12 秒)")
        t0 = time.time()
        r = post("/api/nlq", {"text": "采集一次", "wait": True})
        st = (r.get("task") or {}).get("status")
        ok = st == "completed"
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"[{'ok  ' if ok else 'FAIL'}] 采集一次 → status={st} 耗时 {int((time.time()-t0)*1000)} ms")
        print(f"       {r.get('answer')}")
    else:
        print("[..] 板子当前离线,改为验证「不得谎报成功」(应如实超时)")
        t0 = time.time()
        r = post("/api/nlq", {"text": "采集一次", "wait": True})
        st = (r.get("task") or {}).get("status")
        ans = r.get("answer") or ""
        ok = st in ("timeout", "pending", "received") and "成功" not in ans
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"[{'ok  ' if ok else 'FAIL'}] 采集一次 → status={st} 耗时 {int((time.time()-t0)*1000)} ms")
        print(f"       {ans}")

    print()
    print("=" * 72)
    print(f"自动验证结果:{passed} 通过 / {failed} 失败")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
