"""Design the capabilities that are not built yet, as boards.

Each board starts from a captured screen of the real console and replaces only the part that is new,
using the console's own classes, so building one means composing components that already exist.
Every one carries a visible "Planned" banner naming what it needs. Contracts quote real backend
behaviour (read from store.py / local_api.py / accounts.py), not invented fields.
"""
import json, re
from pathlib import Path

import os
S = Path(os.environ.get('DESIGN_WORK', '.')).resolve()  # the working folder: boards-src/, canvas-live/, canvas-publish/ ...


def load(name):
    return json.loads((S / 'boards-src' / f'{name}.json').read_text())


WARN = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M12 9v4M12 17h.01M10.3 3.9 2.4 17.5A1.9 1.9 0 0 0 4 20.4h16'
        'a1.9 1.9 0 0 0 1.6-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0Z"></path></svg>')
CHECK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
         'stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>')
LOCK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9"></rect>'
        '<path d="M8 11V8a4 4 0 018 0v3"></path></svg>')


def banner(text):
    return ('<div class="xc-callout xc-callout--review" role="note">' + WARN +
            '<div style="min-width: 0px;"><b>Planned — not built.</b><div class="xc-note" style="margin-top: 4px;">' + text + '</div></div></div>')


def callout(tone, title, body, icon=None):
    icon = icon or (CHECK if tone == 'anchored' else WARN)
    return (f'<div class="xc-callout xc-callout--{tone}" role="{"alert" if tone == "conflict" else "status"}">{icon}'
            f'<div style="min-width: 0px;"><b>{title}</b><div class="xc-note" style="margin-top: 4px;">{body}</div></div></div>')


def field(label, input_html):
    return f'<label class="xc-field">{label}{input_html}</label>'


def inp(**kw):
    attrs = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
    cls = kw.pop('cls', 'xc-input')
    return f'<input class="xc-input" {attrs} style="">'


def replace_between(html, start, end, new, include_end=True):
    i = html.index(start)
    j = html.index(end, i) + (len(end) if include_end else 0)
    return html[:i] + new + html[j:]


out = {}


# --- 1 & 2: account recovery, on the sign-in screen --------------------------------------------------------
def auth_form(title, lede, body):
    return ('<form class="xc-auth-form" aria-labelledby="signin-title"><span class="xc-lock" aria-hidden="true">' + LOCK + '</span>'
            + f'<h2 id="signin-title" class="xc-auth-title">{title}</h2><p class="xc-auth-lede">{lede}</p>' + body + '</form>')


def with_form(base_name, name, form, h=900):
    d = load(base_name)
    html = replace_between(d['html'], '<form class="xc-auth-form"', '</form>', form)
    out[name] = {'name': name, 'w': d['w'], 'h': h, 'html': html, 'canvases': d.get('canvases', []), 'base': base_name}


SUBMIT = '<button class="xc-btn xc-btn--primary xc-auth-submit" type="submit">{} <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12h15M13 6l6 6-6 6"></path></svg></button>'
BACK = '<p class="xc-note"><a href="#" style="color: var(--accent);">Back to sign in</a></p>'

with_form('signin', 'planned-reset-request', auth_form(
    'Reset your password',
    'Enter the email for your account. If an account exists and reset delivery is set up on this profile, a one-time link is sent to it.',
    banner('The server routes exist (<code>POST /api/auth/password-reset/request</code> and <code>/confirm</code>). The sign-in screen has no “Forgot password?” link and no screens for them yet.')
    + field('Email', '<input class="xc-input" type="email" name="email" placeholder="operator@organization.com" autocomplete="username" required="" value="" style="">')
    + SUBMIT.format('Send reset link')
    + callout('review', 'Reset delivery is not set up on this profile', 'The server answered that delivery is unavailable, so no message was sent. Ask whoever runs this Cortex to configure it. (This is the 503 state. When delivery works the form says only that a link has been sent if the account exists, and never confirms whether it does.)')
    + BACK))

