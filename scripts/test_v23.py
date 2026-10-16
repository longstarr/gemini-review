"""Offline adversarial regressions; all reviewer responses are synthetic."""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run
import workflow as wf
import web_flow as web
import audit_package
import test_web_flow as fixtures
import test_workflow as gate_fixtures


class EnvelopeTests(unittest.TestCase):
    def test_nested_fences_unicode_and_braces_in_strings(self):
        value = {'proposal':'中文😀\n```json\n{"x":"}\\"}\n```\n', 'nested':[{'x':2}]}
        raw = json.dumps(value,ensure_ascii=False)
        for framed in [raw, '好的，结果如下：\n```json\n'+raw+'\n```\n谢谢。', '\ufeff'+raw]:
            self.assertEqual(wf.strict_json(wf.json_object_text(framed)),value)

    def test_ambiguous_malformed_and_nonstandard_objects_refused(self):
        for raw in ['{} {}','{"x":1,}','{"x":NaN}','{"x":1,"x":2}',
                    '{"x":1,"\\u0078":2}','{"x":','[{"x":1}]','{]','no JSON']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                wf.json_object_text(raw)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WebFlowTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_receipt_crash_resumes_without_duplicate_send(self):
        request=web.queue(self.f.root,'B')
        self.f.accept(request)
        request=web.queue(self.f.root,'C')
        self.f.mark_sending(request)
        capture=self.f.base/'crash-capture.json'
        wf.write_new(capture,self.f.capture(request))
        commit=web.immutable_bytes
        def crash(path,data):
            if Path(path).name=='receipt.json':
                raise RuntimeError('SIMULATED power loss before receipt commit')
            commit(path,data)
        with patch.object(web,'immutable_bytes',side_effect=crash),self.assertRaises(RuntimeError):
            web.accept(self.f.root,capture)
        self.assertEqual(web.read_state(self.f.root)['requests'][-1]['status'],'SENDING')
        with self.assertRaises(ValueError):
            web.mark_sending(self.f.root)
        self.assertEqual(web.accept(self.f.root,capture)['status'],'ACCEPTED')

    def test_state_commit_crash_resumes_same_response(self):
        request=web.queue(self.f.root,'B')
        self.f.mark_sending(request)
        capture=self.f.base/'capture.json'
        wf.write_new(capture,self.f.capture(request))
        with patch.object(web,'save_state',side_effect=RuntimeError('SIMULATED crash')),self.assertRaises(RuntimeError):
            web.accept(self.f.root,capture)
        self.assertEqual(web.accept(self.f.root,capture)['status'],'ACCEPTED')

    def test_preexisting_different_response_is_never_overwritten(self):
        request=web.queue(self.f.root,'B')
        self.f.mark_sending(request)
        response=self.f.root/request['directory']/'response.json'
        response.write_text('{"tampered":true}',encoding='utf-8')
        capture=self.f.base/'capture.json'
        wf.write_new(capture,self.f.capture(request))
        with self.assertRaisesRegex(ValueError,'differs'):
            web.accept(self.f.root,capture)
        self.assertEqual(response.read_text(encoding='utf-8'),'{"tampered":true}')

    def test_kernel_lock_blocks_second_process_and_releases(self):
        command=[sys.executable,'-B','-X','utf8',str(Path(web.__file__)),'failure','--run-dir',str(self.f.root),'--reason','SYNTHETIC contender','--category','recoverable']
        holder_code='import sys; from pathlib import Path; sys.path.insert(0,sys.argv[2]); import web_flow as w; guard=w.journal_lock(Path(sys.argv[1])); guard.__enter__(); print("LOCKED",flush=True); input(); guard.__exit__(None,None,None)'
        holder=subprocess.Popen([sys.executable,'-B','-c',holder_code,str(self.f.root),str(Path(web.__file__).parent)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        try:
            self.assertEqual(holder.stdout.readline().strip(),'LOCKED')
            blocked=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=20)
        finally:
            holder.communicate('\n',timeout=20)
        self.assertNotEqual(blocked.returncode,0)
        self.assertIn('journal busy',blocked.stdout)
        allowed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(allowed.returncode,0,allowed.stdout+allowed.stderr)

    def test_never_sent_abort_requeues_but_unknown_send_cannot_abort(self):
        web.queue(self.f.root,'B')
        self.assertEqual(web.abort(self.f.root,'SYNTHETIC reset')['status'],'ABORTED_BEFORE_SEND')
        request=web.queue(self.f.root,'B')
        self.f.mark_sending(request)
        web.failure(self.f.root,'send_unknown','SYNTHETIC lost acknowledgement')
        with self.assertRaises(ValueError): web.abort(self.f.root,'must not retry')
        with self.assertRaises(ValueError): web.queue(self.f.root,'B')

    def test_browser_request_mutation_and_path_traversal_rejected(self):
        request=web.queue(self.f.root,'B')
        request_path=self.f.root/request['directory']/'browser-request.json'
        original=request_path.read_bytes()
        request_path.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'browser request changed'): web.read_state(self.f.root)
        request_path.write_bytes(original)
        state=web.read_state(self.f.root)
        state['requests'][-1]['directory']='../../outside'
        web.save_state(self.f.root,state)
        with self.assertRaisesRegex(ValueError,'unsafe request directory'): web.read_state(self.f.root)

    def test_c_prompt_references_identical_baseline_and_keeps_full_material(self):
        request=web.queue(self.f.root,'B')
        self.f.accept(request)
        request=web.queue(self.f.root,'C')
        self.assertTrue(request['prompt'].startswith('[TASK_ID:'))
        payload=json.loads(request['prompt'].split('\n',1)[1])['payload']
        self.assertEqual(payload['codex_independent_baseline']['ref'],'current_plan')
        self.assertEqual(payload['current_plan'],self.f.plan)
        self.assertEqual(payload['gemini_independent_baseline']['proposal'],'SYNTHETIC BASELINE')

    def test_completed_invalid_attempt_can_be_archived_and_retried_with_new_identity(self):
        request=web.queue(self.f.root,'B')
        self.f.mark_sending(request)
        capture=self.f.capture(request)
        capture['raw_response']='SYNTHETIC malformed completed response {'
        capture['raw_response_sha256']=wf.sha(capture['raw_response'].encode('utf-8'))
        path=self.f.base/'terminal.json'
        wf.write_new(path,capture)
        self.assertTrue(web.abandon(self.f.root,'SYNTHETIC completed invalid JSON',path)['retry_allowed'])
        retry=web.queue(self.f.root,'B')
        self.assertNotEqual(retry['request_id'],request['request_id'])
        self.assertEqual(web.read_state(self.f.root)['consecutive_failures'],1)

    def test_unknown_attempt_can_end_the_run_but_never_release_it_for_resend(self):
        request=web.queue(self.f.root,'B')
        self.f.mark_sending(request)
        self.assertFalse(web.abandon(self.f.root,'SYNTHETIC tab unavailable')['retry_allowed'])
        self.assertEqual(web.read_state(self.f.root)['stage'],'ABANDONED_UNRESOLVED')
        with self.assertRaisesRegex(ValueError,'do not automatically resend'): web.queue(self.f.root,'B')

    def test_busy_or_wrong_capture_cannot_release_send(self):
        request=web.queue(self.f.root,'B')
        self.f.mark_sending(request)
        capture=self.f.capture(request)
        capture['completion']['stop_visible']=True
        path=self.f.base/'busy.json'
        wf.write_new(path,capture)
        with self.assertRaises(ValueError): web.abandon(self.f.root,'SYNTHETIC still generating',path)
        self.assertEqual(web.read_state(self.f.root)['requests'][-1]['status'],'SENDING')

    def test_atomic_artifact_commit_failure_leaves_no_partial_final(self):
        target=self.f.base/'atomic.json'
        with patch.object(web.os,'replace',side_effect=RuntimeError('SIMULATED before commit')),self.assertRaises(RuntimeError):
            web.immutable_bytes(target,b'complete frozen bytes')
        self.assertFalse(target.exists())
        web.immutable_bytes(target,b'complete frozen bytes')
        self.assertEqual(target.read_bytes(),b'complete frozen bytes')

    def test_evidence_omits_invocation_metadata_and_rejects_oversized_raw_output(self):
        path=self.f.evidence()
        checks=web.evidence_for_prompt([path],wf.sha(self.f.plan_path.read_bytes()),self.f.plan['task_id'])
        self.assertNotIn('argv',checks[0]['raw_output'])
        self.assertNotIn('cwd',checks[0]['raw_output'])
        self.assertNotIn(str(self.f.base),json.dumps(checks))
        check=wf.load(path)
        artifact=self.f.base/check['artifact']
        raw=wf.load(artifact)
        raw['stdout']='SYNTHETIC UNREVIEWED RAW '*10000
        artifact.write_text(json.dumps(raw),encoding='utf-8')
        check['artifact_sha256']=wf.sha(artifact.read_bytes())
        path.write_text(json.dumps(check),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'too large'):
            web.evidence_for_prompt([path],check['plan_sha256'],self.f.plan['task_id'])

    def test_orphan_queue_directory_and_partial_init_recover(self):
        (self.f.root/'01-B').mkdir()
        request=web.queue(self.f.root,'B')
        self.assertEqual(request['directory'],'02-B')
        root=self.f.base/'partial-init'
        root.mkdir()
        (root/'question.txt').write_bytes(self.f.question.read_bytes())
        state=web.init(root,self.f.question,self.f.plan_path)
        self.assertEqual(state['stage'],'QUESTION_FROZEN')
        with self.assertRaises(ValueError): web.init(root,self.f.question,self.f.plan_path)


