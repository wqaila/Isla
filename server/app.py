"""
本机 Flask 服务:接收板端 / 模拟器上传的 IMU 数据,落盘 JSON,提供查询 API 与 Web 页面。

为什么用 JSON 文件而不是 SQLite?
- 任务卡"当堂验证"要求"对照采集值、VPS 原始记录和页面变化",
  JSON 文件可以直接记事本打开核对,排错更直观。
- 演示规模下(每秒几条)完全够用,真上量再换 SQLite 即可。

启动:
    pip install -r requirements.txt
    python app.py

浏览器打开 http://127.0.0.1:8000/
"""

from __future__ import annotations
import json
import os
import time
import uuid
from collections import deque
from pathlib import Path
from threading import Lock, RLock

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data.json"
TASK_FILE = BASE_DIR / "tasks.json"
MAX_RECORDS = 5000  # 内存里最多保留这么多,旧的落盘但不再驻留
MAX_TASKS = 200     # 内存里保留的任务数
TASK_TIMEOUT_MS = 15000   # 任务超时时间:15 秒内没完成算超时

app = Flask(__name__, static_folder="static", template_folder="templates")

_lock = Lock()
_records: deque[dict] = deque(maxlen=MAX_RECORDS)

# ---------- 采集任务(第 2 周:Web 远程采集指令) ----------
# 注意:必须用 RLock(可重入锁),因为 _persist_tasks() 内部也会获取该锁,
# 若用普通 Lock,在持有锁时调用 _persist_tasks() 会死锁。
_task_lock = RLock()
_tasks: dict[str, dict] = {}     # request_id -> task


def _persist_tasks():
    """任务落盘,便于重启后回看(仅保留最近 MAX_TASKS 条)。"""
    try:
        with _task_lock:
            items = sorted(_tasks.values(), key=lambda t: t["created_at_ms"])[-MAX_TASKS:]
        with TASK_FILE.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[server] persist tasks failed: {e}")


def _load_tasks():
    if not TASK_FILE.exists():
        return
    try:
        with TASK_FILE.open("r", encoding="utf-8") as f:
            items = json.load(f)
        with _task_lock:
            for t in items:
                rid = t.get("request_id")
                if rid:
                    _tasks[rid] = t
        print(f"[server] loaded {len(_tasks)} tasks from {TASK_FILE}")
    except Exception as e:
        print(f"[server] load tasks failed: {e}")


def _refresh_task_status(task: dict) -> dict:
    """按时间动态刷新任务状态(超时判定)。调用方需持有 _task_lock。"""
    if task["status"] in ("pending", "received"):
        age = int(time.time() * 1000) - task["created_at_ms"]
        if age > TASK_TIMEOUT_MS:
            task["status"] = "timeout"
            task["timeout_at_ms"] = int(time.time() * 1000)
    return task


def _load_existing():
    if not DATA_FILE.exists():
        return
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    _records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        print(f"[server] loaded {len(_records)} historical records from {DATA_FILE}")
    except Exception as e:
        print(f"[server] load existing data failed: {e}")


def _append_to_disk(record: dict):
    with DATA_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@app.after_request
def _no_cache_static(resp):
    """开发阶段:静态资源禁用缓存。

    否则改完 JS/CSS 后页面仍用旧文件(必须 Ctrl+F5 才生效),
    表现为"改了配置但刷新频率/点数没变"。
    """
    if request.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/data")
