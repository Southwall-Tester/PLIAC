"""Preview by default. Execute only for an authorized learner with all writers stopped."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pliac.data_inventory import learner_inventory
from pliac.data_deletion import delete_learner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('course_root')
    parser.add_argument('student')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-offline', action='store_true')
    parser.add_argument('--confirm-student', default='')
    args = parser.parse_args()
    result = delete_learner(args.course_root, args.student, offline_confirmed=args.confirm_offline,
                            confirm_student=args.confirm_student) if args.execute else learner_inventory(args.course_root, args.student)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
