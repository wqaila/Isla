"""
PC 端 IMU 模拟器:在没拿到板子时,先生成"看上去像 IMU"的合成数据,POST 到本机服务,
用于打通板端 → 服务端 → Web 这条链路(对照任务卡"先完成一个真实传感源与一种已验证网络"前的过渡步骤)。

合成模型(简化):
    acc_z ≈ 9.8 + 0.1*sin(t)         # 重力 + 轻微上下摆
    acc_x ≈ 0.2*sin(0.7t)            # 横向摆
    acc_y ≈ 0.15*cos(0.5t)
    gyro_z ≈ 5*sin(0.3t)             # °/s 量级旋转
    温度 ≈ 26 + 0.5*sin(0.1t)        # 室温附近

使用:
    pip install requests
    python send_sim.py --server http://127.0.0.1:8000 --group G03 --device sim-pc-01 --hz 2
"""
import argparse
import json
import math
import random
import time
import sys
from datetime import datetime

import requests


def gen_sample(t: float):
    return {
        "ts_ms": int(time.time() * 1000),
        "acc_x": round(0.20 * math.sin(0.7 * t) + random.gauss(0, 0.02), 4),
        "acc_y": round(0.15 * math.cos(0.5 * t) + random.gauss(0, 0.02), 4),
        "acc_z": round(9.80665 + 0.10 * math.sin(1.0 * t) + random.gauss(0, 0.02), 4),
        "gyro_x": round(0.5 * math.sin(0.4 * t) + random.gauss(0, 0.1), 3),
        "gyro_y": round(0.5 * math.cos(0.6 * t) + random.gauss(0, 0.1), 3),
        "gyro_z": round(5.0 * math.sin(0.3 * t) + random.gauss(0, 0.1), 3),
        "temp_c": round(26.0 + 0.5 * math.sin(0.1 * t) + random.gauss(0, 0.05), 2),
        "status": "ok",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--group", default="G03")
    p.add_argument("--device", default="sim-pc-01")
    p.add_argument("--hz", type=float, default=2.0, help="每秒发送次数")
    p.add_argument("--duration", type=float, default=0, help="持续秒数,0 表示无限")
    args = p.parse_args()

    url = args.server.rstrip("/") + "/api/data"
    period = 1.0 / max(0.1, args.hz)
    t0 = time.time()
    sent = 0
    print(f"[sim] POST -> {url}  group={args.group}  hz={args.hz}")
    try:
        while True:
            t = time.time() - t0
            payload = gen_sample(t)
            payload["group_id"] = args.group
            payload["device_id"] = args.device
            payload["uptime_s"] = round(t, 2)
            try:
                r = requests.post(url, json=payload, timeout=3)
                ok = r.ok
                txt = r.text.strip()
            except Exception as e:
                ok, txt = False, str(e)
            sent += 1
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[sim] {ts} #{sent:04d}  acc=({payload['acc_x']:+.3f},"
                  f"{payload['acc_y']:+.3f},{payload['acc_z']:+.3f})  "
                  f"resp={'OK' if ok else 'FAIL'} {txt[:60]}")
            if args.duration and t >= args.duration:
                print(f"[sim] duration {args.duration}s reached, stop.")
                break
            time.sleep(period)
    except KeyboardInterrupt:
        print("\n[sim] stopped by user.")


if __name__ == "__main__":
    main()
