import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from xibalba_cortex.observer_capture import CLAUDE_HOOKS, CODEX_HOOKS, drain

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('runtime,events', [('claude', CLAUDE_HOOKS), ('codex', CODEX_HOOKS)])
def test_packaged_hook_executes_installed_observer(tmp_path, runtime, events):
    plugin = ROOT/'plugins'/f'cortex-{runtime}'
    hooks = json.loads((plugin/'hooks/hooks.json').read_text())['hooks']
    assert set(hooks) == set(events)
    env = dict(os.environ, XIBALBA_CORTEX_HOME=str(tmp_path/'profile'),
               PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'])
    result = subprocess.run([sys.executable, str(plugin/'scripts/bridge.py'), 'hook', '--runtime', runtime],
        input=json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'plugin-canary'}),
        text=True, capture_output=True, env=env, timeout=5)
    assert result.returncode == 0, result.stderr
    if runtime == 'codex':
        assert json.loads(result.stdout) == {}
    assert drain(tmp_path/'profile')['acked'] == 1
    check = subprocess.run([sys.executable, str(plugin/'scripts/bridge.py'), 'doctor', '--runtime', runtime],
                           env=env, capture_output=True, text=True)
    assert check.returncode == 0
    assert json.loads(check.stdout)['live_callback_verified'] is False


def test_missing_backend_fails_open_without_creating_profile(tmp_path):
    script = ROOT/'plugins/cortex-codex/scripts/bridge.py'
    result = subprocess.run([sys.executable, str(script), 'hook', '--runtime', 'codex'],
        env={'PATH': '', 'XIBALBA_CORTEX_HOME': str(tmp_path/'missing')},
        input='{}', capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout) == {}
    assert not (tmp_path/'missing').exists()


def test_marketplaces_resolve_packages_and_mcp_commands():
    claude = json.loads((ROOT/'.claude-plugin/marketplace.json').read_text())
    codex = json.loads((ROOT/'.agents/plugins/marketplace.json').read_text())
    for entry in claude['plugins']:
        plugin = ROOT/entry['source']
        assert json.loads((plugin/'.claude-plugin/plugin.json').read_text())['name'] == entry['name']
        assert json.loads((plugin/'.mcp.json').read_text())['mcpServers']['cortex']['command'] == 'xibalba-cortex'
    for entry in codex['plugins']:
        plugin = ROOT/entry['source']['path']
        assert json.loads((plugin/'plugin.json').read_text())['name'] == entry['name']
        assert json.loads((plugin/'mcp.json').read_text())['mcpServers']['cortex']['type'] == 'stdio'
        assert entry['policy']['installation'] == 'AVAILABLE'
    gemini = json.loads((ROOT/'gemini-extension.json').read_text())
    assert (ROOT/gemini['contextFileName']).exists()
    assert gemini['settings'][0]['envVar'] == 'XIBALBA_CORTEX_HOME'
    for surface in ['spark', 'perplexity']:
        template = json.loads((ROOT/f'integrations/{surface}/connector-template.json').read_text())
        assert template['template_only'] is True
        assert template['capture_scope'] == 'cortex_tool_calls'


def test_archives_are_self_contained_and_reproducible(tmp_path):
    import importlib.util
    import zipfile
    module = importlib.util.spec_from_file_location('builder', ROOT/'scripts/build_cortex_plugins.py')
    builder = importlib.util.module_from_spec(module); module.loader.exec_module(builder)
    first, second = tmp_path/'first', tmp_path/'second'
    builder.archives(first); builder.archives(second)
    assert (first/'SHA256SUMS').read_text() == (second/'SHA256SUMS').read_text()
    for platform, manifest in [('claude', '.claude-plugin/plugin.json'), ('codex', 'plugin.json'), ('gemini', 'gemini-extension.json')]:
        with zipfile.ZipFile(first/f'cortex-{platform}-0.1.0.zip') as archive:
            assert manifest in archive.namelist()
            assert not any('..' in name.split('/') for name in archive.namelist())