def receive_data():
    """板端 / 模拟器把 JSON POST 过来。

    若带 request_id,说明是响应某个采集任务,会顺带把任务标记为 completed。
    """
    if not request.is_json:
        return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 400
    try:
        data = request.get_json(force=True, silent=False)
    except Exception as e:
        return jsonify({"ok": False, "error": f"invalid json: {e}"}), 400

    # 标准化字段(没有就填空)
    record = {
        "received_at_ms": int(time.time() * 1000),
        "group_id": str(data.get("group_id", "unknown")),
        "device_id": str(data.get("device_id", "unknown")),
        "ts_ms": data.get("ts_ms"),
        "status": str(data.get("status", "ok")),
        "data": {k: v for k, v in data.items()
                 if k not in ("group_id", "device_id", "ts_ms", "status")},
    }

    with _lock:
        _records.append(record)
        try:
            _append_to_disk(record)
        except Exception as e:
            print(f"[server] persist failed: {e}")

    # ---- 如果这条数据是某个采集任务的响应,标记任务完成 ----
    req_id = data.get("request_id")
    if req_id:
        matched = False
        with _task_lock:
            task = _tasks.get(str(req_id))
            if task:
                task["status"] = "completed"
                task["completed_at_ms"] = record["received_at_ms"]
                task["elapsed_ms"] = record["received_at_ms"] - task["created_at_ms"]
                task["record_index"] = len(_records) - 1
                matched = True
        # 注意:持久化必须放在锁块之外,避免与 _persist_tasks 内部的加锁冲突
        if matched:
            _persist_tasks()
            print(f"[task] {req_id} completed in {task['elapsed_ms']} ms")

    return jsonify({"ok": True, "count": len(_records)})


@app.get("/api/latest")
def latest():
    """某分组最新一条;不传 group_id 就返回最近的任意一条。"""
    group_id = request.args.get("group_id", "").strip()
    with _lock:
        snapshot = list(_records)[::-1]  # 倒序查找
    target = None
    for r in snapshot:
        if not group_id or r.get("group_id") == group_id:
            target = r
            break
    if target is None:
        return jsonify({"ok": True, "record": None, "msg": "no data for this group"}), 200
    return jsonify({"ok": True, "record": target})


@app.get("/api/history")
def history():
    """历史记录查询。

    兼容原有参数(limit),新增 since_ms 时间范围过滤。
    since_ms: 只返回 received_at_ms >= since_ms 的记录(用于"最近1分钟/5分钟"等)
    """
    group_id = request.args.get("group_id", "").strip()
    try:
        limit = int(request.args.get("limit", 60))
    except ValueError:
        limit = 60
    limit = max(1, min(limit, 5000))

    since_ms = request.args.get("since_ms", "").strip()
    since = None
    if since_ms:
        try:
            since = int(float(since_ms))
        except ValueError:
            since = None

    with _lock:
        snapshot = [
            r for r in _records
            if (not group_id or r.get("group_id") == group_id)
            and (since is None or int(r.get("received_at_ms") or 0) >= since)
        ]
    total_matched = len(snapshot)
    # 数据量大时只取末尾 limit 条,避免一次返回过多
    truncated = total_matched > limit
    snapshot = snapshot[-limit:]
    return jsonify({
        "ok": True,
        "records": snapshot,
        "count": len(snapshot),
        "total_matched": total_matched,
        "truncated": truncated,
    })


def _flatten(record: dict) -> dict:
    """把嵌套的 record 拍平,便于统计和导出。"""
    d = record.get("data") or {}
    return {
        "received_at_ms": record.get("received_at_ms"),
        "ts_ms": record.get("ts_ms"),
        "group_id": record.get("group_id"),
        "device_id": record.get("device_id"),
        "status": record.get("status"),
        "acc_x": d.get("acc_x"),
        "acc_y": d.get("acc_y"),
        "acc_z": d.get("acc_z"),
        "acc_x_g": d.get("acc_x_g"),
        "acc_y_g": d.get("acc_y_g"),
        "acc_z_g": d.get("acc_z_g"),
        "rssi": d.get("rssi"),
        "sensor": d.get("sensor"),
        "uptime_s": d.get("uptime_s"),
        "n_samples": d.get("n_samples"),
    }


