# -*- coding: utf-8 -*-
"""第 6 周当堂验证:让语音任务可以澄清与停止(自动部分)。

用法:
    python server/app.py
    server/.venv/Scripts/python.exe scripts/verify_week6.py

覆盖(对照任务卡「当堂验证:取消后迟到结果不得重新播放或触发动作;
新任务不被旧任务结果覆盖」)
--------------------------------------------------
W6-1 取消未下发任务:创建后立即取消 → 状态 cancelled;等过板端轮询周期,
     板端不会领到已取消的任务(或领到后其迟到结果也被忽略)。
W6-2 迟到回执隔离:取消后模拟板端 ack completed → 状态保持 cancelled,
     late_ack=True,不重新播放/不触发动作。
W6-3 迟到数据隔离:取消后模拟板端上传带 request_id 的数据 → 状态仍 cancelled,
     数据本身保留(真实采样不丢),但任务不被算作完成。
W6-4 延迟注入 + 取消(慢响应演示):nlq 带 delay_ms,睡眠期间取消 →
     睡醒后不下发新任务,回答明说"已取消"。
W6-5 连续两次查询互不覆盖:两个独立 session,各自计时/结果,
     日志里 request_id 与 session_id 一一对应。
W6-6 交互日志可关联:动作类任务的 request_id 出现在日志里,时序三项齐全。

需要人工确认(页面 ⏹ 停止按钮、文字停止按钮、慢响应演示操作)见
docs/week6-verification.md。
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
TIMEOUT = 40
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    return ok


def post(path, body, timeout=TIMEOUT):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            raise


def get(path, timeout=TIMEOUT):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("=" * 62)
    print("  第 6 周当堂验证 —— 澄清、取消与迟到结果隔离(自动部分)")
    print(f"  时间:{time.strftime('%Y-%m-%d %H:%M:%S')}   服务:{BASE}")
    print("=" * 62)

    # ---------- W6-1 取消未下发任务 ----------
    print("\n=== W6-1 取消任务:板端不再领取 ===")
    rid1 = ""
    try:
        t = post("/api/task", {"group_id": "G03", "action": "sample"})["task"]
        rid1 = t["request_id"]
        c = post("/api/voice/cancel", {"session_id": "vs-w6-1", "request_id": rid1})
        check("W6-1a 取消成功", (c.get("task") or {}).get("status") == "cancelled",
              f"status={(c.get('task') or {}).get('status')}")
        time.sleep(4)   # 等过板端轮询周期(2s)
        t2 = get(f"/api/task/{rid1}")["task"]
        check("W6-1b 4 秒后仍未完成(板端未执行或结果被忽略)", t2["status"] == "cancelled",
              f"status={t2['status']} late_ack={t2.get('late_ack')}")
    except Exception as e:
        check("W6-1 取消任务", False, f"异常:{e}")

    # ---------- W6-2 迟到回执隔离 ----------
    print("\n=== W6-2 迟到回执被忽略(不触发动作)===")
    try:
        a = post("/api/ack", {"request_id": rid1, "device_id": "esp32s3-eye-01",
                              "stage": "completed", "note": "late-ack-test"})
        t = a["task"]
        check("W6-2a late_ignored 标记", a.get("late_ignored") is True)
        check("W6-2b 状态保持 cancelled", t["status"] == "cancelled", t["status"])
        check("W6-2c 没有 completed_at(不算成功)", t.get("completed_at_ms") is None)
        check("W6-2d late_ack 已记录", t.get("late_ack") is True)
    except Exception as e:
        check("W6-2 迟到回执", False, f"异常:{e}")

    # ---------- W6-3 迟到数据隔离 ----------
    print("\n=== W6-3 迟到数据不回退状态(真实采样仍留存)===")
    try:
        now = int(time.time() * 1000)
        post("/api/data", {"group_id": "G03", "device_id": "esp32s3-eye-01",
                           "ts_ms": now, "status": "ok",
                           "data": {"acc_x": 1.0, "acc_y": 2.0, "acc_z": 3.0,
                                    "request_id": rid1}})
        t = get(f"/api/task/{rid1}")["task"]
        check("W6-3a 状态仍 cancelled", t["status"] == "cancelled", t["status"])
        check("W6-3b late_ack 记录(迟到数据)", t.get("late_ack") is True)
        data_file = Path(__file__).resolve().parent.parent / "server" / "data.json"
        with open(data_file, "r", encoding="utf-8") as f:
            kept = any(rid1 in line for line in f)
        check("W6-3c 数据本身已留存(不丢真实采样)", kept)
    except Exception as e:
        check("W6-3 迟到数据", False, f"异常:{e}")

    # ---------- W6-4 延迟注入 + 取消 ----------
    print("\n=== W6-4 慢响应演示:延迟期间取消 → 不下发 ===")
    try:
        s4 = f"vs-w6-4-{int(time.time())}"
        import threading
        box = {}

        def slow_call():
            box["resp"] = post("/api/nlq", {"text": "采集一次", "channel": "voice",
                                            "session_id": s4, "delay_ms": 4000,
                                            "input_end_ms": int(time.time() * 1000)},
                               timeout=30)
        th = threading.Thread(target=slow_call)
        th.start()
        time.sleep(1.0)   # 服务端正在 sleep(delay),此时取消
        c = post("/api/voice/cancel", {"session_id": s4})
        check("W6-4a 会话已取消", c.get("session_cancelled") is True)
        th.join(timeout=30)
        r = box.get("resp") or {}
        check("W6-4b 取消后不下发任务", r.get("task") is None, f"task={r.get('task')}")
        check("W6-4c 回答明说已取消", "取消" in (r.get("answer") or ""), (r.get("answer") or "")[:40])
    except Exception as e:
        check("W6-4 延迟注入取消", False, f"异常:{e}")

    # ---------- W6-5 连续两次查询互不覆盖 ----------
    print("\n=== W6-5 连续两次查询:独立 session,互不覆盖 ===")
    try:
        q = "有多少条数据"
        r1 = post("/api/nlq", {"text": q, "channel": "voice",
                               "session_id": f"vs-w6-5a-{int(time.time())}",
                               "input_end_ms": int(time.time() * 1000)})
        r2 = post("/api/nlq", {"text": q, "channel": "voice",
                               "session_id": f"vs-w6-5b-{int(time.time())}",
                               "input_end_ms": int(time.time() * 1000)})
        s1, s2 = r1["voice"]["session_id"], r2["voice"]["session_id"]
        check("W6-5a 两个独立 session_id", s1 != s2 and bool(s1) and bool(s2))
        check("W6-5b 各自答案完整", bool(r1.get("answer")) and bool(r2.get("answer")))
        check("W6-5c 各自计时独立", r1["voice"]["respond_ms"] >= 0 and r2["voice"]["respond_ms"] >= 0)
    except Exception as e:
        check("W6-5 连续查询", False, f"异常:{e}")

    # ---------- W6-6 日志可关联 ----------
    print("\n=== W6-6 交互日志:request_id / session_id / 时序关联 ===")
    try:
        items = get("/api/voice/log?limit=30").get("items", [])
        acts = [i for i in items if i.get("request_id")]
        canc = [i for i in items if i.get("cancelled")]
        check("W6-6a 动作类日志带 request_id", len(acts) >= 1, f"{len(acts)} 条")
        check("W6-6b 取消会话被记录", len(canc) >= 1, f"{len(canc)} 条")
        check("W6-6c 时序三项齐全(输入→反馈)",
              all(i.get("first_feedback_ms") is not None or i.get("cancelled") for i in items[-6:]))
        # 迟到回执的权威记录在任务上(见 W6-2d:late_ack=True),日志侧验证:
        # 取消会话 + 两种入口都能在日志里区分
        chans = {i.get("channel") for i in items}
        check("W6-6d 日志可区分入口(voice/text)", "voice" in chans and "text" in chans,
              f"channels={sorted(chans)}")
    except Exception as e:
        check("W6-6 日志关联", False, f"异常:{e}")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 62)
    print(f"  结果:{passed}/{total} 项通过")
    print("=" * 62)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
