"""Check authored examples in real Linux/Bash, with temporary Linux files only.

On Windows: python -X utf8 scripts/verify_linux_examples.py --wsl Ubuntu
This is a maintainer check, not a learner execution endpoint or assessment.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

LINUX_CHECK = r'''
import json, os, pathlib, subprocess, tempfile
checks = []
with tempfile.TemporaryDirectory(prefix="pliac-linux-content-") as tmp:
    root = pathlib.Path(tmp)
    def run(command, expected=None, status=0):
        env = {**os.environ, "LC_ALL": "C", "BASH_ENV": "/dev/null"}
        r = subprocess.run(["bash", "--noprofile", "--norc", "-c", "set -e\n" + command], cwd=root,
                           env=env, capture_output=True, text=True, timeout=10)
        assert r.returncode == status, (command, r.returncode, r.stderr)
        if expected is not None:
            assert r.stdout == expected, (command, r.stdout, expected)
        checks.append(command)
        return r
    (root / 'my notes').mkdir()
    # Fixtures are explicit text rather than commands supplied by learners.
    (root / 'app.log').write_text('INFO a.b\nERROR one\nWARN two\nERROR two\n')
    run("set -- 'my notes'; printf '%s\\n' \"$#\"", '1\n')
    run("mkdir -p project/data; test -d project/data")
    run("printf '%s\\n' note > notes.txt; mkdir backup; cp notes.txt backup/; test -f notes.txt; cmp notes.txt backup/notes.txt")
    run("cp notes.txt draft.txt; mv draft.txt final.txt; test ! -e draft.txt; test -e final.txt")
    run("ln -s notes.txt latest; cmp notes.txt latest; rm -- latest; test -f notes.txt")
    run("tar -cf notes.tar notes.txt; tar -tf notes.tar", 'notes.txt\n')
    run("grep -nF 'a.b' app.log", '1:INFO a.b\n')
    run("grep -E '^WARN' app.log", 'WARN two\n')
    run("grep -F 'ERROR' app.log | wc -l", '2\n')
    run("find . -type f -name '*.log'", './app.log\n')
    run("printf '%s\\n' '*.log'", '*.log\n')
    run("printf '%s\\n' 10 2 1 | sort -n", '1\n2\n10\n')
    run("printf '%s\\n' A B A | uniq", 'A\nB\nA\n')
    run("printf '%s\\n' A B A | sort | uniq", 'A\nB\n')
    run("printf 'hello' | wc -l", '0\n')
    run("printf 'hello\\n' | wc -l", '1\n')
    run("printf 'old\\n' > progress.log; printf 'done\\n' >> progress.log; cat progress.log", 'old\ndone\n')
    run("printf 'old\\n' > victim.txt; cat victim.txt > victim.txt; wc -c < victim.txt", '0\n')
    run("{ printf out; printf err >&2; } > both.log 2>&1; cat both.log", 'outerr')
    run("{ printf out; printf err >&2; } 2>&1 > only-out.log; cat only-out.log", 'errout')
    run("false | true; printf '%s\\n' \"$?\"", '0\n')
    run("set +e; set -o pipefail; false | true; printf '%s\\n' \"$?\"", '1\n')
    run("chmod 640 notes.txt; stat -c '%a' notes.txt", '640\n')
    (root / 'show.sh').write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$1"\n')
    os.chmod(root / 'show.sh', 0o600)
    run("bash show.sh 'my notes'", 'my notes\n')
    run("./show.sh 'my notes'", status=126)
    run("chmod u+x show.sh; ./show.sh 'my notes'", 'my notes\n')
    run("for file in 'a one.txt' 'b.txt'; do printf '%s\\n' \"$file\"; done", 'a one.txt\nb.txt\n')
    run("before=$PWD; bash -c 'cd /tmp'; test \"$PWD\" = \"$before\"")
    # Send TERM only to a process this verification owns, then reap it.
    proc = subprocess.Popen(['sleep', '30'])
    try:
        subprocess.run(['ps', '-p', str(proc.pid), '-o', 'pid,comm'], check=True, capture_output=True)
        proc.terminate()
        proc.wait(timeout=5)
        checks.append('inspect and terminate owned sleep process')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
print(json.dumps({'passed':True, 'checks':len(checks), 'commands':checks,
                  'environment':subprocess.check_output(['bash','--version'],text=True).splitlines()[0],
                  'temporary_linux_directory':True, 'learner_records_created':False}, ensure_ascii=False))
'''


def main():
    parser = argparse.ArgumentParser(description="在临时 Linux 目录验证固定课程算例。")
    parser.add_argument("--wsl", default="", help="Windows 下指定已有的 WSL 发行版")
    args = parser.parse_args()
    command = ["wsl", "-d", args.wsl, "--", "python3", "-"] if args.wsl else ["python3", "-"]
    result = subprocess.run(command, input=LINUX_CHECK, capture_output=True, text=True, encoding="utf-8", timeout=90)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        return result.returncode
    report = json.loads(result.stdout)
    output = ROOT / "outputs/verification/linux-course/bash-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