@app.get("/api/stats")
def stats():
    """对选定时间范围内的数据做统计。

    返回 X/Y/Z 与合加速度的 max/min/avg/std/peak_to_peak,以及采样质量指标。
    """
    group_id = request.args.get("group_id", "").strip()
    since_ms = request.args.get("since_ms", "").strip()
    since = None
    if since_ms:
        try:
            since = int(float(since_ms))
        except ValueError:
            since = None

    with _lock:
        rows = [
            r for r in _records
            if (not group_id or r.get("group_id") == group_id)
            and (since is None or int(r.get("received_at_ms") or 0) >= since)
        ]

    def series_of(key):
        vals = []
        for r in rows:
            v = (r.get("data") or {}).get(key)
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            vals.append(fv)
        return vals

    def describe(vals):
        if not vals:
            return None
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        return {
            "count": n,
            "min": min(vals),
            "max": max(vals),
            "avg": mean,
            "std": var ** 0.5,
            "peak_to_peak": max(vals) - min(vals),
        }

    ax, ay, az = series_of("acc_x"), series_of("acc_y"), series_of("acc_z")
    # 合加速度:按同一时刻的三轴合成
    mags = []
    for r in rows:
        d = r.get("data") or {}
        try:
            x, y, z = float(d.get("acc_x")), float(d.get("acc_y")), float(d.get("acc_z"))
        except (TypeError, ValueError):
            continue
        mags.append((x * x + y * y + z * z) ** 0.5)

    rssi = series_of("rssi")

    # ---- 采样质量 ----
    recv = sorted(int(r.get("received_at_ms") or 0) for r in rows)
    quality = {
        "record_count": len(rows),
        "duration_s": round((recv[-1] - recv[0]) / 1000.0, 2) if len(recv) > 1 else 0,
        "actual_hz": None,
        "expected_hz": 1.0,          # 板端设计为 1s 一条
        "gap_count": 0,
        "max_gap_ms": 0,
        "duplicate_ts": 0,
        "out_of_order": 0,
        "score": None,               # 0~100 数据质量分
    }
    if len(recv) > 1:
        span_s = (recv[-1] - recv[0]) / 1000.0
        quality["actual_hz"] = round((len(recv) - 1) / span_s, 3) if span_s > 0 else None
        gaps = [recv[i] - recv[i - 1] for i in range(1, len(recv))]
        # 超过 3 倍预期间隔算一次丢包
        quality["gap_count"] = sum(1 for g in gaps if g > 3000)
        quality["max_gap_ms"] = max(gaps)
        quality["out_of_order"] = sum(1 for g in gaps if g < 0)

        ts_list = [r.get("ts_ms") for r in rows if r.get("ts_ms") is not None]
        quality["duplicate_ts"] = len(ts_list) - len(set(ts_list))

        # 质量分:按时长内实际收到的比例(满分 100)
        expected = span_s * quality["expected_hz"]
        ratio = (len(recv) / expected) if expected > 0 else 0
        quality["score"] = int(max(0, min(100, round(ratio * 100))))

    return jsonify({
        "ok": True,
        "group_id": group_id or None,
        "since_ms": since,
        "acc_x": describe(ax),
        "acc_y": describe(ay),
        "acc_z": describe(az),
        "acc_magnitude": describe(mags),
        "rssi": describe(rssi),
        "quality": quality,
    })


