"""Offline runtime snapshots. Never overwrites a restore destination."""
import hashlib
import json
import shutil
from pathlib import Path

STORES = {'course_graph', 'documents'}


def checked_path(value):
    path = Path(value).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError('Redirected runtime paths are not supported.')
    # Windows short (8.3) names are aliases, not redirected directories.
    return path.resolve()


def files(root):
    result = {}
    for name in sorted(STORES):
        directory = root / name
        checked_path(directory)
        if not directory.exists():
            continue
        for path in [directory, *directory.rglob('*')]:
            if path.is_symlink() or path.is_junction():
                raise ValueError('Redirected runtime paths cannot be backed up.')
            if path.name == '.write.lock':
                raise ValueError('A writer lock exists; verify all services are stopped.')
            if path.is_file():
                result[path.relative_to(root).as_posix()] = path
    return result


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup(runtime_root, destination, *, offline_confirmed=False):
    if not offline_confirmed:
        raise ValueError('Stop all runtime writers before confirming an offline backup.')
    root, target = checked_path(runtime_root), checked_path(destination)
    if target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError('Backup must be a separate non-redirected directory outside runtime data.')
    source = files(root)
    if not source:
        raise ValueError('No supported runtime stores found.')
    entries = {name: digest(path) for name, path in source.items()}
    target.mkdir(parents=True, exist_ok=False)
    for name, path in source.items():
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)
        if digest(output) != entries[name]:
            raise ValueError('Runtime data changed while copying; incomplete backup retained.')
    if set(files(root)) != set(entries) or any(digest(path) != entries[name] for name, path in source.items()):
        raise ValueError('Runtime data changed; incomplete backup retained without manifest.')
    manifest = {'version': 1, 'offline': True, 'files': entries,
                'notice': 'Private runtime data, not encrypted. Config and code excluded. Restore with matching application version.'}
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'files': len(entries), 'destination': str(target)}


def restore(snapshot, destination):
    root, target = checked_path(snapshot), checked_path(destination)
    if target.exists() or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError('Restore requires a new non-redirected directory outside the snapshot.')
    manifest = json.loads(checked_path(root / 'manifest.json').read_text(encoding='utf-8'))
    entries = manifest.get('files')
    if manifest.get('version') != 1 or not isinstance(entries, dict) or not entries:
        raise ValueError('Invalid backup manifest.')
    actual = files(root)
    if set(actual) != set(entries):
        raise ValueError('Backup file inventory does not match manifest.')
    for name, path in actual.items():
        if digest(path) != entries[name]:
            raise ValueError('Backup integrity check failed; nothing restored.')
    target.mkdir(parents=True, exist_ok=False)
    for name, path in actual.items():
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)
        if digest(output) != entries[name]:
            raise ValueError('Restore integrity check failed; partial destination retained.')
    return {'files': len(entries), 'destination': str(target)}
