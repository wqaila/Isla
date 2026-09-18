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
from collections import deque
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data.json"
MAX_RECORDS = 5000  # 内存里最多保留这么多,旧的落盘但不再驻留

app = Flask(__name__, static_folder="static", template_folder="templates")

_lock = Lock()
_records: deque[dict] = deque(maxlen=MAX_RECORDS)


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


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/data")
def receive_data():
    """板端 / 模拟器把 JSON POST 过来。"""
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
    group_id = request.args.get("group_id", "").strip()
    try:
        limit = int(request.args.get("limit", 60))
    except ValueError:
        limit = 60
    limit = max(1, min(limit, 1000))

    with _lock:
        snapshot = [r for r in _records if not group_id or r.get("group_id") == group_id]
    snapshot = snapshot[-limit:]
    return jsonify({"ok": True, "records": snapshot, "count": len(snapshot)})


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


if __name__ == "__main__":
    _load_existing()
    # 0.0.0.0 让板子能通过局域网 IP 访问
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