with_form('signin', 'planned-reset-confirm', auth_form(
    'Choose a new password',
    'Paste the reset code from the email and choose a new password of at least 10 characters.',
    banner('Reached from the link in the reset email. The code is read from the link when present.')
    + field('Reset code', '<input class="xc-input xc-input--mono" type="text" name="reset_token" placeholder="reset code from the email" autocomplete="one-time-code" required="" value="" style="">')
    + field('New password', '<input class="xc-input" type="password" name="new_password" minlength="10" autocomplete="new-password" required="" placeholder="At least 10 characters" value="" style="">')
    + field('Confirm new password', '<input class="xc-input" type="password" name="confirm_password" minlength="10" autocomplete="new-password" required="" placeholder="••••••••••••" value="" style="">')
    + SUBMIT.format('Set new password')
    + callout('conflict', 'This reset code is invalid or expired', 'Request a new link from the reset screen. A code works once.')
    + BACK))


# --- 3: account approvals (Settings > Account, admin) ------------------------------------------------------
def st_panel(base_name, name, inner, h=None):
    d = load(base_name)
    html = re.sub(r'(<section id="st-panel"[^>]*>).*?(</section></section></div></aside>)', lambda m: m.group(1) + inner + m.group(2), d['html'], count=1, flags=re.S)
    assert inner in html
    out[name] = {'name': name, 'w': d['w'], 'h': h or d['h'], 'html': html, 'canvases': d.get('canvases', []), 'base': base_name}


def pending_row(email, when):
    return (f'<li class="xc-listrow"><span><b>{email}</b> <span class="xc-meta">requested {when}</span></span>'
            '<span class="xc-actions-row"><button type="button" class="xc-btn xc-btn--primary">Approve</button></span></li>')


st_panel('settings-account', 'planned-approvals',
         '<div class="xc-form xc-settings-form">'
         + banner('<code>POST /api/auth/admin/approve</code> exists (scope <code>*</code>, CSRF-checked). There is no way to <em>list</em> accounts waiting for approval, so this needs a new read route, proposed as <code>GET /api/auth/admin/pending</code>.')
         + '<section class="xc-win xc-opscard" aria-label="Signed in as"><p class="xc-eyebrow">Signed in as</p><dl class="xc-kv">'
           '<div><dt>email</dt><dd>operator@organization.com</dd></div><div><dt>display name</dt><dd>Operator</dd></div>'
           '<div><dt>approval status</dt><dd>approved</dd></div></dl></section>'
         + '<section class="xc-win xc-opscard" aria-label="Accounts waiting for approval"><p class="xc-eyebrow">Accounts waiting for approval · 2</p>'
           '<p class="xc-note">Only operators with full scope see this. Approving lets the account sign in. It does not give it access to any agent workspace.</p>'
           '<label class="xc-check xc-settings-row"><input type="checkbox" checked=""><span>Mark the email address as verified</span></label>'
           '<ul class="xc-list">' + pending_row('new.operator@organization.com', '10-10 21:40') + pending_row('analyst@organization.com', '10-10 20:12') + '</ul></section>'
         + '</div>', h=900)


# --- 4: attach a file (Inspector > Files) ----------------------------------------------------------------
def inspector_body(base_name, name, extra_after_rows, h=None):
    d = load(base_name)
    html = d['html']
    marker = '</div></div></div><div class="xc-inspector-foot">'
    assert marker in html
    html = html.replace(marker, '</div>' + extra_after_rows + '</div></div><div class="xc-inspector-foot">', 1)
    out[name] = {'name': name, 'w': d['w'], 'h': h or d['h'], 'html': html, 'canvases': d.get('canvases', []), 'base': base_name}


inspector_body('inspector-files', 'planned-attach',
               '<section style="margin-top: 16px;"><p class="xc-eyebrow xc-eyebrow--dim xc-section-title">Attach a file</p>'
               + banner('Needs an upload route, proposed as <code>POST /api/memory/{id}/attachments</code> (scope <code>memory:write</code>). The store takes a path on the server’s disk today, which a browser cannot supply.')
               + '<div class="xc-form" style="margin-top: 10px;">'
               + field('File', '<input class="xc-input" type="file" style="">')
               + '<p class="xc-note">Stored once by content hash, so attaching the same bytes again adds no copy. Up to 200 MB. The memory’s own text should describe the file; its contents are not searchable.</p>'
               + '<dl class="xc-kv"><div><dt>Media type</dt><dd>detected from the file</dd></div><div><dt>Content hash</dt><dd>shown after upload</dd></div></dl>'
               + '<div class="xc-actions-row"><button type="button" class="xc-btn xc-btn--primary" disabled="">Attach file</button></div></div></section>')


