"""Portable launcher; no installation, key lookup, or network side effects."""
from pathlib import Path
import os
import subprocess
import sys


def runtime_path(home=None, platform=None, override=None):
    override = os.environ.get('GEMINI_REVIEW_PYTHON') if override is None else override
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ValueError('GEMINI_REVIEW_PYTHON must name an existing Python executable')
        return path
    root = (Path.home() if home is None else Path(home)) / '.agents' / 'runtimes' / 'gemini-review'
    relative = 'Scripts/python.exe' if (os.name if platform is None else platform) == 'nt' else 'bin/python'
    candidate = root / relative
    return candidate if candidate.is_file() else Path(sys.executable)


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments[:1] == ['doctor']:
        import doctor
        return doctor.main(arguments[1:])
    target = 'web_flow.py' if arguments[:1] == ['web'] else 'workflow.py'
    if target == 'web_flow.py':
        arguments = arguments[1:]
    try:
        return subprocess.call([str(runtime_path()), '-B', '-X', 'utf8', str(Path(__file__).with_name(target)), *arguments])
    except (OSError, ValueError) as exc:
        print(f'Cannot launch review: {exc}. Use a Python 3.10+ virtualenv with requirements.txt installed.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
