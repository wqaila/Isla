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

import nlq  # 第 4 周:自然语言查询的意图解析(规则式,可离线运行)

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
        # 响应采集任务时板端会把 request_id 放在 data 里,顶层也可能有
        # (第 2 周验收要点:新观测必须能追溯到是哪次采集请求产生的)
        "request_id": record.get("request_id") or d.get("request_id"),
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


def _filter_rows(group_id: str = "", since_ms: int | None = None) -> list[dict]:
    """按 group_id / 时间下界过滤内存记录。

    抽出来是为了让第 4 周的 `/api/nlq` 与 `/api/stats` 用同一套过滤口径,
    避免"页面统计"和"问一句话得到的统计"对不上。
    """
    with _lock:
        return [
            r for r in _records
            if (not group_id or r.get("group_id") == group_id)
            and (since_ms is None or int(r.get("received_at_ms") or 0) >= since_ms)
        ]


def _describe_all(rows: list[dict]) -> dict:
    """对一批记录算 X/Y/Z/合加速度/RSSI 的统计量 + 采样质量。"""
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

    return {
        "ok": True,
        "acc_x": describe(ax),
        "acc_y": describe(ay),
        "acc_z": describe(az),
        "acc_magnitude": describe(mags),
        "rssi": describe(rssi),
        "quality": quality,
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

    rows = _filter_rows(group_id, since)
    result = _describe_all(rows)
    result["group_id"] = group_id or None
    result["since_ms"] = since
    return jsonify(result)


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

def _new_task(group_id: str, device_id: str, action: str) -> dict:
    """创建一个任务并落盘。

    抽成独立函数,是为了让第 4 周的 `/api/nlq` 能复用同一套创建逻辑,
    保证「点按钮」和「说一句话」走的是完全相同的代码路径。
    """
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
    return task


def _resolve_device_id(group_id: str, device_id: str = "") -> str:
    """没指定设备时,取该组最近上报过的那个设备。"""
    device_id = (device_id or "").strip()
    if device_id:
        return device_id
    with _lock:
        for r in reversed(_records):
            if r.get("group_id") == group_id:
                return str(r.get("device_id", ""))
    return ""


# ============================================================
#  第 4 周:自然语言查询与请求采集
#
#  分工:`nlq.py` 只负责"听懂这句话",这里负责"真的去查 / 真的下发任务"。
#    - 查询类(latest/stats/count/device_status/events)直接读内存记录,纯本地;
#    - 动作类(sample/pause/resume)复用第 2 周的任务通道 `_new_task()`,
#      所以"说一句话"和"点按钮"走的是同一条代码路径,结果可以互相对照。
#    - 板端不在线时,动作类会如实超时,绝不把"已下发"说成"已采集成功"。
# ============================================================
NLQ_WAIT_MS = 12000     # 动作类最长等待板端回执的时间(略小于任务超时 15s)
ONLINE_AGE_MS = 10000   # 最后一条数据距今小于这个值才算"在线"

_METRIC_KEY = {"x": "acc_x", "y": "acc_y", "z": "acc_z", "mag": "acc_magnitude"}
_METRIC_CN2 = {"x": "X 轴", "y": "Y 轴", "z": "Z 轴", "mag": "合加速度"}
_AGG_CN2 = {
    "max": "最大值", "min": "最小值", "avg": "平均值",
    "std": "标准差", "peak_to_peak": "峰峰值",
}


def _default_group_id() -> str:
    """没指定组时,用最近一条上报记录的组。"""
    with _lock:
        for r in reversed(_records):
            if r.get("group_id"):
                return str(r["group_id"])
    return ""


def _human_ago(ms) -> str:
    if not ms:
        return "未知"
    d = int(time.time() * 1000) - int(ms)
    d = max(d, 0)
    if d < 1000:
        return f"{d} 毫秒前"
    if d < 60_000:
        return f"{d / 1000:.1f} 秒前"
    if d < 3_600_000:
        return f"{d / 60_000:.1f} 分钟前"
    if d < 86_400_000:
        return f"{d / 3_600_000:.1f} 小时前"
    return f"{d / 86_400_000:.1f} 天前"


def _fmt_num(v, nd: int = 3) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _wait_task(request_id: str, timeout_ms: int = NLQ_WAIT_MS):
    """等任务进入终态(completed / failed / timeout),返回快照。"""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        with _task_lock:
            t = _tasks.get(request_id)
            if t:
                _refresh_task_status(t)
                if t["status"] in ("completed", "failed", "timeout"):
                    return dict(t)
        time.sleep(0.2)
    with _task_lock:
        t = _tasks.get(request_id)
        return dict(t) if t else None


def _find_record_of_task(request_id: str):
    """找到某次采集任务对应上传的那条数据记录(用于把采样值回给用户)。"""
    if not request_id:
        return None
    with _lock:
        for r in reversed(list(_records)):
            if r.get("request_id") == request_id:
                return dict(r)
            d = r.get("data") or {}
            if d.get("request_id") == request_id:
                return dict(r)
    return None


@app.post("/api/nlq")
def nlq_query():
    """自然语言查询。body: {"text": "...", "group_id": "G03", "wait": true}

    返回:解析结果 + 一句人类可读的 answer + 结构化 data(前端渲染用)。
    """
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        # 空输入不算错误:给一句引导,前端直接展示即可
        return jsonify({
            "ok": True, "text": "", "intent": "empty", "parsed": nlq.parse(""),
            "answer": "你还没输入内容。可以试试「现在加速度是多少」。",
            "data": {}, "task": None,
        })

    group_id = str(body.get("group_id") or "").strip() or _default_group_id()
    device_id = str(body.get("device_id") or "").strip()
    want_wait = body.get("wait")
    wait = True if want_wait is None else bool(want_wait)

    parsed = nlq.parse(text)
    intent = parsed["intent"]
    slots = parsed.get("slots") or {}
    now = int(time.time() * 1000)
    since_ms = slots.get("since_ms")
    since = (now - int(since_ms)) if since_ms else None

    answer = ""
    data: dict = {}
    task_snapshot = None

    # ---------------------------------------------------------- 查询类
    if intent == "latest":
        rows = _filter_rows(group_id, None)
        if not rows:
            answer = f"组 {group_id or '(未知)'} 目前一条数据都没有。"
        else:
            r = rows[-1]
            d = r.get("data") or {}
            try:
                x, y, z = float(d.get("acc_x")), float(d.get("acc_y")), float(d.get("acc_z"))
                mag = (x * x + y * y + z * z) ** 0.5
            except (TypeError, ValueError):
                x = y = z = mag = None
            data = {
                "record": _flatten(r),
                "acc_x": x, "acc_y": y, "acc_z": z, "acc_magnitude": mag,
                "received_at_ms": r.get("received_at_ms"),
                "age_ms": now - int(r.get("received_at_ms") or 0),
                "device_id": r.get("device_id"),
                "rssi": (r.get("data") or {}).get("rssi"),
            }
            answer = (
                f"最新一条(来自 {r.get('device_id') or '未知设备'},{_human_ago(r.get('received_at_ms'))}):"
                f"X={_fmt_num(x)} Y={_fmt_num(y)} Z={_fmt_num(z)} m/s²,"
                f"合加速度={_fmt_num(mag)} m/s²(约 {_fmt_num((mag or 0) / 9.80665)} g)。"
            )

    elif intent == "stats":
        metric = slots.get("metric", "mag")
        agg = slots.get("agg", "avg")
        key = _METRIC_KEY[metric]
        rows = _filter_rows(group_id, since)
        st = _describe_all(rows)
        s = st.get(key)
        if not s:
            answer = (
                f"{'最近 ' + nlq.human_ms(since_ms) if since_ms else '全部'}范围内没有可用数据,"
                f"算不出{_METRIC_CN2[metric]}的{_AGG_CN2[agg]}。"
            )
        else:
            scope = f"最近 {nlq.human_ms(since_ms)}" if since_ms else "全部数据"
            data = {"scope": scope, "metric": metric, "agg": agg,
                    "value": s[agg], "count": s["count"], "stat": s}
            answer = (
                f"{scope}({s['count']} 条样本)内,{_METRIC_CN2[metric]}的"
                f"{_AGG_CN2[agg]} = {_fmt_num(s[agg])} m/s²"
                f"(最小 {_fmt_num(s['min'])} / 最大 {_fmt_num(s['max'])} / 标准差 {_fmt_num(s['std'])})。"
            )

    elif intent == "count":
        rows = _filter_rows(group_id, since)
        scope = f"最近 {nlq.human_ms(since_ms)}" if since_ms else "全部"
        with _lock:
            total = len([r for r in _records if (not group_id or r.get("group_id") == group_id)])
        data = {"scope": scope, "count": len(rows), "total": total,
                "duration_s": _describe_all(rows)["quality"]["duration_s"]}
        answer = f"{scope}共 {len(rows)} 条数据(该组累计 {total} 条)。"

    elif intent == "device_status":
        rows = _filter_rows(group_id, None)
        if not rows:
            answer = f"组 {group_id or '(未知)'} 没有任何上报记录,无法判断设备状态 —— 我不能说它在线。"
            data = {"online": None}
        else:
            r = rows[-1]
            age = now - int(r.get("received_at_ms") or 0)
            online = age < ONLINE_AGE_MS
            recent = _describe_all(_filter_rows(group_id, now - 60_000))["rssi"]
            data = {
                "online": online,
                "device_id": r.get("device_id"),
                "age_ms": age,
                "last_seen_ms": r.get("received_at_ms"),
                "rssi_last": (r.get("data") or {}).get("rssi"),
                "rssi_avg_1min": recent["avg"] if recent else None,
                "actual_hz": _describe_all(_filter_rows(group_id, now - 60_000))["quality"]["actual_hz"],
            }
            if online:
                answer = (
                    f"{r.get('device_id')} 在线:最后一条数据 {_human_ago(r.get('received_at_ms'))},"
                    f"RSSI {_fmt_num((r.get('data') or {}).get('rssi'), 0)} dBm,"
                    f"最近 1 分钟实际频率 {data['actual_hz'] or '—'} Hz。"
                )
            else:
                answer = (
                    f"{r.get('device_id')} 目前离线:最后一条数据是 {_human_ago(r.get('received_at_ms'))}"
                    f"({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime((r.get('received_at_ms') or 0) / 1000))})。"
                    f"我不会把它当成在线。"
                )

    elif intent == "events":
        with _event_lock:
            items = [dict(e) for e in _events.values()
                     if (not group_id or e["group_id"] == group_id)]
        items.sort(key=lambda e: e["received_at_ms"], reverse=True)
        unacked = [e for e in items if e["status"] == "received"]
        data = {"count": len(items), "unacked": len(unacked), "events": items[:10]}
        if not items:
            answer = "服务端还没收到过任何按键事件。"
        else:
            answer = (
                f"服务端共收到 {len(items)} 次按键触发,最近一次 {_human_ago(items[0]['received_at_ms'])},"
                f"其中 {len(unacked)} 次还没被回应。"
            )

    # ---------------------------------------------------------- 动作类
    elif intent in ("sample", "pause", "resume"):
        if not group_id:
            answer = "还不知道要给哪个组下发(没有任何历史数据可推断),请先确认设备在上报。"
            return jsonify({"ok": True, "text": text, "intent": intent, "parsed": parsed,
                            "answer": answer, "data": {}, "task": None})
        device_id = _resolve_device_id(group_id, device_id)
        if not device_id:
            answer = f"组 {group_id} 没有历史数据,推断不出设备 ID,无法下发命令。"
            return jsonify({"ok": True, "text": text, "intent": intent, "parsed": parsed,
                            "answer": answer, "data": {}, "task": None})

        task = _new_task(group_id, device_id, intent)
        task_snapshot = dict(task)
        if wait:
            task_snapshot = _wait_task(task["request_id"]) or dict(task)

        status = task_snapshot.get("status")
        elapsed = task_snapshot.get("elapsed_ms")
        if status == "completed":
            if intent == "sample":
                rec = _find_record_of_task(task_snapshot["request_id"])
                d = (rec or {}).get("data") or {}
                data = {"record": _flatten(rec) if rec else None}
                if rec:
                    answer = (
                        f"已采集成功(耗时 {elapsed} ms):"
                        f"X={_fmt_num(d.get('acc_x'))} Y={_fmt_num(d.get('acc_y'))} "
                        f"Z={_fmt_num(d.get('acc_z'))} m/s²。"
                    )
                else:
                    answer = f"板端回执已完成(耗时 {elapsed} ms),但没找到对应数据记录。"
            elif intent == "pause":
                answer = f"已让板端暂停周期上报(耗时 {elapsed} ms),命令通道仍保持。"
            else:
                answer = f"已让板端恢复周期上报(耗时 {elapsed} ms)。"
        elif status == "failed":
            answer = f"板端报告执行失败:{task_snapshot.get('note') or '无备注'}。"
        elif status == "timeout":
            answer = (
                f"命令已下发,但 {NLQ_WAIT_MS} ms 内没等到板端回执(超时)。"
                f"这通常意味着板子离线或断网 —— 我不会把它算作执行成功。"
            )
        else:
            answer = f"命令已下发,当前状态 {status}(板端还没回执)。"

    elif intent == "help":
        answer = nlq.HELP_TEXT
        data = {"help": True}

    else:  # unknown / empty
        answer = (
            f"没听懂「{text}」。目前我能处理这几类:"
            "查当前值、查统计、查设备在线、查数据量、查按键事件、远程采集一次、暂停/恢复上报。"
            "输入「你能做什么」看完整示例。"
        )

    return jsonify({
        "ok": True,
        "text": text,
        "intent": intent,
        "parsed": parsed,
        "answer": answer,
        "data": data,
        "task": task_snapshot,
    })


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
        # 给板端对表用:板子没有 RTC,靠这个值把 millis() 换算成墙上时钟,
        # 这样"本地确认时刻"才能和"服务端收到时刻"做真实对比。
        "server_time_ms": now,
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


# ==================================================================
#  第 3 周:按键触发事件(本地确认 与 远端接收 严格分离)
#
#  核心原则(任务卡要求):
#    - 板端按下按键 → 本地立即确认(屏幕有反馈),这是【本地证据】
#    - 事件 POST 到服务端 → 才算【远端收到】
#    - 二者是两件事:断网时本地仍能确认,但服务端没有该事件,
#      页面绝不能显示"对方已收到"。
#    - 所以服务端只记录它【真正收到过】的事件,不臆造状态。
# ==================================================================
EVENT_FILE = BASE_DIR / "events.json"
MAX_EVENTS = 200

_event_lock = RLock()
_events: dict[str, dict] = {}          # event_id -> event
# 待下发给板端的回应/取消:event_id -> {"action": "ack"|"cancel", "note": str}
_event_cmds: dict[str, dict] = {}


def _persist_events():
    try:
        with _event_lock:
            items = sorted(_events.values(), key=lambda e: e["received_at_ms"])[-MAX_EVENTS:]
        with EVENT_FILE.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[server] persist events failed: {e}")


def _load_events():
    if not EVENT_FILE.exists():
        return
    try:
        with EVENT_FILE.open("r", encoding="utf-8") as f:
            items = json.load(f)
        with _event_lock:
            for e in items:
                eid = e.get("event_id")
                if eid:
                    _events[eid] = e
        print(f"[server] loaded {len(_events)} events from {EVENT_FILE}")
    except Exception as e:
        print(f"[server] load events failed: {e}")


@app.post("/api/event")
def receive_event():
    """板端上报一次本地触发。

    板端必须先在本地给出反馈(屏幕),再来上报。
    这里只登记"服务端确实收到了",不修改板端的本地状态。
    """
    body = request.get_json(silent=True) or {}
    event_id = str(body.get("event_id") or "").strip()
    if not event_id:
        return jsonify({"ok": False, "error": "missing event_id"}), 400

    now = int(time.time() * 1000)
    with _event_lock:
        if event_id in _events:
            ev = _events[event_id]          # 重传/重复上报:不重复建,也不改状态
            ev["resend_count"] = ev.get("resend_count", 0) + 1
        else:
            ev = {
                "event_id": event_id,
                "group_id": str(body.get("group_id") or "").strip(),
                "device_id": str(body.get("device_id") or "").strip(),
                "type": str(body.get("type") or "button_press"),
                # 板端本地确认时刻(墙上时钟,由板端用 server_time_ms 对表后填)
                "local_confirmed_at_ms": body.get("local_confirmed_at_ms"),
                # 兜底:板上电毫秒数,始终有效。local 为 0 表示当时还没对上表
                "local_uptime_ms": body.get("local_uptime_ms"),
                # 服务端真正收到的时刻 —— 这才是"远端已收到"的证据
                "received_at_ms": now,
                "status": "received",       # received → acked / cancelled
                "acked_at_ms": None,
                "cancelled_at_ms": None,
                "note": str(body.get("note") or ""),
                "resend_count": 0,
            }
            _events[event_id] = ev
        snapshot = dict(ev)
    _persist_events()
    return jsonify({"ok": True, "event": snapshot})


@app.get("/api/events")
def list_events():
    """事件列表(前端展示)。按服务端收到时间倒序。"""
    group_id = request.args.get("group_id", "").strip()
    device_id = request.args.get("device_id", "").strip()
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))

    with _event_lock:
        items = [
            dict(e) for e in _events.values()
            if (not group_id or e["group_id"] == group_id)
            and (not device_id or e["device_id"] == device_id)
        ]
    items.sort(key=lambda e: e["received_at_ms"], reverse=True)
    return jsonify({"ok": True, "events": items[:limit], "count": len(items)})


