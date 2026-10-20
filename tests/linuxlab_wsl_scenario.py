"""Maintenance-only real Bash scenario in a temporary HOME, never student state.

Used by the PLIAC browser integration test. Deliberately creates an input error
and an incorrect backup, without completing the learner's real course.
"""
import argparse
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument('--chat', action='store_true')
    args = parser.parse_args()
    binding = json.loads(args.manifest.read_text(encoding="utf-8"))
    report_path = Path(binding["report_path"])
    with tempfile.TemporaryDirectory(prefix="pliac-native-test-") as temp:
        env = dict(os.environ, HOME=temp, TERM="xterm-256color", PYTHONUTF8="1")
        master, slave = pty.openpty()
        process = subprocess.Popen(["python3", str(args.lab / "pliac_bridge.py"), "--manifest", str(args.manifest)],
                                   env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        transcript = bytearray()

        def drain():
            if select.select([master], [], [], .05)[0]:
                try:
                    transcript.extend(os.read(master, 65536))
                except OSError:
                    pass

        def wait(predicate):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                drain()
                try:
                    if predicate():
                        return
                except (OSError, ValueError, KeyError):
                    pass
                if process.poll() is not None:
                    raise AssertionError("Native test terminal exited early (transcript withheld).")
            raise AssertionError("Native terminal test timed out (transcript withheld).")

        def report():
            return json.loads(report_path.read_text())

        def send(text):
            os.write(master, text.encode() + b"\n")

        try:
            wait(lambda: report_path.is_file() and b"LinuxLab" in transcript)
            send("mkidr scratch")
            wait(lambda: bool(report().get("input_patterns")))
            index = Path(temp) / ".local/share/pliac-linuxlab" / binding["binding_id"] / "current.json"
            native = Path(json.loads(index.read_text())["session"])
            state = json.loads((native / "state.json").read_text())
            # An isolated maintainer scenario, not a learner submission.
            send("mkdir -p work/evidence")
            send("cd airlock")
            send("lab check " + shlex.quote(state["beacon"]))
            wait(lambda: report()["phases_passed"] == 1)
            send("cd ..")
            send("lab notes cp")
            send("cp --help")
            wait(lambda: report().get('reference_total') == 2)
            send("mkdir -p work/backup")
            send("cp -a blackbox work/backup")
            send("lab check")
            wait(lambda: any(e.get("issue_code") == "backup" for e in report()["events"]))
            data = report()
            assert any(o.get("facts", {}).get("backup_nested_present") for o in data["operations"])
            assert [(r['source'], r['topic']) for r in data['reference_lookups']] == [('notes', 'cp'), ('command_help', 'cp')]
            if args.chat:
                send('lab chat --offline')
                wait(lambda: '你 > '.encode() in transcript)
                send('为什么cp复制后多了一层目录？')
                wait(lambda: report().get('dialogue_total') == 1)
                send('/exit')
                wait(lambda: '返回 Bash'.encode() in transcript)
                data = report()
                assert data['dialogue_evidence'][0]['learner']['text'] == '为什么cp复制后多了一层目录？'
                assert data['dialogue_analysis'][0]['origin'] == 'local_rule'
            assert state["beacon"] not in json.dumps(data)
            send("exit 0")
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                drain()
            assert process.poll() == 0, "Native shell did not exit cleanly"
            print(json.dumps({"native_bridge_launch": True, "real_bash_input_error": True,
                              "real_backup_check_failure": True, "operations": len(data["operations"]),
                              "events": len(data["events"]), "reference_lookups": len(data['reference_lookups']),
                              "dialogue_total": data.get('dialogue_total', 0), "temporary_home": True}))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            os.close(master)


if __name__ == "__main__":
    main()