class BindingTests(unittest.TestCase):
    def test_source_change_missing_root_and_traversal_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            file=root/'source.py'
            file.write_text('print("original")',encoding='utf-8')
            manifest=[{'path':'source.py','sha256':wf.sha(file.read_bytes())}]
            wf.verify_manifest(root,manifest)
            with self.assertRaises(ValueError): wf.verify_manifest(None,manifest)
            file.write_text('print("changed")',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'mismatch'): wf.verify_manifest(root,manifest)
            with self.assertRaises(ValueError): wf.verify_manifest(root,[{'path':'../outside','sha256':'a'*64}])

    def test_web_evidence_requires_source_metadata(self):
        fixture=gate_fixtures.GateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.record['method']='web'
        fixture.save(fixture.check_path,fixture.record)
        with self.assertRaisesRegex(ValueError,'cited source'): fixture.run_gate()
        fixture.set_literature()
        fixture.record['method']='web'
        fixture.record['sources']=fixture.record['sources'][:1]
        fixture.save(fixture.check_path,fixture.record)
        self.assertEqual(fixture.run_gate()['status'],'READY')

    def test_web_finish_forwards_signed_waivers(self):
        fixture=fixtures.WebFlowTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.get_b_c()
        check=fixture.evidence()
        ledger=fixture.base/'ledger.json'
        wf.write_new(ledger,{'issues':[]})
        request=web.queue(fixture.root,'D',ledger_path=ledger,check_paths=[check])
        fixture.accept(request)
        with patch.object(wf,'gate',return_value={'status':'READY_WITH_WAIVER'}) as gate:
            web.finish(fixture.root,[check],['SYNTHETIC-WAIVER'])
        self.assertEqual(gate.call_args.kwargs['waiver_paths'],['SYNTHETIC-WAIVER'])

    def test_source_bound_gate_rejects_changed_source(self):
        fixture=gate_fixtures.GateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source=fixture.root/'source.py'
        source.write_text('original',encoding='utf-8')
        fixture.plan['source_manifest']=[{'path':'source.py','sha256':wf.sha(source.read_bytes())}]
        fixture.save(fixture.plan_path,fixture.plan)
        digest=wf.sha(fixture.plan_path.read_bytes())
        fixture.review['plan_sha256']=fixture.record['plan_sha256']=digest
        fixture.save(fixture.check_path,fixture.record)
        fixture.sync()
        arguments=(fixture.plan_path,fixture.review_path,fixture.receipt_path,[fixture.check_path],fixture.question)
        self.assertEqual(wf.gate(*arguments,source_root=fixture.root)['status'],'READY')
        source.write_text('changed after review',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'manifest mismatch'): wf.gate(*arguments,source_root=fixture.root)

    def test_disabled_key_status_never_reads_credentials(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['workflow.py','key-status']),patch.object(wf,'load_api_key') as reader,redirect_stdout(output):
            self.assertEqual(wf.main(),0)
        reader.assert_not_called()
        self.assertIsNone(json.loads(output.getvalue())['configured'])


