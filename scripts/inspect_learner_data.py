"""Read-only inventory for one explicit learner and course runtime root."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pliac.data_inventory import learner_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('course_root')
    parser.add_argument('student')
    args = parser.parse_args()
    print(json.dumps(learner_inventory(args.course_root, args.student), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
