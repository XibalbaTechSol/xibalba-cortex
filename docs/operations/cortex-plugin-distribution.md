# Cortex plugin distribution (0.1.0 pilot)

Cortex has three source-controlled native packages and two hosted connector
setup templates. They share the installed Cortex backend; none embeds credentials
or installs backend dependencies during a hook callback.

| Surface | Package | Visibility and capture |
| --- | --- | --- |
| Claude Code | `plugins/cortex-claude` | Xibalba Claude marketplace; MCP memory plus native observation hooks |
| Codex local clients | `plugins/cortex-codex` | Xibalba Codex marketplace; MCP memory plus reviewed/trusted native hooks |
| Gemini CLI | `plugins/cortex-gemini`, root `gemini-extension.json` | Git extension install; MCP memory, no full native observer |
| Gemini personal assistant / Spark | `integrations/spark/connector-template.json` | Custom Connected App setup via HTTPS MCP and OAuth |
| Perplexity consumer | `integrations/perplexity/connector-template.json` | Custom remote connector setup via HTTPS MCP |

Spark and Perplexity templates are operator setup references, not manifests that
can be imported into an undocumented app store. Replace `YOUR-CORTEX-HOST` with the
deployed endpoint and follow `hosted-memory-connectors.md`. The Perplexity API
runtime launcher is documented separately in `perplexity-runtime-recorder.md`.

## Local backend prerequisite

Install Cortex from the documented sibling integrity-core layout using `uv sync
--extra otel`. Put that environment's `bin` directory on the application's PATH;
`xibalba-cortex`, `xibalba-cortex-observer` and `python3` must be available when the
host launches the plugin. Set `XIBALBA_CORTEX_HOME` to an explicit profile directory
in the host application's environment. Metadata capture is default. Optional
`XIBALBA_CORTEX_CAPTURE_MODE=redacted` explicitly enables bounded redacted hook
content; do not enable it implicitly. The backend remains a pilot source installation,
not a claimed standalone `pip install` product. Linux/POSIX hook commands are tested;
Windows/native desktop installation needs a separate canary.

## Install from the repository

The commands below select the published pilot branch until it is merged/released.

Claude Code:

```bash
git clone --branch feat/cortex-runtime-and-plugins https://github.com/XibalbaTechSol/xibalba-cortex.git
claude plugin marketplace add ./xibalba-cortex
claude plugin install cortex-claude@xibalba-cortex
```

Codex:

```bash
codex plugin marketplace add XibalbaTechSol/xibalba-cortex --ref feat/cortex-runtime-and-plugins
```

Open the supported local client's Plugins directory, select **Xibalba Cortex** and
install **cortex-codex**. Review/trust the hooks through `/hooks` before expecting
callbacks. Installation does not bypass Codex hook trust or administrator policies.
This local stdio package cannot run on hosted ChatGPT surfaces. A hosted ChatGPT
plugin requires a deployed OAuth MCP endpoint and registered plugin mapping, then
public/workspace submission; no fake endpoint or registration ID is included here.

Gemini CLI:

```bash
gemini extensions install https://github.com/XibalbaTechSol/xibalba-cortex --ref feat/cortex-runtime-and-plugins
```

The root extension manifest makes the monorepo directly installable. Enter the
Cortex profile path when prompted for **Cortex home**. The extension explicitly
declares its setting so Gemini's environment filtering does not drop it.

## Verify real functionality

Invoke `/cortex-claude:cortex-connect` or the Codex `cortex-connect` skill. Verify
an actual `memory_status` tool call. For Gemini, ask it to invoke `memory_status`.
A settings card or manifest check does not prove an MCP server is reachable.
Claude/Codex hooks enqueue locally; run a managed drain process:

```bash
xibalba-cortex-observer drain --home /path/to/cortex-profile --watch
```

Restart the host, submit a benign prompt/tool and inspect
`xibalba-cortex-observer status --home /path/to/cortex-profile`. The packaged bridge's
`doctor` command checks executables/configuration but intentionally does not claim
live callback delivery. Do not enable both these bundled hooks and equivalent
observer-install hooks for the same profile: they would create duplicate occurrences.
Choose one installation route; uninstall that route before switching.

To disable recording, disable the plugin's hooks through the host; stop the drain
worker separately. Uninstall using the host's plugin/extension manager. Local
recordings remain until deliberately removed. Existing unrelated hooks/settings
are not modified by these packages.

## Build, validate and publish

`python scripts/build_cortex_plugins.py --archives /tmp/cortex-plugins` regenerates
manifests/launchers and builds deterministic ZIPs with SHA256SUMS. Gemini archives
have `gemini-extension.json` at their root. Claude/Codex archives retain their
native/portable root layouts. CI publishes archives as workflow artifacts; it does
not silently create a public release or submit to a provider directory.

Local tests run the bundled hook bridge against actual Cortex executables and
SQLite persistence, validate catalog paths, verify self-contained/reproducible
archives and validate bundled skill frontmatter. Native Claude/Codex/Gemini binaries
were unavailable in this workspace, so native install/trust/menu visibility remains
a live canary. Validate with `claude plugin validate`, the target Codex client and
`gemini extensions list` on supported pilot machines before advertising production
one-click installation.

Repository publication makes packages available through our catalog/Git refs.
Official directory visibility needs separate submission/review. Gemini gallery
indexing is a platform process; a source commit or PR is not proof of listing.
No official marketplace approval or live listing is claimed.

Official distribution contracts:
- https://code.claude.com/docs/en/plugin-marketplaces
- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/deploy/submission
- https://geminicli.com/docs/extensions/writing-extensions/
- https://geminicli.com/docs/extensions/releasing/