# --- 5: back up (Operations) ----------------------------------------------------------------------------
def ops_card(base_name, name, card, h=None):
    d = load(base_name)
    marker = '<section class="xc-win xc-opscard" aria-label="Readiness">'
    assert marker in d['html']
    html = d['html'].replace(marker, card + marker, 1)
    out[name] = {'name': name, 'w': d['w'], 'h': h or d['h'], 'html': html, 'canvases': d.get('canvases', []), 'base': base_name}


ops_card('operations', 'planned-backup',
         '<section class="xc-win xc-opscard" aria-label="Backup"><p class="xc-eyebrow">Backup</p>'
         + banner('Needs <code>POST /api/backup</code> and <code>POST /api/backup/reconcile</code> (full-scope operators). The destination is a directory set in the server’s configuration; the browser never supplies or sees a path.')
         + '<p class="xc-note">An online copy of the store using SQLite’s own backup, then checked: the copy’s integrity check, and a comparison of the live store with the copy for memories, entities and relations.</p>'
         + '<dl class="xc-kv"><div><dt>Destination</dt><dd>configured on the server</dd></div><div><dt>Last backup</dt><dd>none recorded</dd></div></dl>'
         + '<div class="xc-actions-row"><button type="button" class="xc-btn xc-btn--primary">Create backup</button><button type="button" class="xc-btn" disabled="">Check live store against latest</button></div>'
         + callout('anchored', 'Backup checked',
                   'Integrity check ok · schema v16. Live store and copy match for memories, entities and relations at this moment. This shows the copy is complete, not that it will restore on another machine.')
         + '</section>', h=1560)


# --- 6: anchor a session root (Integrity > Sessions) ------------------------------------------------------
def integrity_card_extra(base_name, name, extra, h=None):
    d = load(base_name)
    marker = '<div class="xc-actions-row"><button type="button" class="xc-btn">Verify again</button></div></li>'
    assert marker in d['html']
    new = extra + '<div class="xc-actions-row"><button type="button" class="xc-btn">Verify again</button><button type="button" class="xc-btn" aria-expanded="true">Anchor root…</button></div></li>'
    out[name] = {'name': name, 'w': d['w'], 'h': h or d['h'], 'html': d['html'].replace(marker, new, 1), 'canvases': d.get('canvases', []), 'base': base_name}


integrity_card_extra('integrity', 'planned-anchor',
                     banner('Needs <code>POST /api/session/{id}/anchor</code> (scope <code>memory:write</code>, CSRF-checked, confirmed in the UI). The store method exists; the anchor URL and token come from server configuration, never from the browser.')
                     + '<div class="xc-callout xc-callout--conflict" role="alert">' + WARN
                     + '<div style="min-width: 0px;"><b>Send this session’s root to the anchor service?</b>'
                       '<div class="xc-note" style="margin-top: 4px;">Sends the session id, root hash, exchange count and root kind (and your agent id, for the Integrity CORE endpoint) to the anchor service this profile is configured with. No memory content is sent. It cannot be withdrawn.</div>'
                       '<div class="xc-actions-row" style="margin-top: 10px;"><button type="button" class="xc-btn">Cancel</button><button type="button" class="xc-btn xc-btn--danger">Anchor this root</button></div></div></div>'
                     + callout('review', 'Anchoring is not set up on this profile', 'The server has no anchor service configured. This is the state shown when it is missing, and the button above is then disabled. The server also refuses when the oracle confirms the agent is not registered, and says so.'),
                     h=1100)


# --- 7: verify an integrity link (Integrity > Links) -------------------------------------------------------
def drawer_body(base_name, name, extra, h=None):
    d = load(base_name)
    marker = '</div></div></aside></div>'
    assert marker in d['html']
    html = d['html'].replace(marker, extra + marker, 1)
    out[name] = {'name': name, 'w': d['w'], 'h': h or d['h'], 'html': html, 'canvases': d.get('canvases', []), 'base': base_name}


