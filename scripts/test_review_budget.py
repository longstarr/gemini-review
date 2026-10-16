"""Synthetic offline budget/recovery regressions; no Gemini requests."""
import unittest

import web_flow as web
import workflow as wf
import test_web_flow as fixtures


class ReviewBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebFlowTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_default_and_invalid_budget_values(self):
        self.assertEqual(web.review_budget({}),3)
        for value in [True,0,-1,'5']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                web.review_budget({'max_review_rounds':value})
        for value in [None,True,0,-1]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                web.set_budget(self.f.root,value,'SYNTHETIC user authorization')
        with self.assertRaises(ValueError): web.set_budget(self.f.root,5,'')

    def test_budget_never_releases_active_or_unresolved_send(self):
        request=web.queue(self.f.root,'B')
        with self.assertRaises(ValueError): web.set_budget(self.f.root,5,'SYNTHETIC authorization')
        self.f.mark_sending(request)
        with self.assertRaises(ValueError): web.set_budget(self.f.root,5,'SYNTHETIC authorization')
        web.abandon(self.f.root,'SYNTHETIC original tab permanently unavailable')
        with self.assertRaises(ValueError): web.set_budget(self.f.root,5,'SYNTHETIC authorization')
        self.assertTrue(web.read_state(self.f.root)['terminal'])

    def test_extended_budget_keeps_consumed_rounds_and_allows_real_local_gate(self):
        self.f.accept(web.queue(self.f.root,'B'))
        for index in range(3):
            request=web.queue(self.f.root,'C')
            self.f.mark_sending(request)
            capture=self.f.base/('completed-'+str(index)+'.json')
            wf.write_new(capture,self.f.capture(request))
            web.abandon(self.f.root,'SYNTHETIC completed invalid response',capture)
        with self.assertRaisesRegex(ValueError,'budget exhausted'): web.queue(self.f.root,'C')
        result=web.set_budget(self.f.root,5,'SYNTHETIC explicit user authorization for two extra rounds')
        self.assertEqual(result['consumed_rounds'],3)
        with self.assertRaises(ValueError): web.set_budget(self.f.root,2,'SYNTHETIC lower than consumed')
        state=web.read_state(self.f.root)
        self.assertEqual(len(state['review_budget_changes']),1)
        self.assertEqual(len(state['requests']),4)
        self.f.accept(web.queue(self.f.root,'C'))
        check=self.f.evidence()
        ledger=self.f.base/'ledger.json'
        wf.write_new(ledger,{'issues':[]})
        request=web.queue(self.f.root,'D',ledger_path=ledger,check_paths=[check])
        self.assertEqual(request['round'],5)
        self.f.accept(request)
        self.assertEqual(web.finish(self.f.root,[check])['status'],'READY')

    def test_budget_changes_are_persisted_without_clearing_failures(self):
        web.failure(self.f.root,'recoverable','SYNTHETIC prior failure')
        before=web.read_state(self.f.root)
        web.set_budget(self.f.root,5,'SYNTHETIC explicitly authorized')
        after=web.read_state(self.f.root)
        self.assertEqual(after['rounds'],before['rounds'])
        self.assertEqual(after['failures'],before['failures'])
        self.assertEqual(after['consecutive_failures'],before['consecutive_failures'])
        self.assertEqual(after['max_review_rounds'],5)


if __name__=='__main__':
    unittest.main()