class RuntimeTests(unittest.TestCase):
    def test_windows_and_posix_runtime_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for platform,relative in [('nt','Scripts/python.exe'),('posix','bin/python')]:
                path=root/'.agents/runtimes/gemini-review'/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'SYNTHETIC NOT EXECUTABLE')
                self.assertEqual(run.runtime_path(root,platform,''),path)

    def test_current_interpreter_fallback_and_invalid_override(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(run.runtime_path(temp,'posix',''),Path(sys.executable))
            with self.assertRaises(ValueError): run.runtime_path(temp,'posix',str(Path(temp)/'missing'))

    def test_portability_scan_detects_unencoded_io_and_personal_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.py'
            path.write_text('from pathlib import Path\nPath("x").read_text()\n# '+ 'Z:'+chr(92)+'Users'+chr(92)+'example',encoding='utf-8')
            result=audit_package.scan(temp)
            self.assertEqual(result['status'],'FAIL')
            self.assertEqual(len(result['violations']),2)

    def test_portability_scan_distinguishes_binary_and_utf8_io(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'good.py'
            path.write_text('from pathlib import Path\nPath("x").read_text(encoding="utf-8")\nPath("x").open("rb")',encoding='utf-8')
            result=audit_package.scan(temp)
            self.assertEqual(result['status'],'PASS')
            self.assertEqual(result['text_io_calls_explicit_utf8'],1)
            self.assertEqual(result['binary_io_calls'],1)


if __name__=='__main__':
    unittest.main(verbosity=2)
