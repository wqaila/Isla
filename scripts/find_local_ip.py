"""
find_local_ip.py
找到本机所有 IPv4 地址(命令行友好),帮你决定填到 board/config.h 的 SERVER_HOST。

用法:
    python find_local_ip.py
输出示例:
    192.168.1.100  (你的电脑在局域网里的地址 —  板子用这个)
    127.0.0.1      (仅本机访问,板子请用上面那个)

为什么不用 socket.getfqdn() 或 requests.get("ifconfig.me"):
1. fqdn 在 WiFi 重连后可能指错网卡
2. 外网 IP 在没有路由时拿不到
我们直接枚举所有网卡接口,挑 IPv4。
"""

from __future__ import annotations
import socket
import sys


def list_ips() -> list[tuple[str, str]]:
    """返回 [(ip, 备注)] 列表。"""
    out: list[tuple[str, str]] = []

    # 回环
    out.append(("127.0.0.1", "本机回环,只有这台电脑能访问"))

    # 主机名也可能解析到 LAN IP
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
        if host_ip not in [ip for ip, _ in out]:
            out.append((host_ip, "主机名解析到的 IP"))
    except Exception:
        pass

    # UDP socket trick:连一个外部地址(不发数据),让系统挑默认网卡
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))  # 阿里 DNS,不会真发数据
        ip = s.getsockname()[0]
        if ip not in [x for x, _ in out]:
            out.append((ip, "默认出网网卡(最可能是 WiFi)"))
    except Exception:
        pass
    finally:
        s.close()

    return out


def main() -> int:
    ips = list_ips()
    print("=" * 60)
    print("  本机 IPv4 地址")
    print("=" * 60)
    for ip, note in ips:
        print(f"  {ip:<18}  {note}")
    print("=" * 60)
    print()
    # 推荐的填法
    lan = None
    for ip, note in ips:
        if ip != "127.0.0.1" and not ip.startswith("169.254"):
            lan = ip
            break
    if lan:
        print(f"👉  把下面这行写进 board/config.h:")
        print(f'    #define SERVER_HOST     "{lan}"')
        print(f"    #define SERVER_PORT     8000")
    else:
        print("⚠️  没找到局域网 IP,可能网线没插/WiFi 没连。先连网再跑。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