drawer_body('integrity-links', 'planned-link-verify',
            '<section style="margin-top: 18px;"><p class="xc-eyebrow xc-eyebrow--dim xc-section-title">Verify a memory’s link</p>'
            + banner('Needs <code>POST /api/memory/{id}/verify-link</code> (scope <code>memory:write</code>: it records the result). The Integrity DAG location is the server’s own setting, not a field here.')
            + '<div class="xc-form" style="margin-top: 10px;">'
            + field('Memory', '<input class="xc-input xc-input--mono" type="text" placeholder="memory id" value="" style="">')
            + field('DAG node <span class="xc-note">optional; the linked node is used when blank</span>', '<input class="xc-input xc-input--mono" type="text" value="" style="">')
            + '<div class="xc-actions-row"><button type="button" class="xc-btn xc-btn--primary">Verify</button></div>'
            + callout('anchored', 'Hash match, local',
                      'The DAG node’s content hash matches this memory’s current content. This is byte lineage only: it does not show the content is true, authorized, complete, or anchored on-chain.')
            + '<p class="xc-note">Other results: <b>verification failed</b> (the hashes differ), <b>content unavailable</b> (the node was not found), <b>unlinked</b> (the memory cites no node).</p>'
            + '</div></section>', h=1100)


# --- 8: vault lookup (Settings > Developer) ---------------------------------------------------------------
def dev_card(base_name, name, card, h=None):
    d = load(base_name)
    marker = '<section class="xc-win xc-opscard xc-form" aria-label="Kernel bridge self-test">'
    assert marker in d['html']
    out[name] = {'name': name, 'w': d['w'], 'h': h or d['h'], 'html': d['html'].replace(marker, card + marker, 1), 'canvases': d.get('canvases', []), 'base': base_name}


dev_card('settings-developer', 'planned-vault',
         '<section class="xc-win xc-opscard xc-form" aria-label="Trust vault lookup"><p class="xc-eyebrow">Trust vault lookup</p>'
         + banner('Needs <code>GET /api/vault/leaf?leaf_hash=</code> (read scope). The vault directory is a server setting (<code>INTEGRITY_VAULT_HOME</code>); the browser sends only the hash.')
         + '<p class="xc-note">Looks up a commit or test-result leaf in the Integrity vault and checks whether an anchor covers it. It does not verify memories: a memory’s content hash has no leaf here.</p>'
         + field('Leaf hash', '<input class="xc-input xc-input--mono" type="text" placeholder="0x…" value="" style="">')
         + '<div class="xc-actions-row"><button type="button" class="xc-btn xc-btn--primary">Look up</button></div>'
         + callout('anchored', 'Found, and an anchor covers it',
                   'The leaf’s hash was recomputed from its stored fields and matches. Not found and “could not read the vault” are reported as different things.')
         + '</section>', h=1180)



# =====================================================================================================
# Round 5: backend components with no UI. Every one hangs off the graph, the timeline, or a drawer opened
# from them; none is a new top-level destination.
# =====================================================================================================
def tag(text, tone=''):
    cls = f'xc-tag xc-tag--{tone}' if tone else 'xc-tag'
    return f'<span class="{cls}"><i></i>{text}</span>'


def card(label, eyebrow, body):
    return f'<section class="xc-win xc-opscard" aria-label="{label}"><p class="xc-eyebrow">{eyebrow}</p>{body}</section>'


def kv(rows):
    return '<dl class="xc-kv">' + ''.join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in rows) + '</dl>'


def listrows(rows):
    return '<ul class="xc-list">' + ''.join(f'<li class="xc-listrow"><span>{a}</span><span class="xc-meta">{b}</span></li>' for a, b in rows) + '</ul>'


