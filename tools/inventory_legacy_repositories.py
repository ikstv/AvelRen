"""Побудувати санітизований реєстр TASK-01 з перевірених локальних копій.

Не копіює вміст джерел, secrets чи assets; не виконує мережевих запитів,
push, merge, deployment або імпорт історії. Різні реалізації без доказів
залишаються needs-port (потрібна предметна звірка), а не автоматично accepted.
"""
import argparse
import ast
import collections
import hashlib
import json
import re
import subprocess
from pathlib import Path


def git(repo, *args, data=None):
    p = subprocess.run(['git', '-C', str(repo), *args], input=data, capture_output=True)
    if p.returncode:
        raise RuntimeError(f'Git {args[0]}: {p.returncode}; вміст журналу приховано')
    return p.stdout


def tree(repo, ref):
    result = {}
    for entry in git(repo, 'ls-tree', '-rz', ref).split(b'\0'):
        if entry:
            meta, path = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            result[path.decode()] = {'mode': mode, 'kind': kind, 'blob': oid}
    return result


def ast_without_docstrings(data):
    try:
        parsed = ast.parse(data.decode('utf-8-sig'))
        for node in ast.walk(parsed):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr):
                    value = node.body[0].value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        node.body.pop(0)
        return ast.dump(parsed, include_attributes=False)
    except (ValueError, SyntaxError, UnicodeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.private_root.resolve()
    checkout = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Вихід уже існує; перезапис заборонений')
    output.mkdir(parents=True)
    acquired = json.loads((root / 'acquisition.json').read_text(encoding='utf-8'))
    scanner = json.loads((root / 'scan-summary.json').read_text(encoding='utf-8'))
    target_repo = root / 'AvelRen-ORIGINAL.git'
    target_sha = acquired['repositories']['AvelRen-ORIGINAL']['main']
    target = tree(target_repo, target_sha)
    by_blob = collections.defaultdict(list)
    for path, info in target.items():
        by_blob[info['blob']].append(path)
    provenance = collections.defaultdict(list)
    docs_text = {}
    for path, info in target.items():
        if path.startswith('docs/') and path.endswith(('.md', '.json')):
            data = git(target_repo, 'cat-file', 'blob', info['blob'])
            docs_text[path] = data.decode('utf-8', errors='replace')
            if path.endswith('PROVENANCE.json'):
                for item in json.loads(data).get('files', []):
                    if 'source' in item and 'destination' in item:
                        provenance[item['source']].append((path, item))
    target_current = tree(checkout, 'HEAD')
    for path, info in target_current.items():
        by_blob[info['blob']].append(path)
    blobs = {}

    def content(repo, oid):
        key = (str(repo), oid)
        if key not in blobs:
            blobs[key] = git(repo, 'cat-file', 'blob', oid)
        return blobs[key]

    def classify(repo, name, path, info, changed):
        candidates = []
        if name == 'AvelRen':
            if path.startswith('app/'):
                candidates.append('services/backend/' + path[4:])
            if path.startswith('android/'):
                candidates.append('apps/' + path)
            if path.startswith('deploy/'):
                candidates.append('ops/' + path[7:])
        candidates += [x[1]['destination'] for x in provenance.get(path, [])]
        candidates += [path, 'docs/legacy/AvelRen-ops/' + Path(path).name]
        candidate = next((p for p in candidates if p in target_current), None)
        if re.search(r'(^|/)(\.env|.*\.(jks|keystore|kdbx)|google-services\.json)$', path):
            return 'blocked-sensitive', None, 'Чутливий тип файла; потрібне окреме рішення без публікації вмісту'
        exact = [p for p in by_blob.get(info['blob'], [])
                 if target_current.get(p, target.get(p, {})).get('mode') == info['mode']]
        if exact:
            return 'already-integrated', sorted(set(exact))[0], 'Точний Git blob і mode звіряються з ціллю; це не production-приймання'
        if candidate and path.endswith('.py') and info['mode'] == target_current[candidate]['mode']:
            old = ast_without_docstrings(content(repo, info['blob']))
            new = ast_without_docstrings(content(checkout, target_current[candidate]['blob']))
            if old is not None and old == new:
                return 'already-integrated', candidate, 'AST еквівалентний без docstrings; runtime/dependencies потребують свого приймання'
        for manifest, entry in provenance.get(path, []):
            revision = entry.get('revision')
            if revision and candidate == entry['destination'] and candidate in target_current:
                data = content(repo, info['blob'])
                current = content(checkout, target_current[candidate]['blob'])
                if hashlib.sha256(data).hexdigest() == entry['sha256'] and hashlib.sha256(current).hexdigest() == revision['sha256'] and revision['notes'] in target:
                    return 'superseded-with-evidence', candidate, f'Перевірені source/current SHA-256 та revision: {manifest}; {revision["notes"]}'
        if changed:
            return 'historical-preserve', candidate, 'Унікальний стан іншого ref збережено й відновлено в локальному bundle; функціональне схвалення не встановлено'
        return 'needs-port', candidate, 'Відсутній доведений еквівалент; предметна звірка/рішення в TASK-02, старий код не замінює ціль'

    files = []
    external = {}
    for name in ['AvelRen', 'AvelRen-ops']:
        repo = root / f'{name}.git'
        details = acquired['repositories'][name]
        main_tree = tree(repo, details['main'])
        for path, info in main_tree.items():
            cat, dest, reason = classify(repo, name, path, info, False)
            files.append({'repository': f'ikstv/{name}', 'ref': 'refs/heads/main',
                          'commit': details['main'], 'path': path, **info,
                          'category': cat, 'target_path': dest, 'reason': reason})
        grouped = collections.defaultdict(list)
        for ref, oid in details['refs'].items():
            if ref != 'refs/heads/main':
                grouped[oid].append(ref)
        for oid, refs in grouped.items():
            tip = tree(repo, oid)
            for path, info in tip.items():
                if main_tree.get(path) == info:
                    continue
                cat, dest, reason = classify(repo, name, path, info, True)
                files.append({'repository': f'ikstv/{name}', 'refs': sorted(refs),
                              'commit': oid, 'path': path, **info, 'category': cat,
                              'target_path': dest, 'reason': reason})
            for path in main_tree.keys() - tip.keys():
                files.append({'repository': f'ikstv/{name}', 'refs': sorted(refs),
                              'commit': oid, 'path': path, 'blob': main_tree[path]['blob'],
                              'event': 'deleted-in-ref', 'blob_ref': 'refs/heads/main',
                              'category': 'historical-preserve', 'target_path': None,
                              'reason': 'Видалення відносно main; попередній blob збережений у bundle'})
        raw = git(repo, 'log', '--all', '--raw', '--format=', '--no-renames')
        submodule = bool(re.search(rb'(?m)^:(?:160000 [0-9]{6}|[0-9]{6} 160000) ', raw))
        objects = git(repo, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname) %(objecttype) %(objectsize)')
        small = [x.split()[0] for x in objects.splitlines() if x.split()[1] == b'blob' and int(x.split()[2]) <= 4096]
        batch = git(repo, 'cat-file', '--batch', data=b'\n'.join(small) + b'\n')
        offset = 0
        lfs = 0
        for _ in small:
            end = batch.index(b'\n', offset)
            size = int(batch[offset:end].split()[-1])
            data = batch[end + 1:end + 1 + size]
            lfs += data.splitlines()[:1] == [b'version https://git-lfs.github.com/spec/v1']
            offset = end + size + 2
        external[name] = {'historical_gitlinks': submodule, 'lfs_pointers': lfs,
                          'all_small_blobs_checked': len(small)}
    # Одна унікальна зміна path/blob; усі ref/commit-входження зберігаються.
    tip_records = {}
    unique = []
    for record in files:
        if 'refs' not in record:
            unique.append(record)
            continue
        key = (record['repository'], record['path'], record['blob'], record.get('mode'), record.get('event'))
        occurrence = {'commit': record.pop('commit'), 'refs': record.pop('refs')}
        if key not in tip_records:
            record['occurrences'] = []
            tip_records[key] = record
            unique.append(record)
        tip_records[key]['occurrences'].append(occurrence)
    files = unique
    (output / 'files.json').write_text(json.dumps(files, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    metadata = {}
    for name in ['AvelRen', 'AvelRen-ops', 'AvelRen-ORIGINAL']:
        raw = json.loads((root / 'github-metadata' / f'{name}.json').read_text(encoding='utf-8'))
        cols = raw['collections']
        issues = cols['issues'].get('items', [])
        pulls = {p['number']: p for p in cols['pulls'].get('items', [])}
        records = []
        for item in issues:
            url = item['html_url']
            evidence = sorted(p for p, text in docs_text.items() if url in text)
            pr = pulls.get(item['number'])
            records.append({'number': item['number'], 'kind': 'PR' if pr else 'issue',
                            'state': item['state'], 'url': url, 'comments_expected': item['comments'],
                            'body_sha256': hashlib.sha256((item.get('body') or '').encode()).hexdigest(),
                            'target_references': evidence, 'transfer_status': 'reference-only; native-object-not-transferred',
                            **({'head': pr['head']['sha'], 'base': pr['base']['sha'], 'merged': pr['merged_at'] is not None} if pr else {})})
        discussions = []
        for kind in ['issue_comments', 'review_comments']:
            for item in cols[kind].get('items', []):
                discussions.append({'kind': kind, 'id': item['id'], 'url': item['html_url'],
                                    'body_sha256': hashlib.sha256((item.get('body') or '').encode()).hexdigest(),
                                    'status': 'linked-not-transferred'})
        for number, reviews in raw['reviews'].items():
            for item in reviews.get('items', []):
                discussions.append({'kind': 'review', 'pr': int(number), 'id': item['id'],
                                    'url': item['html_url'], 'state': item['state'],
                                    'body_sha256': hashlib.sha256((item.get('body') or '').encode()).hexdigest(),
                                    'status': 'linked-not-transferred'})
        releases = []
        for release in cols['releases'].get('items', []):
            assets = raw['release_assets'].get(str(release['id']), {})
            sensitive = 'SECURE' in release['name'].upper() or 'BACKUP' in release['name'].upper()
            releases.append({'id': release['id'], 'tag': release['tag_name'], 'url': release['html_url'],
                             'draft': release['draft'], 'published_at': release['published_at'],
                             'asset_listing_status': assets['status'],
                             'assets': [{'id': x['id'], 'name': x['name'], 'bytes': x['size'],
                                         'digest': x.get('digest'), 'url': x['browser_download_url'],
                                         'status': 'blocked-sensitive' if sensitive else 'metadata-only-not-downloaded'}
                                        for x in assets.get('items', [])]})
        fetched_comments = collections.Counter(
            int(x['issue_url'].rsplit('/', 1)[-1]) for x in cols['issue_comments'].get('items', [])
        )
        comment_mismatches = [x['number'] for x in issues
                              if fetched_comments[x['number']] != x['comments']]
        metadata[name] = {'objects': records, 'discussions': discussions, 'releases': releases,
                          'workflows': [{k: x.get(k) for k in ['id', 'name', 'path', 'state', 'html_url']}
                                        for x in cols['workflows'].get('items', [])],
                          'secret_names_only': [x['name'] for x in cols['secrets_metadata'].get('items', [])],
                          'variable_names_only': [x['name'] for x in cols['variables_metadata'].get('items', [])],
                          'environment_names_only': [x['name'] for x in cols['environments'].get('items', [])],
                          'main_protection_required_checks': cols['branch_protection'].get('data', {}).get('required_status_checks'),
                          'collections': {k: {'status': v['status'], 'pages': v.get('pages'),
                                              'items': len(v.get('items', [])),
                                              'expected_total': v.get('expected_total'),
                                              'http_status': v.get('http_status')} for k,v in cols.items()},
                          'review_requests': len(raw['reviews']),
                          'review_failures': sum(v['status'] != 'complete-accessible-pages' for v in raw['reviews'].values()),
                          'issue_comment_count_mismatches': comment_mismatches,
                          'settings_transfer': 'not-performed; metadata-only',
                          'webhooks_and_environment_credentials': 'not-fetched; separate permission/metadata minimization required'}
    (output / 'github-objects.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    summary = {'schema_version': 1, 'acquired_at_utc': acquired['acquired_at_utc'],
               'target_base': target_sha,
               'repositories': {name: {**details, 'refs': [{'ref': ref, 'git_object': oid}
                                  for ref, oid in details['refs'].items()]}
                                for name, details in acquired['repositories'].items()},
               'external_objects': external, 'secret_scan': scanner,
               'file_records': len(files), 'categories': dict(collections.Counter(x['category'] for x in files)),
               'coverage': 'main files and every distinct ref-tip delta vs source main; older intermediate commits preserved by bundles, not functionally accepted',
               'git_hub_metadata': 'separate paginated export; never part of Git bundle',
               'local_uncommitted_changes': 'not collected from other PCs or server; not authorized in TASK-01'}
    (output / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'records': len(files), 'categories': summary['categories'], 'external': external}, ensure_ascii=False))


if __name__ == '__main__':
    main()
