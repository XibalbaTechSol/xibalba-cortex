"""Rebuild dependency-free Cortex plugin manifests and hook launchers."""
import argparse
import ast
import hashlib
import json
import zipfile
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'


def write(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2)+'\n')


def build():
    syntax = ast.parse((ROOT/'src/xibalba_cortex/observer_capture.py').read_text())
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in syntax.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {'CLAUDE_HOOKS', 'CODEX_HOOKS'}}
    CLAUDE_HOOKS, CODEX_HOOKS = constants['CLAUDE_HOOKS'], constants['CODEX_HOOKS']
    for platform, events, variable in [('claude', CLAUDE_HOOKS, 'CLAUDE_PLUGIN_ROOT'),
                                        ('codex', CODEX_HOOKS, 'PLUGIN_ROOT')]:
        base = f'plugins/cortex-{platform}'
        manifest = {'name': f'cortex-{platform}', 'version': VERSION,
                    'description': 'Cortex memory tools and opt-in local agent-event recording',
                    'author': {'name': 'Xibalba Solutions'},
                    'repository': 'https://github.com/XibalbaTechSol/xibalba-cortex'}
        if platform == 'claude':
            write(base+'/.claude-plugin/plugin.json', manifest)
            write(base+'/.mcp.json', {'mcpServers': {'cortex': {'command': 'xibalba-cortex'}}})
        else:
            manifest['$schema'] = 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json'
            write(base+'/plugin.json', manifest)
            write(base+'/mcp.json', {'$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
                                   'mcpServers': {'cortex': {'type': 'stdio', 'command': 'xibalba-cortex', 'args': []}}})
        hooks = {event: [{'hooks': [{'type': 'command',
            'command': f'python3 "${{{variable}}}/scripts/bridge.py" hook --runtime {platform}',
            'timeout': 3 if event in {'SessionEnd', 'Interrupt'} else 5}]}] for event in events}
        write(base+'/hooks/hooks.json', {'hooks': hooks})
        script = ROOT/base/'scripts/bridge.py'
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/'integrations/plugin-distribution/bridge.py', script)
    write('.claude-plugin/marketplace.json', {'name': 'xibalba-cortex', 'owner': {'name': 'Xibalba Solutions'},
        'plugins': [{'name': 'cortex-claude', 'source': './plugins/cortex-claude',
                     'description': 'Cortex memory and local Claude Code observer'}]})
    write('.agents/plugins/marketplace.json', {'name': 'xibalba-cortex',
        'interface': {'displayName': 'Xibalba Cortex'}, 'plugins': [{'name': 'cortex-codex',
        'source': {'source': 'local', 'path': './plugins/cortex-codex'},
        'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}, 'category': 'Productivity'}]})
    gemini = {'name': 'cortex-gemini', 'version': VERSION,
        'description': 'Cortex memory for Gemini CLI; no full native observer bundled',
        'contextFileName': 'GEMINI.md',
        'settings': [{'name': 'Cortex home', 'description': 'Absolute path to your Cortex profile directory',
                      'envVar': 'XIBALBA_CORTEX_HOME', 'sensitive': False}],
        'mcpServers': {'cortex': {'command': 'xibalba-cortex', 'args': []}}}
    write('plugins/cortex-gemini/gemini-extension.json', gemini)
    # Root manifest permits direct Git installation from this monorepo.
    root_gemini = {**gemini, 'contextFileName': 'plugins/cortex-gemini/GEMINI.md'}
    write('gemini-extension.json', root_gemini)
    for surface in ['perplexity', 'spark']:
        write(f'integrations/{surface}/connector-template.json', {
            'surface': surface, 'transport': 'streamable-http',
            'mcp_url': 'https://YOUR-CORTEX-HOST/mcp', 'authentication': 'oauth',
            'scopes': ['memory:read', 'memory:write'], 'validation_tool': 'cortex_connection_status',
            'capture_scope': 'cortex_tool_calls', 'template_only': True})


def archives(destination):
    destination.mkdir(parents=True, exist_ok=True)
    checksums = []
    for platform in ['claude', 'codex', 'gemini']:
        base = ROOT/f'plugins/cortex-{platform}'
        archive = destination/f'cortex-{platform}-{VERSION}.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for file in sorted(base.rglob('*')):
                if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                    if file.is_symlink():
                        raise ValueError('package symlinks are not supported')
                    info = zipfile.ZipInfo(file.relative_to(base).as_posix(), date_time=(1980,1,1,0,0,0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    output.writestr(info, file.read_bytes())
        checksums.append(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name)
    (destination/'SHA256SUMS').write_text('\n'.join(checksums)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', type=Path)
    args = parser.parse_args()
    build()
    if args.archives:
        archives(args.archives)