# --- 9: the agent runtime, on the timeline ----------------------------------------------------------------
d = load('timeline-session-selected')
html = d['html']
# a runtime tag on the selected lane, and a Runtime section at the top of the session inspector
html = html.replace('<span>5 exchanges · open</span></button>', '<span>5 exchanges · open · <b style="color: var(--accent);">claude-code</b></span></button>', 1)
runtime_section = ('<section>' + banner('The runtime controller lives in the MCP server process, so the HTTP API cannot see it. Needs <code>GET /api/session/{id}/runtime</code>, answered from the runtime events the store already records for the session. The lane tag is the same value.')
    + '<p class="xc-eyebrow xc-eyebrow--dim xc-section-title" style="margin-top: 12px;">Runtime</p>'
    + kv([('Adapter', 'claude-code'), ('Opened by', 'harness hook'), ('Identity', 'pseudonym:9e51…'),
          ('Allowed', '41'), ('Asked', '1'), ('Denied', '2'), ('Last hook', 'post-tool · 03:41')])
    + '<p class="xc-note">Deny and ask decisions are marks on this session’s lane, so a blocked tool call is visible where it happened in time. Allow decisions are counted, not drawn.</p></section>')
html = html.replace('<div class="xc-inspector-body">', '<div class="xc-inspector-body">' + runtime_section, 1)
out['planned-runtime-timeline'] = {'name': 'planned-runtime-timeline', 'w': d['w'], 'h': 1100, 'html': html, 'canvases': d.get('canvases', []), 'base': 'timeline-session-selected'}

# --- 10-12: Operations cards -------------------------------------------------------------------------------
ops_card('operations', 'planned-runtimes',
    card('Agent runtimes', 'Agent runtimes',
         banner('Needs <code>GET /api/runtimes</code>: the adapters the runtime controller has seen, with counts read from the runtime events in the store. The 27 <code>runtime_*</code> tools stay a harness protocol; this is a read-only view.')
         + listrows([(tag('claude-code', 'anchored') + ' <b>Claude Code</b>', '2 open · 14 total · deny 2'), (tag('codex', 'anchored') + ' <b>Codex</b>', '0 open · 3 total'),
                     (tag('agy', 'anchored') + ' <b>Agy</b>', '0 open · 1 total'), (tag('gemini') + ' <b>Gemini</b>', 'no sessions'),
                     (tag('cursor') + ' <b>Cursor</b>', 'no sessions'), (tag('openai-compatible') + ' <b>OpenAI-compatible</b>', 'no sessions')])
         + '<p class="xc-note">Choosing a row opens the Timeline with that runtime’s sessions windowed, so it leads back to the lens.</p>'), h=1700)

ops_card('operations', 'planned-workers',
    card('Workers', 'Workers',
         banner('Needs <code>GET /api/workers</code> and a heartbeat row each worker writes when it claims, finishes or idles. Today the console shows only the queues the workers drain.')
         + listrows([('<b>Embedding</b> ' + tag('idle', 'anchored'), 'last run 03:12 · 69 memories missing · 0 failed'),
                     ('<b>PARA</b> ' + tag('running', 'anchored'), 'claimed 03:44 · 1 pending'),
                     ('<b>Contradiction</b> ' + tag('idle', 'anchored'), 'last run 02:58 · 0 pending'),
                     ('<b>Extraction (Hermes)</b> ' + tag('not seen', 'review'), 'no heartbeat in 6 h · 105 tasks pending')])
         + callout('review', 'A worker that has not been seen is not the same as a worker that is idle', 'Not seen is shown in the review colour with the time since its last heartbeat, and the queue it drains is listed beside it.')), h=1700)

ops_card('operations', 'planned-connectors',
    card('Connectors and ingest', 'Connectors and ingest',
         banner('Needs <code>GET /api/connectors</code>: counts by connector source from the memories the ingest tools wrote, and the OTLP receiver’s own counters. Ingest stays a machine protocol; this view only reports it.')
         + listrows([('<b>imported_document</b>', '5 memories · last 10-09 21:40'), ('<b>agent turns</b>', '35 memories · last 10-11 03:44'),
                     ('<b>OTLP receiver</b>', 'accepted 1,204 · rejected 3 · last 03:44')])
         + '<p class="xc-note">“Show in Graph” sets the Memory source facet to the connector, so the memories it wrote light up on the lens.</p>'
         + '<div class="xc-actions-row"><button type="button" class="xc-btn">Show in Graph</button><button type="button" class="xc-btn">Show in Timeline</button></div>'), h=1700)