@app.post("/api/event/<event_id>/ack")
def ack_event(event_id: str):
    """远端回应某个事件(页面点"已收到/回应")。

    入队一条 ack 命令,等板端轮询取走 —— 板端收到后才更新自己的屏幕。
    """
    body = request.get_json(silent=True) or {}
    note = str(body.get("note") or "").strip()
    now = int(time.time() * 1000)
    with _event_lock:
        ev = _events.get(event_id)
        if not ev:
            return jsonify({"ok": False, "error": "event not found"}), 404
        if ev["status"] == "cancelled":
            return jsonify({"ok": False, "error": "event already cancelled"}), 409
        ev["status"] = "acked"
        ev["acked_at_ms"] = now
        if note:
            ev["note"] = note
        _event_cmds[event_id] = {"action": "ack", "note": note, "at_ms": now}
        snapshot = dict(ev)
    _persist_events()
    return jsonify({"ok": True, "event": snapshot})


@app.post("/api/event/<event_id>/cancel")
def cancel_event(event_id: str):
    """远端取消某个事件(页面点"取消")。"""
    body = request.get_json(silent=True) or {}
    note = str(body.get("note") or "").strip()
    now = int(time.time() * 1000)
    with _event_lock:
        ev = _events.get(event_id)
        if not ev:
            return jsonify({"ok": False, "error": "event not found"}), 404
        ev["status"] = "cancelled"
        ev["cancelled_at_ms"] = now
        if note:
            ev["note"] = note
        _event_cmds[event_id] = {"action": "cancel", "note": note, "at_ms": now}
        snapshot = dict(ev)
    _persist_events()
    return jsonify({"ok": True, "event": snapshot})


@app.get("/api/event/pending")
def event_pending():
    """板端轮询:取走待处理的回应/取消命令。

    返回后立即出队(与第 2 周 /api/command 的语义一致:领走即消费)。
    """
    device_id = request.args.get("device_id", "").strip()
    updates = []
    with _event_lock:
        for eid in list(_event_cmds.keys()):
            cmd = _event_cmds.pop(eid)
            ev = _events.get(eid)
            if ev and (not device_id or ev["device_id"] == device_id):
                updates.append({"event_id": eid, **cmd})
    return jsonify({"ok": True, "updates": updates})


if __name__ == "__main__":
    _load_existing()
    _load_tasks()
    _load_events()
    # 0.0.0.0 让板子能通过局域网 IP 访问
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
