"""Offline behavioral checks; all reviewer fixtures are synthetic, never real Gemini."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from jsonschema.exceptions import ValidationError
import workflow as wf


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.question = self.root / 'question.txt'
        self.question.write_text('Test local arithmetic assertion; no real task.', encoding='utf-8')
        self.plan_path = self.root / 'plan.json'
        self.review_path = self.root / 'review.json'
        self.receipt_path = self.root / 'receipt.json'
        self.plan = {'protocol': wf.PROTOCOL, 'task_id': 'offline-fixture',
                     'question_sha256': wf.sha(self.question.read_bytes()), 'version': 'v1',
                     'proposal': 'Use an isolated Python assertion.',
                     'critical_assumptions': [{'id': 'A1', 'claim': 'Python integer addition works',
                                               'verification_requirement': 'Assert 2+2 == 4'}],
                     'failure_modes': ['Python process fails']}
        self.save(self.plan_path, self.plan)
        self.check_path = self.root / 'V1.json'
        self.record = wf.record_check(SimpleNamespace(
            plan=str(self.plan_path), assumption=['A1'], id='V1',
            expected='2+2 equals 4', out=str(self.check_path), cwd=str(self.root), timeout=5,
            command=[sys.executable, '-c', 'assert 2 + 2 == 4; print("assertion passed")']))
        self.review = {'protocol': wf.PROTOCOL, 'task_id': 'offline-fixture',
                       'request_id': 'synthetic-test-only',
                       'plan_sha256': wf.sha(self.plan_path.read_bytes()),
                       'round': 2, 'phase': 'final', 'complete': True, 'blockers': [],
                       'verification_requests': [], 'divergences': [],
                       'critical_assumptions_checked': ['A1'], 'verdict': 'APPROVED',
                       'end_marker': 'END_REVIEW'}
        self.receipt = {'protocol': wf.PROTOCOL, 'task_id': 'offline-fixture',
                        'request_id': 'synthetic-test-only', 'transport': 'manual',
                        'source_ref': 'SYNTHETIC OFFLINE TEST; NOT GEMINI',
                        'model_observed': 'synthetic-test-fixture', 'fresh_context': True,
                        'completion_observed': True, 'response_sha256': '0' * 64}
        self.sync()

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def sync(self):
        self.save(self.review_path, self.review)
        self.receipt['response_sha256'] = wf.sha(self.review_path.read_bytes())
        self.save(self.receipt_path, self.receipt)

    def run_gate(self, checks=None, waivers=()):
        return wf.gate(self.plan_path, self.review_path, self.receipt_path,
                       [self.check_path] if checks is None else checks, self.question,
                       waiver_paths=waivers)

    def set_research(self):
        self.plan['task_kind'] = 'research'
        self.save(self.plan_path, self.plan)
        plan_hash = wf.sha(self.plan_path.read_bytes())
        self.review['plan_sha256'] = plan_hash
        self.record['plan_sha256'] = plan_hash
        self.save(self.check_path, self.record)
        self.sync()

    def make_waiver(self):
        plan_hash = wf.sha(self.plan_path.read_bytes())
        signature = 'OFFLINE TEST USER 同意放行 ' + plan_hash + ' 中的 A1，仅作建议。'
        artifact = self.root / 'synthetic-user-approval.txt'
        artifact.write_text(signature, encoding='utf-8')
        waiver = {'protocol': wf.PROTOCOL, 'id': 'W1', 'task_id': 'offline-fixture',
            'plan_sha256': plan_hash, 'assumption_ids': ['A1'], 'reason': 'unavailable experiment',
            'unverified_risks': 'claim may be wrong', 'allowed_scope': 'advisory_only',
            'decision': 'ACCEPT_UNVERIFIED_FOR_THIS_PLAN', 'signed_by': 'OFFLINE TEST USER',
            'signed_at': datetime.now(timezone.utc).isoformat(), 'approval_text': signature,
            'approval_source': 'user_message', 'artifact': artifact.name,
            'artifact_sha256': wf.sha(artifact.read_bytes())}
        path = self.root / 'waiver.json'
        self.save(path, waiver)
        self.review['verdict'] = 'CONDITIONAL_PASS'
        self.review['verification_requests'] = [{'id': 'V-request', 'assumption_ids': ['A1'],
            'request': 'pending human experiment', 'status': 'USER_ACCEPTED_UNVERIFIED',
            'evidence_ids': ['W1']}]
        self.sync()
        return path, waiver

    def set_literature(self):
        self.record['method'] = 'literature'
        timestamp = datetime.now(timezone.utc).isoformat()
        self.record['sources'] = [{'url': url, 'title': 'SYNTHETIC OFFLINE REFERENCE',
            'accessed_at': timestamp, 'supports': 'fixture claim',
            'limitations': 'not a real source access; test fixture only'}
            for url in ['https://example.org/source1', 'https://example.net/source2']]
        self.save(self.check_path, self.record)

    def test_complete_same_version_evidence_is_ready(self):
        self.assertEqual(self.run_gate()['status'], 'READY')

    def test_unanimous_approval_without_logs_is_blocked(self):
        with self.assertRaisesRegex(ValueError, 'missing PASS evidence'):
            self.run_gate([])

    def test_plan_edit_invalidates_review(self):
        self.plan['proposal'] += ' changed'
        self.save(self.plan_path, self.plan)
        with self.assertRaisesRegex(ValueError, 'different plan version'):
            self.run_gate()

    def test_question_edit_invalidates_plan(self):
        self.question.write_text('Different user question', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'question changed'):
            self.run_gate()

    def test_conditional_pass_does_not_execute(self):
        self.review['verdict'] = 'CONDITIONAL_PASS'
        self.sync()
        with self.assertRaisesRegex(ValueError, 'APPROVED'):
            self.run_gate()

    def test_approved_with_blocker_is_blocked(self):
        self.review['blockers'] = [{'id': 'B1', 'issue': 'Synthetic blocker',
                                    'trigger': 'always', 'evidence': 'fixture',
                                    'required_fix': 'resolve it'}]
        self.sync()
        with self.assertRaisesRegex(ValueError, 'unresolved blockers'):
            self.run_gate()

    def test_incomplete_response_is_blocked(self):
        self.receipt['completion_observed'] = False
        self.sync()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.run_gate()

    def test_old_context_cannot_be_final(self):
        self.receipt['fresh_context'] = False
        self.sync()
        with self.assertRaisesRegex(ValueError, 'fresh final context'):
            self.run_gate()

    def test_over_budget_review_is_blocked(self):
        self.review['round'] = 4
        self.sync()
        with self.assertRaisesRegex(ValueError, 'in-budget'):
            self.run_gate()

    def test_different_request_receipt_is_blocked(self):
        self.receipt['request_id'] = 'different-request'
        self.sync()
        with self.assertRaisesRegex(ValueError, 'receipt does not match'):
            self.run_gate()

    def test_tampered_artifact_is_blocked(self):
        (self.root / self.record['artifact']).write_text('tampered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'):
            self.run_gate()

    def test_uncovered_critical_assumption_is_blocked(self):
        self.plan['critical_assumptions'].append(
            {'id': 'A2', 'claim': 'another premise', 'verification_requirement': 'another test'})
        self.save(self.plan_path, self.plan)
        new_hash = wf.sha(self.plan_path.read_bytes())
        self.review['plan_sha256'] = new_hash
        self.review['critical_assumptions_checked'].append('A2')
        self.record['plan_sha256'] = new_hash
        self.save(self.check_path, self.record)
        self.sync()
        with self.assertRaisesRegex(ValueError, 'missing PASS evidence'):
            self.run_gate()

    def test_failed_assertion_produces_fail_log_and_blocks(self):
        path = self.root / 'failed.json'
        record = wf.record_check(SimpleNamespace(
            plan=str(self.plan_path), assumption=['A1'], id='V2', expected='false assertion',
            out=str(path), cwd=str(self.root), timeout=5,
            command=[sys.executable, '-c', 'assert False, "intentional negative test"']))
        self.assertEqual(record['status'], 'FAIL')
        with self.assertRaisesRegex(ValueError, 'failed or unknown'):
            self.run_gate([path])

    def test_missing_evidence_for_request_is_blocked(self):
        self.review['verification_requests'] = [{'id': 'V-request', 'assumption_ids': ['A1'],
            'request': 'prove addition', 'status': 'SATISFIED', 'evidence_ids': ['absent']}]
        self.sync()
        with self.assertRaisesRegex(ValueError, 'not backed'):
            self.run_gate()

    def test_request_cannot_cite_evidence_for_other_assumption(self):
        self.plan['critical_assumptions'].append({'id': 'A2', 'claim': 'subtraction works',
            'verification_requirement': 'assert 4-2 == 2'})
        self.save(self.plan_path, self.plan)
        new_hash = wf.sha(self.plan_path.read_bytes())
        self.review['plan_sha256'] = new_hash
        self.review['critical_assumptions_checked'].append('A2')
        self.record['plan_sha256'] = new_hash
        self.save(self.check_path, self.record)
        second = self.root / 'V2.json'
        wf.record_check(SimpleNamespace(plan=str(self.plan_path), assumption=['A2'], id='V2',
            expected='subtraction assertion', out=str(second), cwd=str(self.root), timeout=5,
            command=[sys.executable, '-c', 'assert 4 - 2 == 2']))
        self.review['verification_requests'] = [{'id': 'VR2', 'assumption_ids': ['A2'],
            'request': 'prove subtraction', 'status': 'SATISFIED', 'evidence_ids': ['V1']}]
        self.sync()
        with self.assertRaisesRegex(ValueError, 'different assumptions'):
            self.run_gate([self.check_path, second])

    def test_asserted_pass_cannot_hide_failed_process(self):
        artifact = self.root / self.record['artifact']
        raw = wf.load(artifact)
        raw['exit_code'] = 1
        self.save(artifact, raw)
        self.record['artifact_sha256'] = wf.sha(artifact.read_bytes())
        self.save(self.check_path, self.record)
        with self.assertRaisesRegex(ValueError, 'successful test'):
            self.run_gate()

    def test_duplicate_keys_are_not_silently_accepted(self):
        self.review_path.write_text('{"verdict":"REJECTED","verdict":"APPROVED"}',
                                    encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            self.run_gate()

    def test_truncated_json_is_not_repaired(self):
        self.review_path.write_text('{"verdict":', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            self.run_gate()

    def test_unknown_fields_are_blocked(self):
        self.review['ignore_checks'] = True
        self.sync()
        with self.assertRaises(ValidationError):
            self.run_gate()

    def test_literature_log_allows_research_without_local_test_requirement(self):
        self.set_research()
        self.set_literature()
        self.assertEqual(self.run_gate()['status'], 'READY')

    def test_literature_without_two_sources_is_blocked(self):
        self.set_literature()
        del self.record['sources']
        self.save(self.check_path, self.record)
        with self.assertRaisesRegex(ValueError, 'two distinct'):
            self.run_gate()

    def test_duplicate_literature_sources_are_blocked(self):
        self.set_literature()
        self.record['sources'][1]['url'] = self.record['sources'][0]['url']
        self.save(self.check_path, self.record)
        with self.assertRaisesRegex(ValueError, 'two distinct'):
            self.run_gate()

    def test_signed_research_waiver_remains_explicitly_unverified(self):
        self.set_research()
        path, _ = self.make_waiver()
        result = self.run_gate([], [path])
        self.assertEqual(result['status'], 'READY_WITH_WAIVER')
        self.assertEqual(result['verified_assumptions'], [])
        self.assertEqual(result['unverified_assumptions'], ['A1'])

    def test_implementation_cannot_use_research_waiver(self):
        path, _ = self.make_waiver()
        with self.assertRaisesRegex(ValueError, 'only to research/planning'):
            self.run_gate([], [path])

    def test_waiver_requires_specific_signature_not_generic_approval(self):
        self.set_research()
        path, waiver = self.make_waiver()
        waiver['approval_text'] = 'Gemini recommends proceeding at 92 percent'
        self.save(path, waiver)
        with self.assertRaisesRegex(ValueError, 'explicit user signature'):
            self.run_gate([], [path])

    def test_waiver_cannot_be_reused_for_changed_plan(self):
        self.set_research()
        path, waiver = self.make_waiver()
        waiver['plan_sha256'] = '0' * 64
        self.save(path, waiver)
        with self.assertRaisesRegex(ValueError, 'waiver belongs to a different'):
            self.run_gate([], [path])

    def test_waiver_does_not_override_actual_blocker(self):
        self.set_research()
        path, _ = self.make_waiver()
        self.review['blockers'] = [{'id': 'B1', 'issue': 'real contradiction', 'trigger': 'always',
            'evidence': 'fixture', 'required_fix': 'fix contradiction'}]
        self.sync()
        with self.assertRaisesRegex(ValueError, 'unresolved blockers'):
            self.run_gate([], [path])


class ApiTests(unittest.TestCase):
    def test_partial_or_refused_response_is_not_completion(self):
        for status in ['in_progress', 'failed', 'requires_action', 'cancelled']:
            with self.subTest(status=status), self.assertRaises(ValueError):
                wf.parse_api_response({'status': status, 'steps': []})

    def test_completed_response_retains_exact_json_text(self):
        body = '{"test": "\\n```code```"}'
        raw = {'status': 'completed', 'steps': [
            {'type': 'model_output', 'content': [{'type': 'text', 'text': body}]}]}
        self.assertEqual(wf.parse_api_response(raw), body)

    def test_default_dry_run_never_uses_network_or_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'prompt.txt').write_text('original question only', encoding='utf-8')
            (root / 'system.txt').write_text('independent baseline', encoding='utf-8')
            args = SimpleNamespace(model='synthetic-model', kind='baseline',
                prompt=str(root / 'prompt.txt'), system=str(root / 'system.txt'),
                out_dir=str(root / 'result'), send=False, timeout=5, max_output_tokens=100)
            with patch.object(wf.request, 'urlopen') as network:
                self.assertEqual(wf.api_call(args)['network_calls'], 0)
                network.assert_not_called()
            payload = wf.load(root / 'result/request.json')
            self.assertNotIn('previous_interaction_id', payload)
            self.assertFalse(payload['stream'])
            self.assertFalse(payload['store'])

    def test_missing_key_prevents_send(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'p').write_text('question', encoding='utf-8')
            (root / 's').write_text('system', encoding='utf-8')
            args = SimpleNamespace(model='synthetic-model', kind='review',
                prompt=str(root / 'p'), system=str(root / 's'), out_dir=str(root / 'out'),
                send=True, timeout=5, max_output_tokens=100)
            original_load = wf.load
            def enabled_preferences(path):
                return {'api_enabled': True} if Path(path).name == 'preferences.json' else original_load(path)
            with patch.object(wf, 'load', side_effect=enabled_preferences), patch.object(
                    wf, 'load_api_key', return_value=None), patch.object(
                    wf.request, 'urlopen') as network, self.assertRaisesRegex(ValueError, 'no request sent'):
                wf.api_call(args)
            network.assert_not_called()

    def test_manual_preference_blocks_api_before_reading_key(self):
        args = SimpleNamespace(send=True)
        with patch.object(wf, 'load_api_key') as key_reader, patch.object(
                wf.request, 'urlopen') as network, self.assertRaisesRegex(ValueError, 'API disabled'):
            wf.api_call(args)
        key_reader.assert_not_called()
        network.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