# --- 13: API tokens (Settings > Account) ---------------------------------------------------------------------
d = load('settings-account-signed-in')
marker = '<form class="xc-win xc-opscard xc-form" aria-label="Change password"'
assert marker in d['html']
tokens = card('API tokens', 'API tokens',
    banner('Tokens are issued today with the <code>xibalba-cortex-ingest-tokens</code> command. Needs <code>GET /api/auth/tokens</code>, <code>POST /api/auth/tokens</code> and <code>POST /api/auth/tokens/revoke</code> (full-scope operators, CSRF-checked).')
    + listrows([('<b>otlp-receiver</b> ' + tag('ingest'), 'created 10-06 · last used 03:44'), ('<b>hermes-worker</b> ' + tag('worker'), 'created 10-06 · last used 02:58'),
                ('<b>viewer-local-dev</b> ' + tag('operator'), 'created 10-06 · last used 03:49')])
    + '<form class="xc-form" aria-label="Issue a token">'
    + field('Label', '<input class="xc-input" type="text" placeholder="what this token is for" value="" style="">')
    + field('Role', '<select class="xc-input"><option>ingest — write telemetry and turns</option><option>worker — claim and complete tasks</option><option>operator — everything this console does</option></select>')
    + '<div class="xc-actions-row"><button type="button" class="xc-btn xc-btn--primary">Issue token</button></div></form>'
    + callout('review', 'Copy this token now', 'It is shown once and never again; the server keeps only a hash. Revoking a token ends it at once, and the list above shows when it was last used so an unused one is easy to retire.'))
out['planned-tokens'] = {'name': 'planned-tokens', 'w': d['w'], 'h': 1900, 'html': d['html'].replace(marker, tokens + marker, 1), 'canvases': d.get('canvases', []), 'base': 'settings-account-signed-in'}

# --- 14: the profile's configuration (Settings > Profile) ---------------------------------------------------
d = load('settings-embeddings')
html = d['html']
html = re.sub(r'(<button[^>]*role="tab"[^>]*id="st-developer"[^>]*>)', '<button type="button" role="tab" id="st-profile" class="xc-tab" aria-selected="true">Profile</button>' + r'\1', html, count=1)
html = re.sub(r'(<button[^>]*role="tab"[^>]*id="st-embeddings"[^>]*?)aria-selected="true"', r'\1aria-selected="false"', html, count=1)
panel = ('<div class="xc-form xc-settings-form">' + banner('Needs <code>GET /api/profile/config</code>, redacted: no paths, no tokens, no URLs with credentials. Read-only on purpose; see below.')
    + card('Profile', 'Profile', kv([('Mode', 'local'), ('Identity mode', 'pseudonymous'), ('Retention tier', 'verbatim'), ('Profile id', 'default'),
                                     ('Schema', 'v16'), ('Quota · max memories', 'unlimited')]))
    + card('Connections', 'Connections', kv([('Integrity oracle', 'configured · not reachable'), ('Anchor service', 'not configured'), ('Auto-anchor on session end', 'off')]))
    + callout('review', 'This page does not change configuration', 'Mode, identity and retention are set in <code>config.yaml</code> or the environment and take effect on restart. Letting a browser rewrite them would let one tab change what every agent is allowed to remember. The page says where each value comes from.')
    + '</div>')
html = re.sub(r'(<section id="st-panel"[^>]*>).*?(</section></section></div></aside>)', lambda m: m.group(1) + panel + m.group(2), html, count=1, flags=re.S)
out['planned-profile'] = {'name': 'planned-profile', 'w': d['w'], 'h': 1200, 'html': html, 'canvases': d.get('canvases', []), 'base': 'settings-embeddings'}

# --- 15: export what the timeline is showing -------------------------------------------------------------------
d = load('timeline-window')
dialog = ('<div class="xc-scrim" aria-hidden="true"></div><div class="xc-overlay"><div class="xc-win xc-palette" role="dialog" aria-modal="true" aria-label="Export this window" style="max-width: 640px; align-self: flex-start; margin-top: 140px;">'
    '<div class="xc-drawer-head"><div><p class="xc-eyebrow">Export</p><h2 class="xc-drawer-title">This window</h2><p class="xc-note">7 days · 61 memories · 8 sessions</p></div></div>'
    '<div class="xc-drawer-body">' + banner('Needs <code>POST /api/provenance/export</code> taking the time window and the current facets, returning one bundle. Only the per-memory export exists today.')
    + kv([('Window', '10-04 → 10-11'), ('Scope', 'Primary profile · read only'), ('Includes', 'memories, chain events, session roots'), ('Format', 'JSON bundle')])
    + '<p class="xc-note">The bundle is the server’s own document, the same one the Inspector’s export downloads for a single memory, repeated for every memory shown. Facets that hide memories hide them here too, and the bundle says so in its header.</p>'
    + '<div class="xc-actions-row"><button type="button" class="xc-btn">Cancel</button><button type="button" class="xc-btn xc-btn--primary">Download bundle</button></div></div></div></div>')
