from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def access_status(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/access/session", timeout=2) as response:
            value = json.load(response).get("protected")
            return value if isinstance(value, bool) else None
    except (OSError, ValueError, AttributeError):
        return None


def describe_access(protected):
    if protected is True:
        print("身份保护已开启；这不代表已完成真实试用或公开部署验收。")
    elif protected is False:
        print("注意：当前未开启身份保护，仅用于本机开发，请勿开放真实学生数据。")
    else:
        print("无法确认运行服务的身份保护状态，请勿据此开放真实试用。")


def existing(port, student_workspace=False):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            health = json.load(response)
            if health.get("app") != "learning-agent" or "scoped_learning_units" not in health.get("capabilities", []):
                return False
            if student_workspace and health.get("student_entry") != "/app/":
                return False
        if student_workspace:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/app/", timeout=2) as response:
                return response.headers.get_content_type() == "text/html"
        # Static assets update immediately; do not reuse an incompatible old API.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/courses", timeout=2) as response:
            courses = json.load(response).get("courses")
            return isinstance(courses, list) and all("capabilities" in c and "presentation" in c for c in courses)
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="启动 PLIAC 课程个性化学习平台")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--student-workspace", action="store_true", help="打开新学生工作台；需先构建 web 前端")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65525:
        parser.error("端口须在 1024—65525 范围内。")
    if args.student_workspace and not (ROOT / "web/dist/index.html").is_file():
        print("新工作台尚未构建。请在项目 web 目录执行 npm ci，再执行 npm run build，然后重新启动。")
        return 1
    entry = "app/" if args.student_workspace else ""
    try:
        import uvicorn
        from pliac.main import app
    except ImportError as exc:
        print(f"依赖加载失败：{exc}")
        print(f"当前 Python：{sys.executable}")
        print("请在项目目录的 PowerShell 中使用同一 Python 安装依赖：")
        print(f'& "{sys.executable}" -m pip install -r requirements.txt')
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
            if existing(port, args.student_workspace):
                url = f"http://127.0.0.1:{port}/{entry}"
                print(f"工作台已在运行：{url}")
                if args.student_workspace:
                    describe_access(access_status(port))
                    print("复用已有进程；如后端代码已修改，请先手动停止旧服务再重启。")
                if not args.no_browser:
                    webbrowser.open(url)
                return 0
    if listener is None:
        print("连续 10 个端口均不可用，请通过 --port 指定其他端口。")
        return 1
    url = f"http://127.0.0.1:{port}/{entry}"
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
    if args.student_workspace:
        describe_access(os.environ.get("PLIAC_REQUIRE_AUTH") == "1")
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
