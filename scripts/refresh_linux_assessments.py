"""Replay imported LinuxLab evidence under the current policy, without new work.

Immutable raw reports, published graphs and prior assessment snapshots survive.
Repeated runs are idempotent. An unsynced telemetry file is never imported here.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from build_linux_course import COURSE_ID
from learning_agent.course_catalog import resolve_course
from learning_agent.course_graph import CourseGraphStore
from pliac.linux_lab import LinuxLab, read, UUID
from pliac.linux_mastery import POLICY
from pliac.linux_diagnosis import POLICY as DIAGNOSIS_POLICY


def refresh(store):
    lab = LinuxLab(store)
    refreshed, current = [], 0
    for folder in sorted(lab.runs.glob('*')):
        if folder.is_symlink() or not UUID.fullmatch(folder.name) or not (folder / 'import.json').is_file():
            continue
        summary = read(folder / 'import.json')
        if (summary.get('assessment', {}).get('policy_version') == POLICY
                and summary.get('diagnosis', {}).get('policy_version') == DIAGNOSIS_POLICY):
            current += 1
            continue
        binding = read(folder / 'binding.json')
        lab.sync(binding['binding_id'], binding['student_id'], persisted=True)
        refreshed.append(binding['binding_id'])
    return dict(policy_version=POLICY, diagnosis_policy_version=DIAGNOSIS_POLICY,
                refreshed=refreshed, already_current=current)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-id', default=COURSE_ID)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    default = CourseGraphStore(**({'output_dir': args.output_dir} if args.output_dir else {}))
    print(json.dumps(refresh(resolve_course(default, args.course_id)), ensure_ascii=False, indent=2))