html = d['html'].rstrip()
assert html.endswith('</div>')
html = html[:-6] + dialog + '</div>'
out['planned-export-window'] = {'name': 'planned-export-window', 'w': d['w'], 'h': d['h'], 'html': html, 'canvases': d.get('canvases', []), 'base': 'timeline-window'}

# --- 16: end a session (Sessions drawer) -------------------------------------------------------------------------
d = load('sessions')
marker = '<button type="button" class="xc-btn">Build from telemetry</button>'
if marker not in d['html']:
    m = re.search(r'<button[^>]*>Build from telemetry</button>', d['html']); marker = m.group(0)
end = ('<button type="button" class="xc-btn" aria-expanded="true">End session…</button></div>'
       + banner('Needs <code>POST /api/session/{id}/end</code> (scope <code>memory:write</code>, CSRF-checked). Starting a session stays implicit: it begins with its first exchange.')
       + '<div class="xc-callout xc-callout--conflict" role="alert">' + WARN + '<div style="min-width: 0px;"><b>End sess-w1?</b><div class="xc-note" style="margin-top: 4px;">Marks the session closed and fixes its Merkle root over the five exchanges recorded so far. An agent can no longer append to it; a new session starts if it comes back. This cannot be undone.</div>'
         '<div class="xc-actions-row" style="margin-top: 10px;"><button type="button" class="xc-btn">Cancel</button><button type="button" class="xc-btn xc-btn--danger">End this session</button></div></div></div><div style="display:none">')
out['planned-end-session'] = {'name': 'planned-end-session', 'w': d['w'], 'h': d['h'], 'html': d['html'].replace(marker, marker + end, 1), 'canvases': d.get('canvases', []), 'base': 'sessions'}

# --- 17: import (Memories drawer) ----------------------------------------------------------------------------------
d = load('memories-new')
form_pat = r'<form class="xc-win xc-newmemory"[^>]*aria-label="New memory">.*?</form>'
imp = ('<form class="xc-win xc-newmemory" aria-label="Import">' + '<p class="xc-eyebrow">Import</p>'
    + banner('Needs <code>POST /api/import</code> (multipart, scope <code>memory:write</code>). Today the wiki, transcript and raw importers are commands that read a path on the server’s disk, which a browser cannot supply.')
    + field('Source', '<select class="xc-input"><option>Document or wiki page</option><option>Agent transcript</option><option>Raw text</option></select>')
    + field('File', '<input class="xc-input" type="file" style="">')
    + '<p class="xc-note">Each import becomes memories with source <b>imported document</b> and evidence class <b>extracted proposition</b>, so they are easy to find with the Memory source facet and to dismiss as a group. Entities and relations found in them arrive as proposals in Review; nothing is written to the graph without a decision.</p>'
    + '<dl class="xc-kv"><div><dt>Limit</dt><dd>200 MB per file</dd></div><div><dt>Duplicates</dt><dd>skipped by content hash</dd></div></dl>'
    + '<div class="xc-actions-row"><button type="button" class="xc-btn">Cancel</button><button type="button" class="xc-btn xc-btn--primary" disabled="">Import</button></div></form>')
html2 = re.sub(form_pat, lambda m: imp, d['html'], count=1, flags=re.S)
assert html2 != d['html']
out['planned-import'] = {'name': 'planned-import', 'w': d['w'], 'h': d['h'], 'html': html2, 'canvases': d.get('canvases', []), 'base': 'memories-new'}

for name, board in out.items():
    (S / 'boards-src' / f'{name}.json').write_text(json.dumps(board))
    print('planned', name, board['w'], board['h'])