@app.get("/api/export.csv")
def export_csv():
    """导出 CSV。字段与提示词要求一致,并保留 data 里的其他字段。"""
    import csv
    import io

    group_id = request.args.get("group_id", "").strip()
    since_ms = request.args.get("since_ms", "").strip()
    try:
        limit = int(request.args.get("limit", 5000))
    except ValueError:
        limit = 5000
    limit = max(1, min(limit, 20000))

    since = None
    if since_ms:
        try:
            since = int(float(since_ms))
        except ValueError:
            since = None

    with _lock:
        rows = [
            r for r in _records
            if (not group_id or r.get("group_id") == group_id)
            and (since is None or int(r.get("received_at_ms") or 0) >= since)
        ]
    rows = rows[-limit:]

    # 固定列 + data 里的额外列
    base_cols = ["timestamp", "received_at_ms", "device_id", "group_id",
                 "acc_x", "acc_y", "acc_z", "acc_x_g", "acc_y_g", "acc_z_g",
                 "rssi", "sensor", "uptime_s", "status"]
    extra_cols: list[str] = []
    for r in rows:
        for k in (r.get("data") or {}):
            if k not in base_cols and k not in extra_cols:
                extra_cols.append(k)
    cols = base_cols + extra_cols

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for r in rows:
        flat = _flatten(r)
        d = r.get("data") or {}
        row = []
        for c in cols:
            if c == "timestamp":
                ts = r.get("received_at_ms")
                row.append(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000.0)) if ts else "")
            elif c in flat:
                row.append(flat.get(c))
            else:
                row.append(d.get(c))
        writer.writerow(row)

    from flask import Response
    fname = f"imu_{group_id or 'all'}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        "\ufeff" + buf.getvalue(),   # BOM:Excel 打开中文不乱码
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.get("/api/groups")
def groups():
    with _lock:
        snapshot = list(_records)
    info: dict[str, dict] = {}
    for r in snapshot:
        g = r.get("group_id", "unknown")
        d = r.get("device_id", "unknown")
        info.setdefault(g, {"group_id": g, "devices": set(), "count": 0, "last_seen_ms": 0})
        info[g]["devices"].add(d)
        info[g]["count"] += 1
        if r.get("received_at_ms", 0) > info[g]["last_seen_ms"]:
            info[g]["last_seen_ms"] = r["received_at_ms"]
    for g in info.values():
        g["devices"] = sorted(g["devices"])
    return jsonify({"ok": True, "groups": sorted(info.values(), key=lambda x: x["group_id"])})


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "time_ms": int(time.time() * 1000), "count": len(_records)})


# ============================================================
#  第 2 周:Web 远程采集指令与执行结果反馈
#  流程:Web 创建任务 → 板端拉命令 → 板端采集并回执 → 状态完成/超时
# ============================================================

@app.post("/api/task")
def create_task():
    """Web 端创建一次采集任务。

    body: {"group_id": "G03", "device_id": "esp32s3-eye-01", "action": "sample"}
    返回 request_id,前端据此追踪本次采集结果。
    """
    if not request.is_json:
        return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 400
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    group_id = str(body.get("group_id", "")).strip()
    device_id = str(body.get("device_id", "")).strip()
    action = str(body.get("action", "sample")).strip() or "sample"

    if not group_id:
        return jsonify({"ok": False, "error": "group_id is required"}), 400
    if not device_id:
        # 没指定设备就取该组最近上报的设备
        with _lock:
            for r in reversed(_records):
                if r.get("group_id") == group_id:
                    device_id = str(r.get("device_id", ""))
                    break
    if not device_id:
        return jsonify({"ok": False, "error": "device_id is required (且该组暂无历史数据可推断)"}), 400

    now = int(time.time() * 1000)
    request_id = f"req-{now}-{uuid.uuid4().hex[:6]}"
    task = {
        "request_id": request_id,
        "group_id": group_id,
        "device_id": device_id,
        "action": action,
        "status": "pending",        # pending → received → completed / failed / timeout
        "created_at_ms": now,
        "dispatched_at_ms": None,   # 板端拉走命令的时间
        "received_at_ms": None,     # 板端回执"已接收"
        "completed_at_ms": None,
        "elapsed_ms": None,
        "record_index": None,       # 对应 data.json 里的记录序号
        "note": "",
    }
    with _task_lock:
        _tasks[request_id] = task
        # 清理过旧的任务,避免无限增长
        if len(_tasks) > MAX_TASKS:
            for rid in sorted(_tasks, key=lambda k: _tasks[k]["created_at_ms"])[:len(_tasks) - MAX_TASKS]:
                _tasks.pop(rid, None)
    _persist_tasks()

    print(f"[task] created {request_id} for {device_id} (group={group_id}, action={action})")
    return jsonify({"ok": True, "task": task})


