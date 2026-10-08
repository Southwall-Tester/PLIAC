"""Replay a checked-in scanned graph against the real browser renderer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'datasets/stress/manifest.json').read_text(encoding='utf-8'))
    samples = {s['name']: s for s in manifest['samples']}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', choices=samples, default='computer-organization')
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    parser.add_argument('--browser-channel', default='')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    sample = samples[args.sample]
    raw = (ROOT / 'datasets/stress' / sample['file']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sample['sha256']:
        raise SystemExit('样本 SHA-256 不符，请恢复仓库内的原始文件。')
    graph = json.loads(raw)
    ids = {n['id'] for n in graph['nodes']}
    assert len(ids) == sample['nodes'] and len(graph['edges']) == sample['edges']
    assert all(e['source'] in ids and e['target'] in ids for e in graph['edges'])
    print(f"{args.sample}: {len(ids)} nodes, {len(graph['edges'])} edges, SHA-256 OK", flush=True)
    if args.verify_only:
        return
    target = ROOT / 'outputs/verification' / (args.sample + '-snapshot.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'base_url': args.base_url, 'job': sample['job'], 'graph': graph},
                                 ensure_ascii=False), encoding='utf-8')
    command = [sys.executable, '-X', 'utf8', str(ROOT / 'tests/test_ui_large_graph.py'),
               '--snapshot', str(target), '--base-url', args.base_url, '--tag', args.sample]
    if args.browser_channel:
        command.extend(['--browser-channel', args.browser_channel])
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
