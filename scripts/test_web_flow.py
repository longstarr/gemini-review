"""Synthetic OFFLINE fixtures only: no real Gemini, browser, or network calls."""
from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

import workflow as wf
import web_flow as web


class WebFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.question = self.base / 'q.txt'
        self.question.write_text('SYNTHETIC QUESTION 中文', encoding='utf-8')
        self.plan = {'protocol': wf.PROTOCOL, 'task_id': 'synthetic-offline-web',
                     'question_sha256': wf.sha(self.question.read_bytes()), 'version': 'fixture-v1',
                     'task_kind': 'planning', 'proposal': 'CODEX_ONLY_SECRET_SENTINEL',
                     'critical_assumptions': [{'id': 'A1', 'claim': '2+2=4',
                                               'verification_requirement': 'assert integer addition'}],
                     'failure_modes': ['SYNTHETIC FIXTURE, not a real review']}
        self.plan_path = self.base / 'plan.json'
        wf.write_new(self.plan_path, self.plan)
        self.root = self.base / 'run'
        web.init(self.root, self.question, self.plan_path)

    def response(self, request):
        if request['kind'] == 'baseline':
            return {**self.plan, 'version': 'synthetic-gemini-baseline', 'proposal': 'SYNTHETIC BASELINE'}
        return {'protocol': wf.PROTOCOL, 'task_id': self.plan['task_id'],
                'request_id': request['request_id'], 'plan_sha256': request['plan_sha256'],
                'round': request['round'], 'phase': request['phase'], 'complete': True,
                'blockers': [], 'verification_requests': [], 'divergences': [],
                'critical_assumptions_checked': ['A1'], 'verdict': 'APPROVED', 'end_marker': 'END_REVIEW'}

    def capture(self, request, response=None):
        raw = json.dumps(response or self.response(request), ensure_ascii=False)
        return {'protocol': wf.PROTOCOL, 'task_id': request['task_id'], 'request_id': request['request_id'],
                'stage': request['stage_code'], 'request_sha256': request['request_sha256'],
                'tab_id': 'synthetic-tab-' + request['request_id'],
                'source_url': 'https://gemini.google.com/app/synthetic-' + request['request_id'],
                'model_observed': 'SYNTHETIC OFFLINE FIXTURE, NOT GEMINI',
                'fresh_context': True, 'prompt_echo_matches': True,
                'completion': {'stop_visible': False, 'copy_visible': True, 'stable_observations': 2},
                'raw_response': raw, 'raw_response_sha256': wf.sha(raw.encode('utf-8'))}

    def accept(self, request, capture=None):
        path = self.base / (request['request_id'] + '-capture.json')
        wf.write_new(path, capture or self.capture(request))
        self.mark_sending(request)
        return web.accept(self.root, path)

    def mark_sending(self, request):
        capture = self.capture(request)
        web.attach(self.root, capture['tab_id'], 'https://gemini.google.com/app',
                   capture['model_observed'], True)
        return web.mark_sending(self.root)

    def get_b_c(self):
        baseline = web.queue(self.root, 'B')
        self.accept(baseline)
        critique = web.queue(self.root, 'C')
        self.accept(critique)
        return baseline, critique

    def evidence(self):
        path = self.base / 'V1.json'
        wf.record_check(SimpleNamespace(plan=str(self.plan_path), assumption=['A1'], id='V1',
            expected='SYNTHETIC: assert 2+2=4', out=str(path), cwd=str(self.base), timeout=5,
            command=[sys.executable, '-c', 'assert 2+2 == 4; print("SYNTHETIC arithmetic checked")']))
        return path

    def test_b_prompt_never_contains_codex_proposal(self):
        baseline = web.queue(self.root, 'B')
        self.assertNotIn(self.plan['proposal'], baseline['prompt'])
        self.assertIn('SYNTHETIC QUESTION 中文', baseline['prompt'])

    def test_review_request_schema_and_receiver_reject_baseline_ids_and_duplicates(self):
        baseline = web.queue(self.root, 'B')
        self.accept(baseline)
        request = web.queue(self.root, 'C')
        schema = json.loads(request['prompt'].split('\n', 1)[1])['payload']['output_schema']
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.response(request))
        self.mark_sending(request)
        for index, checked in enumerate([['A1', 'CA-1'], ['CA-1'], ['A1', 'A1']]):
            response = self.response(request)
            response['critical_assumptions_checked'] = checked
            path = self.base / f'scope-{index}.json'
            wf.write_new(path, self.capture(request, response))
            with self.assertRaises(ValidationError):
                web.accept(self.root, path)
            self.assertFalse((self.root / request['directory'] / 'response.json').exists())
        good = self.base / 'scope-good.json'
        wf.write_new(good, self.capture(request))
        self.assertEqual(web.accept(self.root, good)['status'], 'ACCEPTED')

    def test_rejects_out_of_order_and_duplicate_send(self):
        with self.assertRaises(ValueError): web.queue(self.root, 'C')
        request = web.queue(self.root, 'B')
        self.mark_sending(request)
        with self.assertRaises(ValueError): web.mark_sending(self.root)
        with self.assertRaises(ValueError): web.queue(self.root, 'B')

    def test_unknown_send_survives_recovery(self):
        request = web.queue(self.root, 'B')
        self.mark_sending(request)
        web.failure(self.root, 'send_unknown', 'SYNTHETIC lost acknowledgment')
        self.assertEqual(web.read_state(self.root)['requests'][-1]['status'], 'SEND_UNKNOWN')
        with self.assertRaises(ValueError): web.mark_sending(self.root)

    def test_streaming_and_missing_copy_and_unstable_rejected(self):
        request = web.queue(self.root, 'B')
        self.mark_sending(request)
        for key, value in [('stop_visible', True), ('copy_visible', False), ('stable_observations', 1)]:
            capture = self.capture(request)
            capture['completion'][key] = value
            path = self.base / (key + '.json')
            wf.write_new(path, capture)
            with self.assertRaises(ValueError): web.accept(self.root, path)

    def test_duplicate_key_truncation_and_nan_rejected(self):
        request = web.queue(self.root, 'B')
        self.mark_sending(request)
        for index, raw in enumerate(['{"task_id":"x","task_id":"y"}', '{"proposal":', '{"x":NaN}']):
            capture = self.capture(request)
            capture['raw_response'] = raw
            capture['raw_response_sha256'] = wf.sha(raw.encode('utf-8'))
            path = self.base / f'bad-{index}.json'
            wf.write_new(path, capture)
            with self.assertRaises(ValueError):
                web.accept(self.root, path)

    def test_wrong_task_or_request_rejected(self):
        request = web.queue(self.root, 'B')
        capture = self.capture(request)
        capture['request_id'] = 'wrong'
        with self.assertRaises(ValueError): self.accept(request, capture)

    def test_rejects_reused_conversation(self):
        baseline = web.queue(self.root, 'B')
        self.accept(baseline)
        critique = web.queue(self.root, 'C')
        capture = self.capture(critique)
        capture['source_url'] = self.capture(baseline)['source_url']
        with self.assertRaises(ValueError): self.accept(critique, capture)

    def test_modified_frozen_prompt_rejected(self):
        request = web.queue(self.root, 'B')
        (self.root / request['directory'] / 'prompt.txt').write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError): web.mark_sending(self.root)

    def test_repeated_failure_and_policy_block_have_different_recovery(self):
        for _ in range(2):
            self.assertEqual(web.failure(self.root, 'recoverable', 'fixture')['status'], 'AUTOMATION_RETRY_AVAILABLE')
        self.assertEqual(web.failure(self.root, 'recoverable', 'fixture')['status'], 'MANUAL_FALLBACK_AVAILABLE')
        self.assertEqual(web.failure(self.root, 'blocked', 'fixture')['status'], 'AUTOMATION_RECOVERY_REQUIRED')

    def test_offline_b_c_d_to_real_local_gate(self):
        self.get_b_c()
        check = self.evidence()
        ledger = self.base / 'ledger.json'
        wf.write_new(ledger, {'issues': [], 'note': 'SYNTHETIC OFFLINE FIXTURE'})
        final = web.queue(self.root, 'D', ledger_path=ledger, check_paths=[check])
        self.accept(final)
        self.assertEqual(web.finish(self.root, [check])['status'], 'READY')
        self.assertEqual(web.read_state(self.root)['stage'], 'READY')

    def test_final_request_needs_evidence_and_ledger(self):
        self.get_b_c()
        with self.assertRaises(ValueError): web.queue(self.root, 'D')

    def test_accepted_baseline_cannot_be_silently_modified(self):
        baseline = web.queue(self.root, 'B')
        self.accept(baseline)
        (self.root / baseline['directory'] / 'response.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError): web.queue(self.root, 'C')


if __name__ == '__main__':
    unittest.main()
