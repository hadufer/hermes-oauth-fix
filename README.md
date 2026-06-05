# Hermes Anthropic OAuth Fix

A patch that keeps `hermes-agent` working on the Anthropic OAuth (Claude Code subscription) path.

Without it, every request comes back as HTTP 400 with the message *"You're out of extra usage. Add more at claude.ai/settings/usage and keep going"*, even when your quota is fine. The message is misleading. What's actually happening is Anthropic silently rejecting non-official clients on that auth path. The patch reshapes outgoing requests so they look like traffic from the real Claude Code CLI, and reverses the disguise on the way back so Hermes' tool dispatcher still routes correctly.

## Use at your own risk

Read this before installing.

The patch makes Hermes' requests look like they come from the real Claude Code CLI. Anthropic doesn't want third-party agents on the OAuth subscription path, and running Hermes through it puts you in violation of their Terms of Service.

Concretely: Anthropic can suspend your account or revoke your OAuth token whenever they want, without telling you why. Their detector can update on a Tuesday and break the patch by Wednesday. They've also been known to spot accounts using this kind of trick and ban them in batches. Similar projects have already been on the receiving end of all three.

The patch is not a security exploit. You're using your own credentials to call their API, you're just changing what the request looks like on the wire. No authentication is being defeated. Nothing is being accessed that the account wasn't already paying for. And to be clear: this repo isn't endorsed by Anthropic, NousResearch, or anyone official.

If you have a regular `sk-ant-...` API key, use that. The OAuth path is the only one Anthropic polices. Pay-per-token costs more, but you can drop the patch entirely and stop worrying about any of this.

This repo is for people who already pay for a Claude Code subscription and want to use it through their own setup, and for anyone curious about how that kind of detection actually works. If neither of those is you, the regular API key is the simpler path.

## What it changes

Two files, `agent/anthropic_adapter.py` and `agent/transports/anthropic.py`. The actual changes:

- Outbound tool names get renamed. Hermes' `read_file` / `terminal` / `skill_manage` go out as `Read` / `Bash` / `mcp__playwright__browser_click` / `mcp__h__skill_manage`. The originals come back on the way in so the dispatcher still works.
- The system prompt loses its most distinctive Hermes signatures: the `<available_skills>` XML block, the `Host:` / `Shell:` / `Conversation started:` blocks, the `# Claude Code Persona` header, NousResearch URLs, the word "Hermes", the WSL environment hint, `hermes` CLI references, and the "You are X" platform intros. Functional guidance stays put (memory tool, skill loading, MEDIA tags, persona).
- The `<available_skills>` catalog gets re-emitted as flat markdown. Every skill name and description survives, in a format that no longer matches what the detector is looking for.
- The `# Nous Subscription` capability block (added when web/browser tools are loaded) and the `# Kanban task execution protocol` block (added when kanban tools are loaded) get stripped entirely — both leak product names that survive the per-word rewrites.
- Lowercase path/env-var leaks get rewritten: `~/.hermes/` → `~/.claude/`, `$HERMES_*` → `$CLAUDE_*`, `.hermes.md` → `.claude.md`, `HERMES.md` → `CLAUDE.md`, `HERMES_HOME` → `CLAUDE_HOME`. Inline `hermes <cmd>` references (setup, status, config, tools, kanban, etc.) get rewritten to `claude <cmd>`.
- Tool calls coming back from Anthropic go through the rename in reverse before Hermes' dispatcher fires.

The model still sees the same tools and the same instructions, so nothing functional breaks.

## Requirements

- Python 3.10+
- An existing `hermes-agent` install
- An Anthropic OAuth (Claude Code subscription) token configured in Hermes

If you use a regular `sk-ant-...` API key, you don't need this patch. That path isn't policed.

## Where Hermes lives, per platform

### Linux

Usually `~/.hermes/hermes-agent/`. To search:
```bash
find ~ -maxdepth 5 -type d -name hermes-agent 2>/dev/null
```

### macOS

Usually `~/.hermes/hermes-agent/`. If installed via Homebrew, also check `$(brew --prefix)/share/hermes-agent/`:
```bash
find ~ /opt/homebrew /usr/local -maxdepth 6 -type d -name hermes-agent 2>/dev/null
```

### Windows (native, no WSL)

```
C:\Users\<your-username>\AppData\Local\hermes\hermes-agent\
```
From Git Bash:
```bash
ls "/c/Users/$USER/AppData/Local/hermes/hermes-agent/agent/"
```
From PowerShell:
```powershell
ls "$env:LOCALAPPDATA\hermes\hermes-agent\agent\"
```

### WSL

Inside the WSL home: `~/.hermes/hermes-agent/`. The patch already handles the WSL-specific prompt block, so the install is the same as for Linux.

If your WSL Hermes runs against the Windows install instead:
```bash
ls "/mnt/c/Users/<windows-username>/AppData/Local/hermes/hermes-agent/agent/"
```

