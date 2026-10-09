#!/usr/bin/env python3
"""第 2 周当堂验证脚本 —— Web 远程采集指令与执行结果反馈。

自动跑完不需要人工配合的验证项,并生成 Markdown 报告。

验证项(对照第 2 周任务卡"当堂验证"):
  T0  前置:服务在线 + 设备在线
  T1  基线:周期上报正常,数据持续到达
  T2  远程采集一次:状态流转 pending→received→completed,且产生带 request_id 的新观测
  T3  暂停周期上报:暂停后不再产生周期记录
  T4  暂停中命令通道仍可用:仍能用"采集一次"拿到新数据
  T5  [人工] 改变设备状态(晃动板子)后采集,核对新观测确实更新
  T6  恢复周期上报:周期记录恢复
  T7  设备无响应时的等待/超时:任务不得把旧值误标为本次结果

用法:
  python scripts/verify_week2.py                # 跑自动项
  python scripts/verify_week2.py --manual       # 只跑需要人工配合的 T5
  python scripts/verify_week2.py --all          # 全部(含 T5)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
GROUP = "G03"
DEVICE = "esp32s3-eye-01"

RESULTS: list[dict] = []
LOG_LINES: list[str] = []


# ---------------------------------------------------------------- HTTP ----
def req(url: str, method: str = "GET", body: dict | None = None, timeout: int = 6):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def out(msg: str) -> None:
    print(msg, flush=True)
    LOG_LINES.append(msg)


def check(name: str, ok: bool, detail: str) -> bool:
    mark = "PASS" if ok else "FAIL"
    out(f"  [{mark}] {name}: {detail}")
    RESULTS.append({"name": name, "ok": ok, "detail": detail})
    return ok


# ------------------------------------------------------------- helpers ----
def latest(group: str = GROUP) -> dict | None:
    return req(f"{BASE}/api/latest?group_id={group}").get("record")


def history(limit: int = 200, group: str = GROUP) -> list[dict]:
    return req(f"{BASE}/api/history?group_id={group}&limit={limit}").get("records", [])


def count_since(since_ms: int, group: str = GROUP, periodic_only: bool = False) -> list[dict]:
    """返回 received_at_ms > since_ms 的记录;periodic_only=True 时只看周期上报(无 request_id)。"""
    recs = [r for r in history(limit=300, group=group) if r["received_at_ms"] > since_ms]
    if periodic_only:
        recs = [r for r in recs if not r["data"].get("request_id")]
    return recs


def mag(rec: dict) -> float:
    d = rec["data"]
    return math.sqrt(d["acc_x_g"] ** 2 + d["acc_y_g"] ** 2 + d["acc_z_g"] ** 2)


def create_task(action: str, device_id: str = DEVICE, group_id: str = GROUP) -> dict:
    return req(f"{BASE}/api/task", method="POST",
               body={"group_id": group_id, "device_id": device_id, "action": action})["task"]


def wait_task(rid: str, timeout: float = 20.0) -> tuple[dict, list[str]]:
    """轮询任务状态,返回 (最终任务, 状态轨迹)。"""
    trace: list[str] = []
    deadline = time.time() + timeout
    task = None
    while time.time() < deadline:
        task = req(f"{BASE}/api/task/{rid}")["task"]
        if not trace or trace[-1] != task["status"]:
            trace.append(task["status"])
        if task["status"] in ("completed", "failed", "timeout"):
            return task, trace
        time.sleep(0.4)
    return task or {}, trace + ["(轮询超时)"]


def find_record_by_req(rid: str) -> dict | None:
    for r in history(limit=300):
        if r["data"].get("request_id") == rid:
            return r
    return None


# --------------------------------------------------------------- tests ----
def t0() -> None:
    out("\n=== T0 前置检查 ===")
    h = req(f"{BASE}/api/health")
    check("T0.1 服务在线", h["ok"] is True, f"/api/health ok, count={h['count']}")
    rec = latest()
    if rec is None:
        check("T0.2 设备在线", False, "G03 无任何数据")
        return
    age = (int(time.time() * 1000) - rec["received_at_ms"]) // 1000
    check("T0.2 设备在线", age < 10 and rec["status"] == "ok",
          f"device={rec['device_id']} status={rec['status']} age={age}s")


def t1() -> None:
    out("\n=== T1 基线:周期上报 ===")
    start = int(time.time() * 1000)
    time.sleep(8)
    new = count_since(start)
    per = count_since(start, periodic_only=True)
    check("T1.1 周期数据持续到达", len(per) >= 1,
          f"8s 内新增 {len(new)} 条(其中周期上报 {len(per)} 条)")


def t2() -> int | None:
    out("\n=== T2 远程采集一次 ===")
    before = latest()
    t = create_task("sample")
    rid = t["request_id"]
    out(f"  创建任务 request_id={rid}")
    task, trace = wait_task(rid, timeout=20)
    check("T2.1 状态流转完整", "→".join(trace) in ("pending→received→completed", "received→completed", "pending→completed")
          or trace[-1] == "completed",
          f"轨迹: {'→'.join(trace)}")
    check("T2.2 任务在超时前完成", task.get("status") == "completed"
          and (task.get("elapsed_ms") or 99999) < 15000,
          f"status={task.get('status')} elapsed={task.get('elapsed_ms')} ms")
    rec = find_record_by_req(rid)
    check("T2.3 产生带 request_id 的新观测", rec is not None,
          f"record={'有' if rec else '无'}"
          + (f", |a|={mag(rec):.3f} g, received_at={rec['received_at_ms']}" if rec else ""))
    if rec and before:
        check("T2.4 新观测晚于任务创建", rec["received_at_ms"] >= task["created_at_ms"],
              f"record.received_at - task.created_at = "
              f"{rec['received_at_ms'] - task['created_at_ms']} ms")
    return rec["received_at_ms"] if rec else None


def t3() -> None:
    out("\n=== T3 暂停周期上报 ===")
    t = create_task("pause")
    rid = t["request_id"]
    task, trace = wait_task(rid, timeout=20)
    check("T3.1 pause 命令被执行", task.get("status") == "completed",
          f"轨迹: {'→'.join(trace)}, note={task.get('note')!r}")
    start = int(time.time() * 1000)
    time.sleep(9)
    per = count_since(start, periodic_only=True)
    check("T3.2 暂停后不再产生周期记录", len(per) == 0, f"9s 内新增周期记录 {len(per)} 条")


def t4() -> dict | None:
    out("\n=== T4 暂停中命令通道仍可用 ===")
    t = create_task("sample")
    rid = t["request_id"]
    task, trace = wait_task(rid, timeout=20)
    check("T4.1 暂停期间采集任务仍能完成", task.get("status") == "completed",
          f"轨迹: {'→'.join(trace)}, elapsed={task.get('elapsed_ms')} ms")
    rec = find_record_by_req(rid)
    check("T4.2 拿到本任务的新观测", rec is not None,
          f"|a|={mag(rec):.3f} g" if rec else "未找到带该 request_id 的记录")
    return rec


def t5_manual(baseline: dict | None) -> None:
    out("\n=== T5 [人工] 改变设备状态后采集 ===")
    out("  >>> 请在接下来 12 秒内拿起板子晃动/改变姿态 <<<")
    time.sleep(12)
    t = create_task("sample")
    rid = t["request_id"]
    task, trace = wait_task(rid, timeout=20)
    rec = find_record_by_req(rid)
    if rec is None:
        check("T5.1 采集到新观测", False, "未找到带该 request_id 的记录")
        return
    m = mag(rec)
    if baseline:
        bm = mag(baseline)
        diff = abs(m - bm)
        d = rec["data"]
        bd = baseline["data"]
        axis = max(abs(d["acc_x_g"] - bd["acc_x_g"]),
                   abs(d["acc_y_g"] - bd["acc_y_g"]),
                   abs(d["acc_z_g"] - bd["acc_z_g"]))
        check("T5.1 新观测与静止基线明显不同", axis > 0.15,
              f"基线 |a|={bm:.3f}g → 现在 |a|={m:.3f}g,单轴最大变化 {axis:.3f} g")
    else:
        check("T5.1 采集到新观测", True, f"|a|={m:.3f} g(无基线可比对)")
    check("T5.2 request_id 可追溯", rec["data"].get("request_id") == rid,
          f"record.request_id={rec['data'].get('request_id')}")


def t6() -> None:
    out("\n=== T6 恢复周期上报 ===")
    t = create_task("resume")
    rid = t["request_id"]
    task, trace = wait_task(rid, timeout=20)
    check("T6.1 resume 命令被执行", task.get("status") == "completed",
          f"轨迹: {'→'.join(trace)}, note={task.get('note')!r}")
    start = int(time.time() * 1000)
    time.sleep(9)
    per = count_since(start, periodic_only=True)
    check("T6.2 周期上报恢复", len(per) >= 1, f"9s 内新增周期记录 {len(per)} 条")


def t7() -> None:
    out("\n=== T7 设备无响应:等待 / 超时,且旧值不被误标 ===")
    ghost = "ghost-offline-01"
    t = create_task("sample", device_id=ghost)
    rid = t["request_id"]
    out(f"  创建指向离线设备 {ghost} 的任务 {rid},等待超时(15s 阈值)...")
    task, trace = wait_task(rid, timeout=25)
    check("T7.1 任务最终判定为超时", task.get("status") == "timeout",
          f"轨迹: {'→'.join(trace)}")
    check("T7.2 超时任务没有 completed_at", task.get("completed_at_ms") is None,
          f"completed_at_ms={task.get('completed_at_ms')}")
    check("T7.3 超时任务未指向任何记录(旧值未被误标)", task.get("record_index") is None,
          f"record_index={task.get('record_index')}")
    leaked = find_record_by_req(rid)
    check("T7.4 没有记录被打上该 request_id", leaked is None,
          "未发现污染记录" if leaked is None else f"发现异常记录 {leaked['received_at_ms']}")


# ---------------------------------------------------------------- main ----
def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual", action="store_true", help="只跑需要人工配合的 T5")
    ap.add_argument("--all", action="store_true", help="跑全部(含 T5)")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base

    out("=" * 62)
    out("  第 2 周当堂验证 —— Web 远程采集指令与执行结果反馈")
    out(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}   服务: {BASE}")
    out("=" * 62)

    if args.manual:
        t5_manual(latest())
    else:
        t0()
        t1()
        baseline = t2()
        t3()
        t4()
        if args.all:
            t5_manual(latest())
        t6()
        t7()

    passed = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    out("\n" + "=" * 62)
    out(f"  结果: {passed}/{total} 项通过")
    out("=" * 62)
    for r in RESULTS:
        if not r["ok"]:
            out(f"  未通过: {r['name']} —— {r['detail']}")

    # 写报告
    docs = Path(__file__).resolve().parent.parent / "docs"
    docs.mkdir(exist_ok=True)
    rep = docs / "week2-verification.md"
    with rep.open("w", encoding="utf-8") as f:
        f.write(f"# 第 2 周当堂验证报告\n\n")
        f.write(f"- 生成时间:{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- 服务地址:`{BASE}`  分组:`{GROUP}`  设备:`{DEVICE}`\n")
        f.write(f"- 结论:**{passed}/{total} 项通过**\n\n")
        f.write("## 逐项结果\n\n| 项 | 结果 | 明细 |\n|---|---|---|\n")
        for r in RESULTS:
            f.write(f"| {r['name']} | {'✅ PASS' if r['ok'] else '❌ FAIL'} | {r['detail']} |\n")
        f.write("\n## 原始输出\n\n```\n")
        f.write("\n".join(LOG_LINES))
        f.write("\n```\n")
    out(f"\n报告已写入: {rep}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
