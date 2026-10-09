"""Select an installed project environment for the Windows double-click entries."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Import names corresponding to requirements.txt. Probe without importing the app
# so choosing an interpreter cannot initialize course or learner stores.
MODULES = (
    "fastapi", "uvicorn", "networkx", "pymupdf", "multipart", "jieba",
    "pkg_resources", "sklearn", "pydantic", "httpx", "pypdf", "PIL",
    "playwright", "jinja2", "markdown_it", "platformdirs",
)


def candidates():
    paths = [ROOT / ".venv" / "Scripts" / "python.exe", Path(sys.executable)]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            paths.append(Path(entry.strip('"')) / "python.exe")
    seen = set()
    for path in paths:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen and path.is_file():
            seen.add(key)
            yield path


def available(python):
    probe = (
        "import importlib.util; "
        f"raise SystemExit(0 if all(importlib.util.find_spec(m) is not None for m in {MODULES!r}) else 1)"
    )
    try:
        result = subprocess.run(
            [str(python), "-X", "utf8", "-c", probe],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    checked = list(candidates())
    for python in checked:
        if available(python):
            print(f"使用 Python：{python}", flush=True)
            try:
                return subprocess.call(
                    [str(python), "-X", "utf8", str(ROOT / "scripts" / "run.py"), *sys.argv[1:]],
                    cwd=ROOT,
                )
            except KeyboardInterrupt:
                return 130
    print("未找到已安装项目依赖的 Python。已检查：")
    for python in checked:
        print(f"  {python}")
    print("请在项目目录的 PowerShell 中运行：")
    print(f'& "{sys.executable}" -m pip install -r requirements.txt')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
