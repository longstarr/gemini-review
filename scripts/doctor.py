"""Local runtime diagnostics only: no browser, network, credentials or installation."""
import argparse
import json
import subprocess

from run import runtime_path


PROBE = '''import importlib.metadata, json, sys
result = {"python": list(sys.version_info[:3]), "jsonschema": None, "draft202012": False}
try:
    import jsonschema
    result["jsonschema"] = importlib.metadata.version("jsonschema")
    result["draft202012"] = callable(jsonschema.Draft202012Validator)
except Exception as exc:
    result["dependency_error"] = type(exc).__name__
print(json.dumps(result))
'''


def diagnose():
    report = {'status': 'ERROR', 'browser_check': 'NOT_CHECKED',
              'scope': 'Local Python/dependency probe only; not review READY or browser availability.',
              'issues': []}
    try:
        executable = runtime_path().resolve()
        report['selected_python'] = str(executable)
        completed = subprocess.run([str(executable), '-B', '-X', 'utf8', '-c', PROBE],
                                   capture_output=True, text=True, encoding='utf-8', timeout=15)
        if completed.returncode:
            report['issues'].append('Selected Python could not complete the local probe.')
            return report
        probe = json.loads(completed.stdout)
        version = probe.get('python')
        if not isinstance(version, list) or len(version) != 3 or not all(type(n) is int for n in version):
            raise ValueError('invalid probe version')
        report['python_version'] = '.'.join(map(str, version))
        if version[:2] < [3, 10]:
            report['issues'].append('Python 3.10+ is required.')
        dependency = probe.get('jsonschema')
        report['jsonschema_version'] = dependency
        try:
            parts = tuple(int(part) for part in dependency.split('.')[:2])
            supported = len(parts) == 2 and (4, 23) <= parts < (5, 0)
        except (AttributeError, TypeError, ValueError):
            supported = False
        if not supported or probe.get('draft202012') is not True:
            report['issues'].append('Install requirements.txt using the selected interpreter (jsonschema>=4.23,<5).')
        if not report['issues']:
            report['status'] = 'OK'
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        # Do not print arbitrary subprocess output, environment or exception contents.
        report['issues'].append('Cannot inspect the selected runtime. Check GEMINI_REVIEW_PYTHON and interpreter permissions.')
    return report


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(arguments)
    result = diagnose()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'OK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