## Applying the patch

```bash
python3 install.py
```

The installer finds your Hermes install, applies the patches (idempotently), validates the result with `py_compile`, clears the stale bytecode, and writes `.oauth-fix.bak` backups next to the originals.

Flags:
```bash
python3 install.py --check                      # report state, don't modify
python3 install.py --uninstall                  # restore originals from backups
python3 install.py /custom/path/to/hermes-agent # explicit path
```

Discovery order:

1. `$HERMES_HOME` if set
2. `~/.hermes/hermes-agent` (Linux, macOS, WSL)
3. `~/AppData/Local/hermes/hermes-agent` (Windows)
4. `~/Library/Application Support/hermes/hermes-agent` (macOS alternative)
5. `/opt/hermes/hermes-agent`, `/usr/local/share/hermes-agent`, `/opt/homebrew/share/hermes-agent`

Pass the path explicitly if yours isn't on that list.

One thing to remember: if `hermes` is already running, restart it. Python only re-imports modules at startup, so an in-flight session keeps the old code in memory.

## Verifying

Start a chat session:

```bash
hermes chat --provider anthropic
```

Then send any message inside the session. Before the patch the first message comes back as HTTP 400 with the usage message. After, you get a normal reply, and tool calls, memory, skill loading, and MEDIA file delivery all keep working.

## Reverting

```bash
python3 install.py --uninstall
```

This restores both files from the `.oauth-fix.bak` backups. The patch never touches any other file, so the uninstall is complete.

## Diagnosing new leaks (when Hermes updates)

Hermes evolves. New prompt blocks, new env vars, new commands — anything that still says "Hermes" or "Nous" on the wire can re-trigger the detector. To see what's actually being sent to Anthropic after the patch runs, set `HERMES_OAUTH_FIX_DUMP_DIR` to a writable directory:

```powershell
# PowerShell
$env:HERMES_OAUTH_FIX_DUMP_DIR = "$env:USERPROFILE\Desktop\oauth-dump"
hermes chat --provider anthropic
```

```bash
# Linux / macOS / WSL
export HERMES_OAUTH_FIX_DUMP_DIR=~/oauth-dump
hermes chat --provider anthropic
```

Each outbound request writes a `oauth-<pid>-<ms-timestamp>-<rand>.json` file (the pid and random suffix keep concurrent requests from overwriting each other) containing the post-sanitization `model`, `system` blocks, `tools`, and `messages` — exactly what gets serialized into the Anthropic Messages API call. Grep the dump for `Hermes`, `Nous`, `hermes`, or any other product-name fragments; whatever you find there is what's still leaking. Add the corresponding strip/rewrite to `ADAPTER_OAUTH_PATCHED` in `install.py` and re-run `python install.py` (it's idempotent — it'll restore the backup, then re-patch with the updated rules).

Unset the env var (or delete the dump dir) when you're done — every request writes a new file.

## Known limitations

Tested on Windows native with Sonnet 4.6 and Opus 4.7. Linux, macOS, and WSL strips are in place but haven't been validated against a live install on those platforms. If Anthropic reads a platform-specific signature that wasn't in our sample, you may need to extend the regex set.

Messaging adapters (Telegram, Discord, Slack, email, SMS, cron) and the browser WebUI surface have their "You are X" intros rewritten generically. The WebUI intro gets an explicit sentence rewrite because a bare `Hermes` → `Claude Code` swap would still leave the product-specific term "WebUI" on the wire. If you run Hermes through a surface whose intro isn't covered and the 400 comes back, capture the outgoing payload (see *Diagnosing new leaks* above) and see what's still in there.

The tool disguise maps Hermes' browser tools onto `mcp__playwright__*` and routes everything else through a fake `mcp__h__*` server. If you configure a *real* native MCP server named exactly `playwright` or `h`, its tool names collide with those disguise prefixes and the reverse-mapping would strip them on the way back, so the dispatcher wouldn't find them. Pick any other server name and the collision disappears. The `test_tool_mapping_bijection.py` check proves the round-trip is collision-free for every tool in your actual registry.

Future Hermes versions that change the prompt structure or add new top-level kwargs will probably need additional strips. The detector evolves, Hermes evolves, this patch will eventually need updating. When `python install.py` reports `original OAuth block not found (file may be from a different Hermes version)` or `original prefix/strip block not found`, the anchor strings in `install.py` (`ADAPTER_OAUTH_ORIGINAL`, `TRANSPORT_PREFIX_ORIGINAL`, `TRANSPORT_STRIP_ORIGINAL`) need to be re-synced against the current upstream code in `agent/anthropic_adapter.py` and `agent/transports/anthropic.py`.

`output_config` and `thinking.adaptive` are real Anthropic API features for Claude 4.6+. They stay in the request and are not signatures.

If you authenticate with `sk-ant-...` instead of OAuth, none of this applies.
