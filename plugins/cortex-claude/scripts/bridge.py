"""Dependency-free plugin launcher; Cortex itself must already be installed."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['doctor', 'hook'])
    parser.add_argument('--runtime', choices=['claude', 'codex'])
    args = parser.parse_args()
    backend = shutil.which('xibalba-cortex-observer')
    home = os.environ.get('XIBALBA_CORTEX_HOME')
    if args.action == 'doctor':
        checks = {'backend_available': bool(backend), 'mcp_available': bool(shutil.which('xibalba-cortex')),
                  'explicit_profile_configured': bool(home), 'capture_mode': os.environ.get('XIBALBA_CORTEX_CAPTURE_MODE', 'metadata'),
                  'native_hook_runtime': args.runtime, 'live_callback_verified': False}
        print(json.dumps(checks))
        return 0 if all(checks[k] for k in ['backend_available', 'mcp_available', 'explicit_profile_configured']) else 1
    # Observation-only fail-open behavior. No package installation, downloads,
    # daemon spawning or settings mutations inside callbacks.
    if not args.runtime or not backend or not home:
        print('{}')
        print('Cortex observer is not configured; run the plugin connection check.', file=sys.stderr)
        return 0
    mode = os.environ.get('XIBALBA_CORTEX_CAPTURE_MODE', 'metadata')
    if mode not in {'metadata', 'redacted'}:
        print('{}')
        return 0
    try:
        subprocess.run([backend, args.runtime+'-hook', '--home', str(Path(home).expanduser()),
                        '--mode', mode], timeout=2, check=True)
    except (OSError, subprocess.SubprocessError):
        print('{}')
        print('Cortex observation delivery failed; the agent may continue.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
