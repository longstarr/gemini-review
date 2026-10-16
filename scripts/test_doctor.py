"""Offline diagnostic contract tests; no real browser or Gemini calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import doctor


class DoctorTests(unittest.TestCase):
    def probe(self, value, returncode=0):
        return subprocess.CompletedProcess([], returncode, json.dumps(value), '')

    def test_real_selected_interpreter_and_launcher_doctor(self):
        env = dict(os.environ, GEMINI_REVIEW_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1')
        output = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).with_name('run.py')), 'doctor'],
                                capture_output=True, text=True, encoding='utf-8', timeout=25, env=env)
        self.assertEqual(output.returncode, 0, output.stderr)
        report = json.loads(output.stdout)
        self.assertEqual(report['status'], 'OK')
        self.assertEqual(report['browser_check'], 'NOT_CHECKED')
        self.assertEqual(Path(report['selected_python']), Path(sys.executable).resolve())

    def test_missing_old_or_new_dependency_is_diagnosed(self):
        for dependency in [None, '4.22.0', '5.0.0']:
            with self.subTest(dependency=dependency), patch.object(doctor, 'runtime_path', return_value=Path(sys.executable)), patch.object(doctor.subprocess, 'run', return_value=self.probe({'python':[3,12,0], 'jsonschema':dependency, 'draft202012':False})):
                self.assertEqual(doctor.diagnose()['status'], 'ERROR')

    def test_old_python_and_wrong_probe_shape_are_refused(self):
        for version in [[3,9,9], '3.12', [3,12], [3,True,0]]:
            with self.subTest(version=version), patch.object(doctor, 'runtime_path', return_value=Path(sys.executable)), patch.object(doctor.subprocess, 'run', return_value=self.probe({'python':version, 'jsonschema':'4.26.0', 'draft202012':True})):
                self.assertEqual(doctor.diagnose()['status'], 'ERROR')

    def test_missing_override_is_safe_and_never_starts_probe(self):
        with patch.object(doctor, 'runtime_path', side_effect=ValueError('SENSITIVE_SENTINEL')), patch.object(doctor.subprocess, 'run') as runner:
            result = doctor.diagnose()
        runner.assert_not_called()
        self.assertEqual(result['status'], 'ERROR')
        self.assertNotIn('SENSITIVE_SENTINEL', json.dumps(result))

    def test_probe_failure_timeout_or_invalid_output_does_not_leak_output(self):
        values = [self.probe({}, 1), subprocess.TimeoutExpired(['SENSITIVE_SENTINEL'],15),
                  subprocess.CompletedProcess([],0,'SENSITIVE_SENTINEL',''), self.probe([])]
        for value in values:
            kwargs = {'side_effect':value} if isinstance(value,Exception) else {'return_value':value}
            with self.subTest(value=type(value).__name__), patch.object(doctor, 'runtime_path',return_value=Path(sys.executable)), patch.object(doctor.subprocess,'run',**kwargs):
                result=doctor.diagnose()
                self.assertEqual(result['status'],'ERROR')
                self.assertNotIn('SENSITIVE_SENTINEL',json.dumps(result))

    def test_diagnostics_does_not_open_sockets_or_read_credentials(self):
        import socket
        with patch.object(socket,'socket',side_effect=AssertionError('no network')), patch.object(doctor,'runtime_path',return_value=Path(sys.executable)), patch.object(doctor.subprocess,'run',return_value=self.probe({'python':[3,12,0],'jsonschema':'4.26.0','draft202012':True})), patch.dict(os.environ,{'GEMINI_API_KEY':'SENSITIVE_SENTINEL'}):
            result=doctor.diagnose()
        self.assertEqual(result['status'],'OK')
        self.assertNotIn('SENSITIVE_SENTINEL',json.dumps(result))

    def test_main_has_nonzero_exit_on_local_error(self):
        with patch.object(doctor,'diagnose',return_value={'status':'ERROR'}),patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(doctor.main([]),2)


if __name__ == '__main__':
    unittest.main()
