"""Build local IR artifacts from explicitly supplied saved HTML or parsed records."""
import argparse
import hashlib
import json
from pathlib import Path

from ui_ir.bridge import invoke, parse_documents


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--html', type=Path, action='append', help='Admitted saved HTML; repeat for multiple documents')
    inputs.add_argument('--records', type=Path, help='DOMEvidence JSON; skips browser parsing')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--snapshot-id')
    parser.add_argument('--profile', choices=['structure', 'excerpt', 'budget'], default='structure')
    parser.add_argument('--max-bytes', type=int, default=200000)
    parser.add_argument('--no-partitions', action='store_true')
    args = parser.parse_args(argv)
    if args.max_bytes <= 0:
        parser.error('--max-bytes must be positive')
    if args.records:
        if args.records.stat().st_size > 32 * 1024 * 1024:
            parser.error('Parsed-record input exceeds 32 MiB')
        evidence = json.loads(args.records.read_text())
        if args.snapshot_id:
            evidence['snapshotId'] = args.snapshot_id
    else:
        documents, digest = [], hashlib.sha256()
        for i, path in enumerate(args.html):
            if path.stat().st_size > 10_000_000:
                parser.error('A source HTML document exceeds 10 MB')
            source = path.read_bytes()
            digest.update(len(source).to_bytes(8, 'big'))
            digest.update(source)
            documents.append({'id': f'd{i}', 'html': source.decode('utf-8'), 'sourceHash': hashlib.sha256(source).hexdigest()})
        evidence = {'snapshotId': args.snapshot_id or digest.hexdigest(), 'documents': parse_documents(documents)}
    result = invoke({'operation': 'pipeline', 'input': evidence, 'request': {
        'profile': args.profile, 'maxBytes': args.max_bytes, 'planRegions': not args.no_partitions,
    }})
    navigation = invoke({'operation': 'navigation', 'view': result['result']['view'],
                         'observation': result['bundle']['observation']})
    args.out.mkdir(parents=True, exist_ok=True)
    artifacts = {
        'observation.json': result['bundle']['observation'],
        'grounding.json': result['bundle']['grounding'],
        'evidence.json': result['bundle']['evidence'],
        'adapter-audit.json': result['bundle']['audit'],
        'view.json': result['result']['view'],
        'compaction-ledger.json': result['result']['ledger'],
        'compaction-report.json': result['result']['report'],
        'model-packet.json': result['packet'],
        'navigation-packet.json': navigation,
        'regions.json': result.get('regionPackets', []),
    }
    manifest = {'snapshotId': evidence['snapshotId'], 'profile': args.profile, 'status': result['result']['report']['status'], 'artifacts': {}}
    for filename, value in artifacts.items():
        path = args.out / filename
        if path.is_symlink():
            raise ValueError('Output artifacts must not be symlinks')
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        path.write_bytes(raw)
        manifest['artifacts'][filename] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    model_path = args.out / 'model-input.json'
    if model_path.is_symlink():
        raise ValueError('Output artifacts must not be symlinks')
    model_raw = result['packet']['text'].encode()
    model_path.write_bytes(model_raw)
    manifest['artifacts']['model-input.json'] = {'bytes': len(model_raw), 'sha256': hashlib.sha256(model_raw).hexdigest()}
    navigation_path = args.out / 'navigation-input.json'
    if navigation_path.is_symlink():
        raise ValueError('Navigation artifacts must not be symlinks')
    navigation_raw = navigation['text'].encode()
    navigation_path.write_bytes(navigation_raw)
    manifest['artifacts'][navigation_path.name] = {'bytes': len(navigation_raw), 'sha256': hashlib.sha256(navigation_raw).hexdigest()}
    manifest['navigation'] = {'representation': 'ui-navigation/0.1', 'eligibleNodes': len(navigation['eligibleIds']),
                              'bytes': len(navigation_raw)}
    manifest_path = args.out / 'manifest.json'
    if manifest_path.is_symlink():
        raise ValueError('Manifest must not be a symlink')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'output': str(args.out), **result['result']['report']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
