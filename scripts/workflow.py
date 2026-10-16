"""Local review protocol helpers. No implicit network or execution of model text."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib import error, request

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 'gemini-review/2'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(text,
                      object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f'invalid JSON constant: {value}')))


def load(path):
    return strict_json(Path(path).read_text(encoding='utf-8-sig'))


def json_object_text(raw):
    """Strip framing, never repair JSON or select one of conflicting objects."""
    chunks, start, stack, quoted, escaped = [], None, [], False, False
    for index, char in enumerate(raw.strip('\ufeff')):
        if start is None:
            if char in '{[':
                start, stack = index, [char]
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or (stack.pop(), char) not in {('{', '}'), ('[', ']')}:
                raise ValueError('mismatched JSON delimiters')
            if not stack:
                chunks.append(raw.strip('\ufeff')[start:index + 1])
                start = None
    if start is not None or len(chunks) != 1:
        raise ValueError('expected exactly one complete JSON object')
    if not isinstance(strict_json(chunks[0]), dict):
        raise ValueError('JSON object required')
    return chunks[0]


def schema_for(kind):
    # A maintained local alias; never fetch a remote $ref.
    return load(ROOT / 'schemas' / ('plan.schema.json' if kind == 'baseline' else f'{kind}.schema.json'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write('\n')


def validate(value, kind):
    schema = schema_for(kind)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return value


def ids(items):
    values = [item['id'] for item in items]
    if len(values) != len(set(values)):
        raise ValueError('duplicate IDs')
    return set(values)


def artifact_for(record, record_path):
    parent = Path(record_path).resolve().parent
    artifact = (parent / record['artifact']).resolve()
    if not artifact.is_relative_to(parent):
        raise ValueError('artifact must remain inside its log directory')
    if not artifact.is_file() or artifact.stat().st_size == 0:
        raise ValueError('artifact missing/empty')
    if sha(artifact.read_bytes()) != record['artifact_sha256']:
        raise ValueError('artifact hash mismatch')
    return artifact


def check_time(value):
    when = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if when > datetime.now(timezone.utc):
        raise ValueError('record timestamp is in the future')


def verify_manifest(root, manifest):
    if root is None:
        raise ValueError('source-root required for a source-bound plan')
    root = Path(root).resolve()
    seen = set()
    for item in manifest:
        name = item['path']
        relative = Path(name)
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root) or name in seen:
            raise ValueError('unsafe or duplicate source path')
        seen.add(name)
        if not target.is_file() or sha(target.read_bytes()) != item['sha256']:
            raise ValueError('source manifest mismatch: ' + name)


def gate(plan_path, review_path, receipt_path, check_paths, question_path, max_rounds=3,
         waiver_paths=(), source_root=None):
    plan = validate(load(plan_path), 'plan')
    review = validate(load(review_path), 'review')
    receipt = validate(load(receipt_path), 'receipt')
    plan_hash = sha(Path(plan_path).read_bytes())
    required = ids(plan['critical_assumptions'])
    if plan.get('source_manifest'):
        verify_manifest(source_root, plan['source_manifest'])
    if sha(Path(question_path).read_bytes()) != plan['question_sha256']:
        raise ValueError('question changed since plan was created')
    if review['task_id'] != plan['task_id'] or receipt['task_id'] != plan['task_id']:
        raise ValueError('task identity mismatch')
    if review['plan_sha256'] != plan_hash:
        raise ValueError('review belongs to a different plan version')
    if (receipt['request_id'] != review['request_id'] or
            receipt['response_sha256'] != sha(Path(review_path).read_bytes())):
        raise ValueError('receipt does not match review bytes/request')
    if not receipt['completion_observed'] or not review['complete']:
        raise ValueError('incomplete response')
    if review['phase'] != 'final' or review['verdict'] == 'REJECTED':
        raise ValueError('a final APPROVED review is required')
    if not receipt['fresh_context'] or not 1 <= review['round'] <= max_rounds:
        raise ValueError('fresh final context and an in-budget round are required')
    if review['blockers']:
        raise ValueError('unresolved blockers')
    checked = review['critical_assumptions_checked']
    if len(checked) != len(set(checked)) or set(checked) != required:
        raise ValueError('review must cover every critical assumption exactly once')
    ids(review['divergences'])
    ids(review['verification_requests'])
    waived, waiver_coverage, scopes = set(), {}, set()
    for path in waiver_paths:
        waiver = validate(load(path), 'waiver')
        if plan.get('task_kind', 'implementation') not in {'research', 'planning'}:
            raise ValueError('unverified waivers apply only to research/planning tasks')
        if waiver['task_id'] != plan['task_id'] or waiver['plan_sha256'] != plan_hash:
            raise ValueError('waiver belongs to a different task/plan')
        targets = set(waiver['assumption_ids'])
        if not targets <= required or waiver['id'] in waiver_coverage:
            raise ValueError('unknown waived assumption or duplicate waiver ID')
        signature = waiver['approval_text']
        if (plan_hash not in signature or waiver['signed_by'] not in signature or
                not all(item in signature for item in targets) or
                not any(term in signature for term in ['同意放行', 'ACCEPT_UNVERIFIED'])):
            raise ValueError('explicit user signature must name signer, plan hash and assumptions')
        if signature not in artifact_for(waiver, path).read_text(encoding='utf-8-sig'):
            raise ValueError('signature does not match the recorded user approval')
        check_time(waiver['signed_at'])
        waived.update(targets)
        scopes.add(waiver['allowed_scope'])
        waiver_coverage[waiver['id']] = targets
    if review['verdict'] != 'APPROVED' and not waived:
        raise ValueError('a final APPROVED review is required without signed waivers')
    if waived and review['verdict'] != 'CONDITIONAL_PASS':
        raise ValueError('waived assumptions must retain CONDITIONAL_PASS, not verified APPROVED')
    coverage, evidence_ids, evidence_coverage = set(), set(), {}
    for path in check_paths:
        check = validate(load(path), 'check')
        if check['id'] in evidence_ids:
            raise ValueError('duplicate verification ID')
        evidence_ids.add(check['id'])
        if check['task_id'] != plan['task_id'] or check['plan_sha256'] != plan_hash:
            raise ValueError('verification belongs to a different task/plan')
        targets = set(check['assumption_ids'])
        if not targets <= required:
            raise ValueError('verification references unknown assumption')
        artifact = artifact_for(check, path)
        if check['status'] != 'PASS':
            raise ValueError('failed or unknown verification remains')
        if check['method'] == 'command':
            execution = load(artifact)
            if execution.get('exit_code') != 0 or execution.get('timed_out') is not False:
                raise ValueError('command artifact does not show a completed successful test')
        if check['method'] in {'web', 'literature'}:
            sources = check.get('sources', [])
            minimum = 2 if check['method'] == 'literature' else 1
            if len(sources) < minimum or len({source['url'] for source in sources}) != len(sources):
                raise ValueError('literature verification requires two distinct cited sources' if minimum == 2 else 'web verification requires a cited source')
            for source in sources:
                if not source['url'].startswith(('https://', 'http://')):
                    raise ValueError('literature source must be an actually accessed web reference')
                check_time(source['accessed_at'])
        check_time(check['executed_at'])
        coverage.update(targets)
        evidence_coverage[check['id']] = targets
    if not required <= coverage | waived:
        raise ValueError('missing PASS evidence for critical assumptions')
    for item in review['verification_requests']:
        if not set(item['assumption_ids']) <= required:
            raise ValueError('request references unknown assumption')
        if item['status'] == 'USER_ACCEPTED_UNVERIFIED':
            if not item['evidence_ids'] or not set(item['evidence_ids']) <= set(waiver_coverage):
                raise ValueError('unverified request requires specific signed waiver IDs')
            covered = set().union(*(waiver_coverage[x] for x in item['evidence_ids']))
            if not set(item['assumption_ids']) <= covered:
                raise ValueError('waiver does not cover the unverified request')
            continue
        if (item['status'] != 'SATISFIED' or not item['evidence_ids'] or
                not set(item['evidence_ids']) <= evidence_ids):
            raise ValueError('verification request is not backed by supplied logs')
        covered = set().union(*(evidence_coverage[x] for x in item['evidence_ids']))
        if not set(item['assumption_ids']) <= covered:
            raise ValueError('request cites logs for different assumptions')
    return {'status': 'READY_WITH_WAIVER' if waived else 'READY', 'plan_sha256': plan_hash,
            'transport': receipt['transport'], 'checks': len(check_paths),
            'verified_assumptions': sorted(coverage), 'unverified_assumptions': sorted(waived),
            'allowed_scopes': sorted(scopes),
            'scope': 'local preflight only; not an execution authorization'}


def record_check(args):
    plan = validate(load(args.plan), 'plan')
    if not set(args.assumption) <= ids(plan['critical_assumptions']):
        raise ValueError('unknown assumption')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        raise ValueError('an explicit assertion/test command is required')
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = output.with_suffix('.execution.json')
    if output.exists() or artifact.exists():
        raise ValueError('use new output paths; existing records are never overwritten')
    started = datetime.now(timezone.utc).isoformat()
    timed_out = False
    try:
        result = subprocess.run(command, cwd=args.cwd, capture_output=True,
                                text=True, encoding='utf-8', errors='replace',
                                timeout=args.timeout, shell=False)
        exit_code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out, exit_code = True, None
        stdout = (exc.stdout or b'').decode('utf-8', errors='replace') if isinstance(
            exc.stdout, bytes) else (exc.stdout or '')
        stderr = 'verification timed out'
    write_new(artifact, {'started_at': started, 'cwd': str(Path(args.cwd).resolve()),
                         'argv': command, 'exit_code': exit_code, 'timed_out': timed_out,
                         'stdout': stdout, 'stderr': stderr})
    record = {'protocol': PROTOCOL, 'task_id': plan['task_id'],
              'plan_sha256': sha(Path(args.plan).read_bytes()), 'id': args.id,
              'assumption_ids': args.assumption, 'method': 'command',
              'executed_at': started, 'target': json.dumps(command, ensure_ascii=False),
              'expected': args.expected,
              'observed': f'exit_code={exit_code}; assertion output in artifact',
              'status': 'PASS' if exit_code == 0 and not timed_out else 'FAIL',
              'artifact': artifact.name, 'artifact_sha256': sha(artifact.read_bytes())}
    validate(record, 'check')
    write_new(output, record)
    return record


def parse_api_response(raw):
    if raw.get('status') != 'completed':
        raise ValueError('Gemini interaction is not completed')
    chunks = [content.get('text', '') for step in raw.get('steps', [])
              if step.get('type') == 'model_output'
              for content in step.get('content', []) if content.get('type') == 'text']
    if len(chunks) != 1:
        raise ValueError('expected one complete JSON text output; preserve raw response')
    return chunks[0]


def api_schema(value):
    if isinstance(value, dict):
        return {key: api_schema(item) for key, item in value.items()
                if key not in {'$schema', 'pattern', 'minLength'}}
    if isinstance(value, list):
        return [api_schema(item) for item in value]
    return value


def load_api_key():
    # User-level lookup supports keys configured after this Codex process started.
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
                value, _ = winreg.QueryValueEx(registry, 'GEMINI_API_KEY')
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:
            pass
    return os.environ.get('GEMINI_API_KEY', '').strip() or None


def api_call(args):
    preferences = load(ROOT / 'preferences.json') if (ROOT / 'preferences.json').is_file() else {}
    if args.send and not preferences.get('api_enabled', False):
        raise ValueError('API disabled by user preference; use manual/web transport')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', args.model):
        raise ValueError('invalid model ID')
    # Use only the documented API schema subset; retain full local validation.
    schema = api_schema(schema_for(args.kind))
    payload = {'model': args.model, 'input': Path(args.prompt).read_text(encoding='utf-8'),
               'system_instruction': Path(args.system).read_text(encoding='utf-8'),
               'store': False, 'stream': False,
               'generation_config': {'max_output_tokens': args.max_output_tokens},
               'response_format': {'type': 'text', 'mime_type': 'application/json',
                                   'schema': schema}}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=False)
    write_new(out / 'request.json', payload)
    if not args.send:
        return {'status': 'DRY_RUN', 'network_calls': 0}
    key = load_api_key()
    if not key:
        raise ValueError('GEMINI_API_KEY not configured; no request sent')
    req = request.Request('https://generativelanguage.googleapis.com/v1beta/interactions',
                          data=json.dumps(payload).encode('utf-8'),
                          headers={'Content-Type': 'application/json',
                                   'x-goog-api-key': key}, method='POST')
    # No automatic retries: a timeout may still have produced a billable response.
    try:
        with request.urlopen(req, timeout=args.timeout) as response:
            raw = json.load(response)
    except error.HTTPError as exc:
        write_new(out / 'failure.json', {'status': 'HTTP_ERROR', 'code': exc.code})
        raise ValueError(f'Gemini HTTP {exc.code}; no automatic retry') from None
    except (error.URLError, TimeoutError):
        write_new(out / 'failure.json', {'status': 'TRANSPORT_UNKNOWN'})
        raise ValueError('transport failed; completion unknown; no automatic retry') from None
    write_new(out / 'raw-response.json', raw)
    text_output = parse_api_response(raw)
    text_path = out / 'response.json'
    with text_path.open('x', encoding='utf-8', newline='\n') as file:
        file.write(text_output)
    report = validate(load(text_path), args.kind)
    if args.kind == 'review':
        receipt = {'protocol': PROTOCOL, 'task_id': report['task_id'],
                   'request_id': report['request_id'], 'transport': 'api',
                   'source_ref': str(raw.get('id', 'unknown')),
                   'model_observed': raw.get('model', args.model),
                   'fresh_context': True,
                   'completion_observed': True,
                   'response_sha256': sha(text_path.read_bytes())}
        write_new(out / 'receipt.json', validate(receipt, 'receipt'))
    return {'status': 'RECEIVED_AND_SCHEMA_VALIDATED', 'kind': args.kind}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    hash_parser = commands.add_parser('hash')
    hash_parser.add_argument('file')
    check_parser = commands.add_parser('check')
    for flag in ['plan', 'id', 'expected', 'out', 'cwd']:
        check_parser.add_argument('--' + flag, required=True)
    check_parser.add_argument('--assumption', action='append', required=True)
    check_parser.add_argument('--timeout', type=int, default=60)
    check_parser.add_argument('command', nargs=argparse.REMAINDER)
    gate_parser = commands.add_parser('gate')
    for flag in ['plan', 'review', 'receipt', 'question']:
        gate_parser.add_argument('--' + flag, required=True)
    gate_parser.add_argument('--check', action='append', default=[])
    gate_parser.add_argument('--max-rounds', type=int, default=3)
    gate_parser.add_argument('--waiver', action='append', default=[])
    gate_parser.add_argument('--source-root')
    commands.add_parser('key-status')
    api_parser = commands.add_parser('api')
    for flag in ['model', 'prompt', 'system', 'out-dir']:
        api_parser.add_argument('--' + flag, required=True)
    api_parser.add_argument('--kind', choices=['baseline', 'review'], required=True)
    api_parser.add_argument('--send', action='store_true')
    api_parser.add_argument('--timeout', type=int, default=60)
    api_parser.add_argument('--max-output-tokens', type=int, default=4096)
    args = parser.parse_args()
    try:
        if args.action == 'hash':
            result = {'sha256': sha(Path(args.file).read_bytes())}
        elif args.action == 'key-status':
            enabled = load(ROOT / 'preferences.json').get('api_enabled', False)
            result = {'configured': bool(load_api_key()) if enabled else None,
                      'api_enabled': enabled, 'key_value': 'never displayed'}
        elif args.action == 'gate':
            result = gate(args.plan, args.review, args.receipt, args.check, args.question,
                          args.max_rounds, args.waiver, args.source_root)
        elif args.action == 'check':
            result = record_check(args)
        else:
            result = api_call(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('status') != 'FAIL' else 2
    except Exception as exc:
        # Do not echo arbitrary API bodies or exception strings that may contain secrets.
        message = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else type(exc).__name__
        print(json.dumps({'status': 'BLOCKED', 'reason': message}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
