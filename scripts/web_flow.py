"""Durable Edge review journal. UI is driven only by authorized CUA browser tools."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import os
from jsonschema import Draft202012Validator

import workflow as wf
from contextlib import contextmanager
from functools import wraps


@contextmanager
def journal_lock(root):
    """Kernel lock releases on process exit; lock file persistence is harmless."""
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    path = root.parent / ('.' + root.name + '.journal.lock')
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('journal busy: another process owns this run; retry after it exits') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def serialized(function):
    @wraps(function)
    def run(root, *args, **kwargs):
        with journal_lock(root):
            return function(root, *args, **kwargs)
    return run


def immutable_bytes(path, data):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('existing committed artifact differs: ' + path.name)
        return
    handle, temporary = tempfile.mkstemp(prefix='.commit-', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)  # Mutating callers hold the run lock.
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()



def now():
    return datetime.now(timezone.utc).isoformat()


def review_budget(state):
    value = state.get('max_review_rounds', 3)
    if type(value) is not int or value < 1:
        raise ValueError('review budget must be a positive integer')
    return value


@serialized
def set_budget(root, max_rounds, reason):
    """Record an explicitly user-authorized limit change, never reset history."""
    state = read_state(root)
    if state.get('terminal') or any(item['status'] in {'QUEUED', 'SENDING', 'SEND_UNKNOWN'} for item in state['requests']):
        raise ValueError('resolve the active request first; budget cannot release an unknown send')
    if type(max_rounds) is not int or max_rounds < max(1, state['rounds']) or not reason.strip():
        raise ValueError('budget needs a positive limit >= consumed rounds and an explicit authorization reason')
    previous = review_budget(state)
    state.setdefault('review_budget_changes', []).append({'at': now(), 'previous': previous, 'new': max_rounds, 'reason': reason})
    state['max_review_rounds'] = max_rounds
    save_state(root, state)
    return {'status': 'BUDGET_UPDATED', 'max_review_rounds': max_rounds, 'consumed_rounds': state['rounds']}


def save_state(root, state):
    # Same-directory atomic replacement keeps a crash from leaving partial JSON.
    handle, temp = tempfile.mkstemp(prefix='.state-', dir=root)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, root / 'web-state.json')
    finally:
        if Path(temp).exists():
            Path(temp).unlink()


def read_state(root):
    state = wf.load(root / 'web-state.json')
    if wf.sha((root / 'question.txt').read_bytes()) != state['question_sha256']:
        raise ValueError('frozen question changed')
    if wf.sha((root / 'codex-baseline.json').read_bytes()) != state['codex_baseline_sha256']:
        raise ValueError('frozen Codex baseline changed')
    for item in state['requests']:
        if not re.fullmatch(r'[0-9]{2,}-[BCD]', item['directory']):
            raise ValueError('unsafe request directory')
        directory = root / item['directory']
        if not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError('request directory escapes run')
        if item.get('browser_request_sha256') and wf.sha((directory / 'browser-request.json').read_bytes()) != item['browser_request_sha256']:
            raise ValueError('frozen browser request changed')
        if wf.sha((directory / 'prompt.txt').read_bytes()) != item['request_sha256']:
            raise ValueError('queued prompt changed')
        if wf.sha((directory / 'plan.json').read_bytes()) != item['plan_sha256']:
            raise ValueError('queued plan changed')
        if item['status'] == 'ACCEPTED' and wf.sha((directory / 'response.json').read_bytes()) != item['response_sha256']:
            raise ValueError('accepted response changed')
    return state


@serialized
def init(root, question_path, codex_path):
    plan = wf.validate(wf.load(codex_path), 'plan')
    question_bytes = Path(question_path).read_bytes()
    if wf.sha(question_bytes) != plan['question_sha256']:
        raise ValueError('question does not match baseline')
    if (root / 'web-state.json').exists():
        raise ValueError('run already initialized; use status to resume it')
    root.mkdir(parents=True, exist_ok=True)
    if any(path.name not in {'question.txt', 'codex-baseline.json'} and not path.name.startswith(('.state-', '.commit-')) for path in root.iterdir()):
        raise ValueError('unrecognized partial initialization; preserve artifacts and use a new run directory')
    immutable_bytes(root / 'question.txt', question_bytes)
    immutable_bytes(root / 'codex-baseline.json', Path(codex_path).read_bytes())
    state = {'protocol': wf.PROTOCOL, 'task_id': plan['task_id'],
             'question_sha256': plan['question_sha256'],
             'codex_baseline_sha256': wf.sha(Path(codex_path).read_bytes()),
             'requests': [], 'consecutive_failures': 0, 'rounds': 0,
             'stage': 'QUESTION_FROZEN', 'created_at': now()}
    save_state(root, state)
    return state


def evidence_for_prompt(paths, plan_hash, task_id):
    result = []
    for path in paths:
        check = wf.validate(wf.load(path), 'check')
        if check['plan_sha256'] != plan_hash or check['task_id'] != task_id:
            raise ValueError('evidence task/plan mismatch')
        artifact = wf.artifact_for(check, path)
        raw = wf.load(artifact)
        if len(json.dumps(raw, ensure_ascii=False)) > 131072:
            raise ValueError('evidence too large; supply a reviewed concise log with provenance, never silently truncate evidence')
        # Do not transmit unrelated local argv/cwd. The agent still checks sensitive content.
        if check['method'] == 'command':
            raw = {key: raw.get(key) for key in ['exit_code', 'timed_out', 'stdout', 'stderr']}
        safe_check = {key: check[key] for key in ['id', 'task_id', 'plan_sha256', 'assumption_ids',
                      'method', 'executed_at', 'expected', 'observed', 'status', 'artifact_sha256']}
        if 'sources' in check:
            safe_check['sources'] = check['sources']
        result.append({'check': safe_check, 'raw_output': raw})
    return result


@serialized
def queue(root, phase, plan_path=None, ledger_path=None, check_paths=()):
    state = read_state(root)
    if state.get('terminal'):
        raise ValueError('run was abandoned with an unresolved send; do not automatically resend')
    if any(item['status'] in {'QUEUED', 'SENDING', 'SEND_UNKNOWN'} for item in state['requests']):
        raise ValueError('resolve outstanding request; never blindly resend an uncertain send')
    accepted = [item for item in state['requests'] if item['status'] == 'ACCEPTED']
    phases = [item['stage_code'] for item in accepted]
    if phase == 'B' and any(x['status'] not in {'ABORTED_BEFORE_SEND', 'FAILED_TERMINAL'} for x in state['requests']):
        raise ValueError('baseline B must be first and unique')
    if phase == 'C' and phases != ['B']:
        raise ValueError('C requires accepted independent baseline B')
    if phase == 'D' and not (phases[:2] == ['B', 'C'] and all(x == 'D' for x in phases[2:])):
        raise ValueError('D requires B/C and a fresh context on every revision')
    if phase != 'B' and state['rounds'] >= review_budget(state):
        raise ValueError('review round budget exhausted')
    if phase == 'D' and (not ledger_path or not check_paths):
        raise ValueError('final review needs the full ledger and actual evidence')
    plan_path = Path(plan_path) if plan_path else root / 'codex-baseline.json'
    plan = wf.validate(wf.load(plan_path), 'plan')
    if plan['task_id'] != state['task_id'] or plan['question_sha256'] != state['question_sha256']:
        raise ValueError('new plan must preserve task and question')
    plan_hash = wf.sha(plan_path.read_bytes())
    index = len(state['requests']) + 1
    # A crash before state commit may leave an uncommitted request directory.
    # Preserve it and allocate a new never-used ID; no send intent existed.
    while any(root.glob(f'{index:02d}-*')):
        index += 1
    request_id = f"{state['task_id']}-{phase.lower()}-{index}"
    request_dir = root / f'{index:02d}-{phase}'
    request_dir.mkdir()
    (request_dir / 'plan.json').write_bytes(plan_path.read_bytes())
    round_number = 0 if phase == 'B' else state['rounds'] + 1
    kind = 'baseline' if phase == 'B' else 'review'
    header = {'task_id': state['task_id'], 'request_id': request_id,
              'question_sha256': state['question_sha256'], 'stage': phase}
    question = (root / 'question.txt').read_text(encoding='utf-8-sig')
    if phase == 'B':
        payload = {'original_question': question, 'output_schema': wf.schema_for('baseline')}
        instruction = '根据原始问题独立生成基线；这里没有另一模型的方案。只输出符合 Schema 的完整 JSON，version=gemini-baseline-v1。不虚构已完成的验证。'
    else:
        baseline_b = root / accepted[0]['directory'] / 'response.json'
        review_schema = wf.load(wf.ROOT / 'schemas/review.schema.json')
        current_ids = [entry['id'] for entry in plan['critical_assumptions']]
        checked = review_schema['properties']['critical_assumptions_checked']
        checked['items']['enum'] = current_ids
        checked.update({'uniqueItems': True, 'minItems': len(current_ids), 'maxItems': len(current_ids)})
        request_properties = review_schema['properties']['verification_requests']['items']['properties']
        request_properties['assumption_ids']['items']['enum'] = current_ids
        logs = evidence_for_prompt(check_paths, plan_hash, state['task_id'])
        if logs:
            request_properties['evidence_ids']['items']['enum'] = [entry['check']['id'] for entry in logs]
        header.update({'plan_sha256': plan_hash, 'round': round_number,
                       'phase': 'adversarial' if phase == 'C' else 'final'})
        payload = {'original_question': question, 'current_plan': plan,
                   'codex_independent_baseline': wf.load(root / 'codex-baseline.json'),
                   'gemini_independent_baseline': wf.load(baseline_b),
                   'prior_reviews': [wf.load(root / item['directory'] / 'response.json')
                                     for item in accepted if item['stage_code'] != 'B'],
                   'ledger': wf.load(ledger_path) if ledger_path else [],
                   'verification_logs': logs,
                   'output_schema': review_schema}
        instruction = ('优先证伪 Codex 方案，同时检查 Gemini 基线。不为反对而编造缺陷，不把模型一致当证据。'
                       '检查所有关键假设的证据，缺证据保持 OPEN；终审仅在条件满足时 APPROVED。'
                       '保留未解决的 B/V/D 编号，只返回符合 Schema 的完整 JSON，原样回传 header 标识，'
                       'complete=true 仅用于确已完成的完整输出，end_marker=END_REVIEW。')
        instruction += ('critical_assumptions_checked 只列当前 current_plan 的全部且仅有的假设编号，每个一次；'
                        '独立基线 CA 编号的讨论放入 divergences 正文。verification_requests 的 assumption_ids '
                        '仅引用当前计划编号，evidence_ids 仅引用本请求 verification_logs 中的证据编号，'
                        '不能把历史其他计划版本的证据编号当作当前已验证。')
    if phase != 'B' and plan_hash == state['codex_baseline_sha256']:
        payload['codex_independent_baseline'] = {'ref': 'current_plan', 'sha256': plan_hash}
    instruction = f'[TASK_ID:{state["task_id"]} REQUEST_ID:{request_id}] ' + instruction
    prompt = instruction + '\n' + json.dumps({'header': header, 'payload': payload}, ensure_ascii=False, separators=(',', ':')) + '\n'
    (request_dir / 'prompt.txt').write_text(prompt, encoding='utf-8', newline='\n')
    request = {'protocol': wf.PROTOCOL, **header, 'stage_code': phase, 'kind': kind, 'round': round_number,
               'plan_sha256': plan_hash, 'request_sha256': wf.sha(prompt.encode('utf-8')),
               'prompt': prompt, 'directory': request_dir.name, 'status': 'QUEUED'}
    wf.write_new(request_dir / 'browser-request.json', request)
    item = {key: value for key, value in request.items() if key != 'prompt'}
    item['browser_request_sha256'] = wf.sha((request_dir / 'browser-request.json').read_bytes())
    state['requests'].append(item)
    state['rounds'] = round_number if phase != 'B' else state['rounds']
    state['stage'] = phase + '_QUEUED'
    save_state(root, state)
    return request


def active(root):
    state = read_state(root)
    if not state['requests']:
        raise ValueError('no request')
    item = state['requests'][-1]
    directory = root / item['directory']
    return state, item, directory


@serialized
def attach(root, tab_id, source_url, model_observed, fresh_context_observed):
    state, item, _ = active(root)
    if item['status'] != 'QUEUED' or item.get('tab_id'):
        raise ValueError('attach requires an unbound queued request')
    if not (tab_id and model_observed and fresh_context_observed is True):
        raise ValueError('attach needs observed tab, model and empty context')
    if not re.fullmatch(r'https://gemini\.google\.com/app/?(?:\?[^#]*)?', source_url):
        raise ValueError('attach must identify a fresh Gemini page')
    if any(old.get('tab_id') == tab_id for old in state['requests'][:-1]):
        raise ValueError('cannot reuse an earlier phase tab')
    item.update({'tab_id': tab_id, 'initial_url': source_url,
                 'model_observed': model_observed, 'fresh_context_observed': True})
    save_state(root, state)
    return {'status': 'TAB_BOUND', 'request_id': item['request_id'], 'tab_id': tab_id}


@serialized
def mark_sending(root):
    state, item, _ = active(root)
    if item['status'] != 'QUEUED':
        raise ValueError('send already attempted or completed; do not resend')
    if not item.get('tab_id') or not item.get('fresh_context_observed'):
        raise ValueError('record the actual fresh browser tab before sending')
    item.update({'status': 'SENDING', 'send_intent_at': now()})
    state['stage'] = item['stage_code'] + '_SENDING'
    save_state(root, state)  # Must complete before the agent clicks Send.
    return {'status': 'SEND_INTENT_RECORDED', 'request_id': item['request_id']}


def json_text(raw):
    return wf.json_object_text(raw)


@serialized
def accept(root, capture_path):
    state, item, directory = active(root)
    if item['status'] not in {'SENDING', 'SEND_UNKNOWN'}:
        raise ValueError('capture requires a recorded send intent')
    capture = wf.load(capture_path)
    if capture.get('tab_id') != item.get('tab_id') or capture.get('model_observed') != item.get('model_observed'):
        raise ValueError('capture must match the tab/model bound before sending')
    for key in ['task_id', 'request_id', 'stage', 'request_sha256']:
        expected = item['stage_code'] if key == 'stage' else item[key]
        if capture.get(key) != expected:
            raise ValueError('capture request mismatch: ' + key)
    signal = capture.get('completion', {})
    if not (capture.get('fresh_context') is True and capture.get('prompt_echo_matches') is True
            and signal.get('stop_visible') is False and signal.get('copy_visible') is True
            and signal.get('stable_observations', 0) >= 2):
        raise ValueError('missing observed freshness/completion/prompt evidence')
    url = capture.get('source_url', '')
    if not re.fullmatch(r'https://gemini\.google\.com/app/[A-Za-z0-9_-]+(?:\?[^#]*)?', url):
        raise ValueError('capture must identify an actual Gemini conversation')
    for earlier in state['requests'][:-1]:
        if earlier.get('source_url') == url or earlier.get('tab_id') == capture.get('tab_id'):
            raise ValueError('B/C/D must use distinct tabs and conversations')
    if not capture.get('tab_id') or not capture.get('model_observed'):
        raise ValueError('missing observed tab or model label')
    raw = capture.get('raw_response')
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('empty response')
    if capture.get('raw_response_sha256') != wf.sha(raw.encode('utf-8')):
        raise ValueError('browser-to-file response transfer hash mismatch')
    attempt = len(list(directory.glob('capture-*.json'))) + 1
    wf.write_new(directory / f'capture-{attempt}.json', capture)
    parsed_path = directory / f'candidate-{attempt}.json'
    parsed_path.write_text(json_text(raw), encoding='utf-8', newline='\n')
    response = wf.validate(wf.load(parsed_path), item['kind'])  # strict duplicate-key/constant refusal
    queued_payload = json.loads((directory / 'prompt.txt').read_text(encoding='utf-8').split('\n', 1)[1])
    Draft202012Validator(queued_payload['payload']['output_schema']).validate(response)
    if response['task_id'] != state['task_id']:
        raise ValueError('response task mismatch')
    if item['kind'] == 'baseline':
        wf.ids(response['critical_assumptions'])
        if response['question_sha256'] != state['question_sha256']:
            raise ValueError('baseline question mismatch')
    else:
        if any(response[key] != item[key] for key in ['request_id', 'plan_sha256', 'round', 'phase']):
            raise ValueError('response review identity/version mismatch')
        if not response['complete']:
            raise ValueError('review incomplete')
    immutable_bytes(directory / 'response.json', parsed_path.read_bytes())
    if item['kind'] == 'review':
        receipt = {'protocol': wf.PROTOCOL, 'task_id': state['task_id'],
                   'request_id': item['request_id'], 'transport': 'web', 'source_ref': url,
                   'model_observed': capture['model_observed'], 'fresh_context': True,
                   'completion_observed': True,
                   'response_sha256': wf.sha((directory / 'response.json').read_bytes())}
        wf.validate(receipt, 'receipt')
        immutable_bytes(directory / 'receipt.json', (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    item.update({'status': 'ACCEPTED', 'source_url': url, 'tab_id': capture['tab_id'],
                 'response_sha256': wf.sha((directory / 'response.json').read_bytes())})
    state.update({'stage': item['stage_code'] + '_RECEIVED', 'consecutive_failures': 0})
    save_state(root, state)
    return {'status': 'ACCEPTED', 'request_id': item['request_id'], 'directory': str(directory)}


@serialized
def failure(root, category, reason):
    state = read_state(root)
    if category == 'send_unknown' and (not state['requests'] or state['requests'][-1]['status'] not in {'SENDING', 'SEND_UNKNOWN'}):
        raise ValueError('unknown-send recovery requires an actual durable send attempt')
    state['consecutive_failures'] += 1
    state.setdefault('failures', []).append({'at': now(), 'category': category, 'reason': reason})
    if category == 'send_unknown' and state['requests']:
        state['requests'][-1]['status'] = 'SEND_UNKNOWN'
    # Blocked policy/authentication must be restored, never bypassed or blindly retried.
    state['stage'] = ('AUTOMATION_RECOVERY_REQUIRED' if category in {'blocked', 'send_unknown'}
                      else 'MANUAL_FALLBACK_AVAILABLE' if state['consecutive_failures'] >= 3
                      else 'AUTOMATION_RETRY_AVAILABLE')
    save_state(root, state)
    return {'status': state['stage'], 'consecutive_failures': state['consecutive_failures']}


@serialized
def finish(root, check_paths, waiver_paths=(), source_root=None):
    state, item, directory = active(root)
    if item['stage_code'] != 'D' or item['status'] != 'ACCEPTED':
        raise ValueError('accepted final D required')
    result = wf.gate(directory / 'plan.json', directory / 'response.json',
                     directory / 'receipt.json', check_paths, root / 'question.txt', max_rounds=review_budget(state), waiver_paths=waiver_paths, source_root=source_root)
    immutable_bytes(directory / 'gate-result.json', (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    state['stage'] = result['status']
    save_state(root, state)
    return result


@serialized
def abort(root, reason):
    state, item, _ = active(root)
    if item['status'] != 'QUEUED' or item.get('send_intent_at') or not reason.strip():
        raise ValueError('only a never-attempted queued request can abort; uncertain sends remain observation-only')
    item.update(status='ABORTED_BEFORE_SEND', reason=reason, aborted_at=now())
    state['stage'] = 'ABORTED_BEFORE_SEND'
    save_state(root, state)
    return {'status': state['stage']}


@serialized
def abandon(root, reason, capture_path=None):
    """Archive an attempt. Retry only when completion was actually observed."""
    state, item, directory = active(root)
    if item['status'] not in {'SENDING', 'SEND_UNKNOWN'} or not reason.strip():
        raise ValueError('abandon needs an attempted request and an explicit reason')
    if capture_path is None:
        item['status'] = 'ABANDONED_UNRESOLVED'
        state['terminal'] = True
    else:
        capture = wf.load(capture_path)
        for key in ['task_id', 'request_id', 'request_sha256', 'tab_id', 'model_observed']:
            if capture.get(key) != item.get(key):
                raise ValueError('abandon capture binding mismatch')
        signal = capture.get('completion', {})
        if not (signal.get('stop_visible') is False and signal.get('copy_visible') is True
                and signal.get('stable_observations', 0) >= 2 and capture.get('prompt_echo_matches') is True
                and capture.get('fresh_context') is True
                and capture.get('raw_response_sha256') == wf.sha(capture.get('raw_response', '').encode('utf-8'))):
            raise ValueError('observed completed response required to release the attempt')
        url = capture.get('source_url', '')
        if not re.fullmatch(r'https://gemini\.google\.com/app/[A-Za-z0-9_-]+(?:\?[^#]*)?', url):
            raise ValueError('actual completed conversation URL required')
        wf.write_new(directory / 'abandoned-capture.json', capture)
        item.update(status='FAILED_TERMINAL', source_url=url)
    item.update(reason=reason, abandoned_at=now())
    state['consecutive_failures'] += 1
    state['stage'] = item['status']
    save_state(root, state)
    return {'status': state['stage'], 'retry_allowed': not state.get('terminal', False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'queue', 'attach', 'sending', 'accept', 'failure', 'finish', 'abort', 'abandon', 'budget', 'status'])
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--question')
    parser.add_argument('--plan')
    parser.add_argument('--phase', choices=['B', 'C', 'D'])
    parser.add_argument('--ledger')
    parser.add_argument('--check', action='append', default=[])
    parser.add_argument('--capture')
    parser.add_argument('--waiver', action='append', default=[])
    parser.add_argument('--source-root')
    parser.add_argument('--tab-id')
    parser.add_argument('--source-url')
    parser.add_argument('--model-observed')
    parser.add_argument('--fresh-context-observed', action='store_true')
    parser.add_argument('--category', choices=['recoverable', 'blocked', 'send_unknown'])
    parser.add_argument('--reason', default='')
    parser.add_argument('--max-rounds', type=int)
    args = parser.parse_args()
    root = Path(args.run_dir).resolve()
    try:
        if args.action == 'init':
            if not args.question or not args.plan:
                raise ValueError('init needs question and frozen Codex plan')
            result = init(root, args.question, args.plan)
        elif args.action == 'queue':
            if not args.phase:
                raise ValueError('queue needs phase')
            result = queue(root, args.phase, args.plan, args.ledger, args.check)
        elif args.action == 'attach':
            result = attach(root, args.tab_id, args.source_url or '', args.model_observed,
                            args.fresh_context_observed)
        elif args.action == 'sending':
            result = mark_sending(root)
        elif args.action == 'accept':
            result = accept(root, args.capture)
        elif args.action == 'failure':
            if not args.category:
                raise ValueError('failure needs category')
            result = failure(root, args.category, args.reason)
        elif args.action == 'finish':
            result = finish(root, args.check, args.waiver, args.source_root)
        elif args.action == 'abort':
            result = abort(root, args.reason)
        elif args.action == 'abandon':
            result = abandon(root, args.reason, args.capture)
        elif args.action == 'budget':
            result = set_budget(root, args.max_rounds, args.reason)
        else:
            result = read_state(root)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
