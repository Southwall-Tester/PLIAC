"""Offline backup/restore of explicit local runtime paths. No service control."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pliac.runtime_backup import backup, restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'restore'])
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('--confirm-offline', action='store_true')
    args = parser.parse_args()
    result = backup(args.source, args.destination, offline_confirmed=args.confirm_offline) if args.operation == 'backup' else restore(args.source, args.destination)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
