from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def existing(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            health = json.load(response)
            if health.get("app") != "learning-agent" or "acceptance_course" not in health.get("capabilities", []):
                return False
        # An older server may share the assets while lacking the course catalog API.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/courses", timeout=2) as response:
            return isinstance(json.load(response).get("courses"), list)
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="启动 PLIAC 课程个性化学习平台")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65525:
        parser.error("端口须在 1024—65525 范围内。")
    try:
        import uvicorn
        from pliac.main import app
    except ImportError as exc:
        print(f"缺少依赖 {exc.name}，请在项目目录运行：pip install -r requirements.txt")
        return 1
    listener = None
    for port in range(args.port, args.port + 10):
        candidate = socket.socket()
        try:
            candidate.bind(("127.0.0.1", port))
            listener = candidate
            break
        except OSError:
            candidate.close()
            if existing(port):
                url = f"http://127.0.0.1:{port}/courses"
                print(f"工作台已在运行：{url}")
                if not args.no_browser:
                    webbrowser.open(url)
                return 0
    if listener is None:
        print("连续 10 个端口均不可用，请通过 --port 指定其他端口。")
        return 1
    url = f"http://127.0.0.1:{port}/courses"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
    if not args.no_browser:
        def ready():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if server.started:
                    webbrowser.open(url)
                    return
                time.sleep(.1)
        threading.Thread(target=ready, daemon=True).start()
    print(f"课程入口：{url}\n关闭窗口或按 Ctrl+C 停止服务。", flush=True)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
