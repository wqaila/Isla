"""
health.py
快速检查本机 IMU 服务是否在线、最近是否有数据。
用法:
    python scripts/health.py                # 默认查 127.0.0.1:8000
    python scripts/health.py --host 192.168.1.100
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--group", default="G03")
    args = p.parse_args()

    base = f"http://{args.host}:{args.port}"
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=2) as r:
            j = json.loads(r.read())
        print(f"[health] OK  count={j['count']}  time_ms={j['time_ms']}")
    except Exception as e:
        print(f"[health] FAIL  cannot reach {base}/api/health : {e}")
        return 1

    try:
        with urllib.request.urlopen(
            f"{base}/api/latest?group_id={args.group}", timeout=2
        ) as r:
            j = json.loads(r.read())
    except Exception as e:
        print(f"[latest] FAIL : {e}")
        return 2

    if not j.get("record"):
        print(f"[latest] group={args.group}  -> 暂无数据,请确认发送端正在运行")
        return 0

    rec = j["record"]
    import time as _t
    age = max(0, int(_t.time() * 1000) - rec["received_at_ms"]) // 1000
    print(
        f"[latest] OK  group={rec['group_id']}  device={rec['device_id']}  "
        f"status={rec['status']}  age={age}s"
    )
    return 0 if age < 10 and rec["status"] in ("ok", "simulated") else 0


if __name__ == "__main__":
    sys.exit(main())