@app.get("/api/command")
def get_command():
    """板端轮询:拉取属于自己的待执行任务。

    query: device_id
    返回 command=null 表示暂无任务;有任务时同时把状态置为 received。
    """
    device_id = request.args.get("device_id", "").strip()
    if not device_id:
        return jsonify({"ok": False, "error": "device_id is required"}), 400

    now = int(time.time() * 1000)
    picked = None
    with _task_lock:
        # 先刷新所有任务状态(把超时的挑出来)
        for t in _tasks.values():
            _refresh_task_status(t)
        # 取该设备最早的一个待执行任务
        candidates = [
            t for t in _tasks.values()
            if t["device_id"] == device_id and t["status"] == "pending"
        ]
        if candidates:
            picked = min(candidates, key=lambda t: t["created_at_ms"])
            picked["status"] = "received"
            picked["dispatched_at_ms"] = now
    if picked:
        _persist_tasks()
        print(f"[task] {picked['request_id']} dispatched to {device_id}")

    return jsonify({
        "ok": True,
        "command": (
            {"request_id": picked["request_id"], "action": picked["action"]}
            if picked else None
        ),
    })


@app.post("/api/ack")
def ack_task():
    """板端回执。

    body: {"request_id": "...", "device_id": "...", "stage": "received"|"started"|"failed", "note": "..."}
    """
    if not request.is_json:
        return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 400
    body = request.get_json(force=True, silent=True) or {}
    request_id = str(body.get("request_id", "")).strip()
    stage = str(body.get("stage", "received")).strip()
    note = str(body.get("note", "")).strip()

    if not request_id:
        return jsonify({"ok": False, "error": "request_id is required"}), 400

    now = int(time.time() * 1000)
    with _task_lock:
        task = _tasks.get(request_id)
        if not task:
            return jsonify({"ok": False, "error": "unknown request_id"}), 404
        if stage == "failed":
            task["status"] = "failed"
            task["completed_at_ms"] = now
            task["elapsed_ms"] = now - task["created_at_ms"]
        elif stage == "completed":
            # 不需要采集数据的命令(pause/resume 等)由板端直接回 completed
            task["status"] = "completed"
            task["received_at_ms"] = task["received_at_ms"] or now
            task["completed_at_ms"] = now
            task["elapsed_ms"] = now - task["created_at_ms"]
        else:
            task["received_at_ms"] = task["received_at_ms"] or now
            if task["status"] == "pending":
                task["status"] = "received"
        if note:
            task["note"] = note
    _persist_tasks()
    print(f"[task] {request_id} ack: {stage}")
    return jsonify({"ok": True, "task": task})


@app.get("/api/task/<request_id>")
def get_task(request_id: str):
    """查询单个任务状态(前端轮询用)。"""
    with _task_lock:
        task = _tasks.get(request_id)
        if not task:
            return jsonify({"ok": False, "error": "unknown request_id"}), 404
        _refresh_task_status(task)
        snapshot = dict(task)
    return jsonify({"ok": True, "task": snapshot})


@app.get("/api/tasks")
def list_tasks():
    """任务列表(默认最近 20 条)。"""
    group_id = request.args.get("group_id", "").strip()
    device_id = request.args.get("device_id", "").strip()
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))

    with _task_lock:
        for t in _tasks.values():
            _refresh_task_status(t)
        items = [
            dict(t) for t in _tasks.values()
            if (not group_id or t["group_id"] == group_id)
            and (not device_id or t["device_id"] == device_id)
        ]
    items.sort(key=lambda t: t["created_at_ms"], reverse=True)
    return jsonify({"ok": True, "tasks": items[:limit], "count": len(items)})


if __name__ == "__main__":
    _load_existing()
    _load_tasks()
    # 0.0.0.0 让板子能通过局域网 IP 访问
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
