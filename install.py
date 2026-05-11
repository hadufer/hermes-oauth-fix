#!/usr/bin/env python3
"""Cross-platform installer for the Hermes Anthropic OAuth fix.

Discovers the hermes-agent install on Linux / macOS / Windows / WSL,
patches agent/anthropic_adapter.py and agent/transports/anthropic.py,
validates the result, and clears stale bytecode.

Usage:
    python install.py                  # apply
    python install.py --check          # report state, do not modify
    python install.py --uninstall      # restore originals from backups
    python install.py /path/to/hermes  # use an explicit hermes-agent root
"""

import argparse
import os
import py_compile
import shutil
import sys
from pathlib import Path


HOME = Path.home()

DISCOVERY_PATHS = [
    HOME / ".hermes" / "hermes-agent",
    HOME / "AppData" / "Local" / "hermes" / "hermes-agent",
    HOME / "Library" / "Application Support" / "hermes" / "hermes-agent",
    Path("/opt/hermes/hermes-agent"),
    Path("/usr/local/share/hermes-agent"),
    Path("/opt/homebrew/share/hermes-agent"),
]

ADAPTER_REL = Path("agent") / "anthropic_adapter.py"
TRANSPORT_REL = Path("agent") / "transports" / "anthropic.py"

BACKUP_SUFFIX = ".oauth-fix.bak"


ADAPTER_HELPERS_INSERT_AFTER = '_MCP_TOOL_PREFIX = "mcp_"'

ADAPTER_HELPERS_BLOCK = '''

_OAUTH_TOOL_BUILTIN: Dict[str, str] = {
    "read_file":     "Read",
    "write_file":    "Write",
    "terminal":      "Bash",
    "patch":         "Edit",
    "todo":          "TodoWrite",
    "delegate_task": "Task",
    "search_files":  "Grep",
}

_OAUTH_TOOL_PLAYWRIGHT: set = {
    "browser_back", "browser_click", "browser_console", "browser_get_images",
    "browser_navigate", "browser_press", "browser_scroll", "browser_snapshot",
    "browser_type", "browser_vision",
}

_OAUTH_TOOL_FAKE_SERVER_PREFIX = "mcp__h__"
_OAUTH_TOOL_PLAYWRIGHT_PREFIX = "mcp__playwright__"


def _oauth_rename_tool(name: str) -> str:
    if name in _OAUTH_TOOL_BUILTIN:
        return _OAUTH_TOOL_BUILTIN[name]
    if name in _OAUTH_TOOL_PLAYWRIGHT:
        return _OAUTH_TOOL_PLAYWRIGHT_PREFIX + name
    if name in _OAUTH_TOOL_BUILTIN.values():
        return name
    if name.startswith("mcp__"):
        return name
    return _OAUTH_TOOL_FAKE_SERVER_PREFIX + name


def _oauth_unrename_tool(name: str) -> str:
    for hermes_name, disguised in _OAUTH_TOOL_BUILTIN.items():
        if name == disguised:
            return hermes_name
    if name.startswith(_OAUTH_TOOL_PLAYWRIGHT_PREFIX):
        return name[len(_OAUTH_TOOL_PLAYWRIGHT_PREFIX):]
    if name.startswith(_OAUTH_TOOL_FAKE_SERVER_PREFIX):
        return name[len(_OAUTH_TOOL_FAKE_SERVER_PREFIX):]
    if name.startswith(_MCP_TOOL_PREFIX):
        return name[len(_MCP_TOOL_PREFIX):]
    return name


def _reformat_available_skills_block(text: str) -> str:
    import re as _re

    m = _re.search(
        r"<available_skills>\\n?([\\s\\S]*?)</available_skills>\\s*",
        text,
    )
    if not m:
        return text

    body = m.group(1)

    categories: list = []
    current = None
    for line in body.splitlines():
        if not line.strip():
            continue
        skill_m = _re.match(r"\\s{2,}-\\s+([A-Za-z0-9_./-]+):\\s*(.*)", line)
        if skill_m and current is not None:
            current[2].append((skill_m.group(1), skill_m.group(2).strip()))
            continue
        cat_m = _re.match(r"\\s{1,4}([A-Za-z0-9_./-]+):\\s*(.*)", line)
        if cat_m:
            current = (cat_m.group(1), cat_m.group(2).strip(), [])
            categories.append(current)
            continue
        if current is not None and current[1]:
            current = (current[0], current[1] + " " + line.strip(), current[2])
            categories[-1] = current

    if not categories:
        return text[: m.start()] + text[m.end():]

    chunks: list = ["## Specialized capability modules\\n"]
    chunks.append(
        "The agent can load any of the following on demand via "
        "`mcp__h__skill_view(name=<module-name>)`. Pick the module "
        "that best matches the task before answering.\\n"
    )
    for cat_name, cat_desc, skills in categories:
        chunks.append(f"\\n### {cat_name}")
        if cat_desc:
            chunks.append(f"\\n{cat_desc}\\n")
        else:
            chunks.append("\\n")
        for skill_name, skill_desc in skills:
            chunks.append(f"- `{skill_name}` — {skill_desc}\\n")

    new_block = "".join(chunks)
    return text[: m.start()] + new_block + text[m.end():]
'''


ADAPTER_OAUTH_ORIGINAL = '''        # 2. Sanitize system prompt — replace product name references
        #    to avoid Anthropic's server-side content filters.
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                text = text.replace("Hermes Agent", "Claude Code")
                text = text.replace("Hermes agent", "Claude Code")
                text = text.replace("hermes-agent", "claude-code")
                text = text.replace("Nous Research", "Anthropic")
                block["text"] = text

        # 3. Prefix tool names with mcp_ (Claude Code convention)
        if anthropic_tools:
            for tool in anthropic_tools:
                if "name" in tool:
                    tool["name"] = _MCP_TOOL_PREFIX + tool["name"]

        # 4. Prefix tool names in message history (tool_use and tool_result blocks)
        for msg in anthropic_messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use" and "name" in block:
                            if not block["name"].startswith(_MCP_TOOL_PREFIX):
                                block["name"] = _MCP_TOOL_PREFIX + block["name"]
                        elif block.get("type") == "tool_result" and "tool_use_id" in block:
                            pass  # tool_result uses ID, not name'''


ADAPTER_OAUTH_PATCHED = '''        import re as _re
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")

                text = text.replace("Hermes Agent", "Claude Code")
                text = text.replace("Hermes agent", "Claude Code")
                text = text.replace("hermes-agent", "claude-code")
                text = text.replace("Nous Research", "Anthropic")
                text = text.replace(
                    "claude-code.nousresearch.com",
                    "claude-code.anthropic.com",
                )

                text = _reformat_available_skills_block(text)

                text = _re.sub(
                    r"\\n?Host:\\s*[^\\n]*\\nUser home directory:[^\\n]*\\nCurrent working directory:[^\\n]*\\n(?:Note:[^\\n]*\\n)?",
                    "\\n",
                    text,
                )

                text = _re.sub(
                    r"\\n?Shell: on this [^\\n]+ host your `?terminal`? tool[\\s\\S]*?(?:POSIX equivalents[^\\n]*\\n|will NOT work[^\\n]*\\n)",
                    "\\n",
                    text,
                )

                text = _re.sub(
                    r"Conversation started:[^\\n]*\\nModel:[^\\n]*\\nProvider:[^\\n]*\\n?",
                    "",
                    text,
                )

                text = _re.sub(
                    r"<!--\\s*\\nThis file defines the agent's personality[\\s\\S]*?-->\\n?",
                    "",
                    text,
                )

                text = _re.sub(r"^#\\s+Claude Code Persona\\s*\\n+", "", text)

                text = _re.sub(
                    r"\\s*\\(e\\.g\\.\\s*`hermes [^`]*`(?:,\\s*`hermes [^`]*`)*\\)",
                    "",
                    text,
                )

                _HERMES_FN_RENAME = (
                    ("session_search", "mcp__h__session_search"),
                    ("skill_manage",   "mcp__h__skill_manage"),
                    ("skill_view",     "mcp__h__skill_view"),
                    ("skills_list",    "mcp__h__skills_list"),
                )
                for _old, _new in _HERMES_FN_RENAME:
                    text = _re.sub(rf"\\b{_old}\\b", _new, text)

                _PLATFORM_INTRO_REWRITES = [
                    ("You are a CLI AI Agent.",
                     "You write output that will be rendered in a terminal."),
                    ("You are on a text messaging communication platform, ",
                     "Your output is delivered through "),
                    ("You are in a Discord server or group chat communicating with your user.",
                     "Your output is delivered through Discord."),
                    ("You are in a Slack workspace communicating with your user.",
                     "Your output is delivered through Slack."),
                    ("You are communicating via email.",
                     "Your output is delivered as email."),
                    ("You are communicating via SMS.",
                     "Your output is delivered as SMS."),
                    ("You are running as a scheduled cron job.",
                     "This invocation is a scheduled non-interactive run."),
                ]
                for _old, _new in _PLATFORM_INTRO_REWRITES:
                    text = text.replace(_old, _new)

                text = _re.sub(
                    r"You are running inside WSL[\\s\\S]*?(?:if needed\\.|/mnt/c/Users/[^\\n]*\\n)",
                    "",
                    text,
                )

                text = _re.sub(r"\\bHermes\\b", "Claude Code", text)

                block["text"] = text

        system = [
            b for b in system
            if not (
                isinstance(b, dict)
                and b.get("type") == "text"
                and not (b.get("text") or "").strip()
            )
        ]

        if anthropic_tools:
            for tool in anthropic_tools:
                if "name" in tool:
                    tool["name"] = _oauth_rename_tool(tool["name"])

        for msg in anthropic_messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use" and "name" in block:
                            block["name"] = _oauth_rename_tool(block["name"])
                        elif block.get("type") == "tool_result" and "tool_use_id" in block:
                            pass'''


TRANSPORT_PREFIX_ORIGINAL = '''        strip_tool_prefix = kwargs.get("strip_tool_prefix", False)
        _MCP_PREFIX = "mcp_"'''

TRANSPORT_PREFIX_PATCHED = '''        strip_tool_prefix = kwargs.get("strip_tool_prefix", False)
        from agent.anthropic_adapter import _oauth_unrename_tool'''


TRANSPORT_STRIP_ORIGINAL = '''            elif block.type == "tool_use":
                name = block.name
                if strip_tool_prefix and name.startswith(_MCP_PREFIX):
                    name = name[len(_MCP_PREFIX):]'''

TRANSPORT_STRIP_PATCHED = '''            elif block.type == "tool_use":
                name = block.name
                if strip_tool_prefix:
                    name = _oauth_unrename_tool(name)'''


PATCHED_MARKER_ADAPTER = "_oauth_rename_tool"
PATCHED_MARKER_TRANSPORT = "_oauth_unrename_tool"


def discover_hermes(explicit: str = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if (p / ADAPTER_REL).exists():
            return p
        raise SystemExit(f"error: {p} does not look like a hermes-agent install ({ADAPTER_REL} missing)")

    env = os.environ.get("HERMES_HOME")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / ADAPTER_REL).exists():
            return p

    for candidate in DISCOVERY_PATHS:
        if (candidate / ADAPTER_REL).exists():
            return candidate.resolve()

    raise SystemExit(
        "error: could not locate a hermes-agent install. "
        "Pass the path explicitly: python install.py /path/to/hermes-agent"
    )


def is_patched(file_path: Path, marker: str) -> bool:
    return marker in file_path.read_text(encoding="utf-8")


def backup_once(file_path: Path) -> Path:
    backup = file_path.with_suffix(file_path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(file_path, backup)
    return backup


def restore_backup(file_path: Path) -> bool:
    backup = file_path.with_suffix(file_path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        return False
    shutil.copy2(backup, file_path)
    backup.unlink()
    return True


def patch_adapter(adapter_path: Path) -> str:
    content = adapter_path.read_text(encoding="utf-8")
    if PATCHED_MARKER_ADAPTER in content:
        return "already-patched"

    if ADAPTER_HELPERS_INSERT_AFTER not in content:
        return f"anchor not found: {ADAPTER_HELPERS_INSERT_AFTER!r}"
    if ADAPTER_OAUTH_ORIGINAL not in content:
        return "original OAuth block not found (file may be from a different Hermes version)"

    content = content.replace(
        ADAPTER_HELPERS_INSERT_AFTER,
        ADAPTER_HELPERS_INSERT_AFTER + ADAPTER_HELPERS_BLOCK,
        1,
    )
    content = content.replace(ADAPTER_OAUTH_ORIGINAL, ADAPTER_OAUTH_PATCHED, 1)

    backup_once(adapter_path)
    adapter_path.write_text(content, encoding="utf-8")
    return "patched"


def patch_transport(transport_path: Path) -> str:
    content = transport_path.read_text(encoding="utf-8")
    if PATCHED_MARKER_TRANSPORT in content:
        return "already-patched"

    if TRANSPORT_PREFIX_ORIGINAL not in content:
        return "original prefix block not found"
    if TRANSPORT_STRIP_ORIGINAL not in content:
        return "original strip block not found"

    content = content.replace(TRANSPORT_PREFIX_ORIGINAL, TRANSPORT_PREFIX_PATCHED, 1)
    content = content.replace(TRANSPORT_STRIP_ORIGINAL, TRANSPORT_STRIP_PATCHED, 1)

    backup_once(transport_path)
    transport_path.write_text(content, encoding="utf-8")
    return "patched"


def validate_syntax(file_path: Path) -> bool:
    try:
        py_compile.compile(str(file_path), doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  syntax error in {file_path}: {e}", file=sys.stderr)
        return False


def clear_pyc(hermes_root: Path) -> None:
    for cache_dir in [
        hermes_root / "agent" / "__pycache__",
        hermes_root / "agent" / "transports" / "__pycache__",
    ]:
        if not cache_dir.exists():
            continue
        for pyc in cache_dir.glob("anthropic*.pyc"):
            pyc.unlink()


def cmd_apply(hermes_root: Path) -> int:
    print(f"Hermes root: {hermes_root}")

    adapter = hermes_root / ADAPTER_REL
    transport = hermes_root / TRANSPORT_REL

    adapter_status = patch_adapter(adapter)
    print(f"  {ADAPTER_REL}: {adapter_status}")
    if adapter_status not in ("patched", "already-patched"):
        return 1

    transport_status = patch_transport(transport)
    print(f"  {TRANSPORT_REL}: {transport_status}")
    if transport_status not in ("patched", "already-patched"):
        restore_backup(adapter)
        return 1

    if not validate_syntax(adapter) or not validate_syntax(transport):
        print("syntax check failed; rolling back", file=sys.stderr)
        restore_backup(adapter)
        restore_backup(transport)
        return 1

    clear_pyc(hermes_root)
    print("done. Restart any running hermes process to pick up the patch.")
    return 0


def cmd_uninstall(hermes_root: Path) -> int:
    print(f"Hermes root: {hermes_root}")
    adapter = hermes_root / ADAPTER_REL
    transport = hermes_root / TRANSPORT_REL

    a = restore_backup(adapter)
    t = restore_backup(transport)
    print(f"  {ADAPTER_REL}: {'restored' if a else 'no backup found'}")
    print(f"  {TRANSPORT_REL}: {'restored' if t else 'no backup found'}")

    clear_pyc(hermes_root)
    return 0 if (a and t) else 1


def cmd_check(hermes_root: Path) -> int:
    print(f"Hermes root: {hermes_root}")
    adapter = hermes_root / ADAPTER_REL
    transport = hermes_root / TRANSPORT_REL

    a = is_patched(adapter, PATCHED_MARKER_ADAPTER)
    t = is_patched(transport, PATCHED_MARKER_TRANSPORT)
    print(f"  {ADAPTER_REL}: {'patched' if a else 'unpatched'}")
    print(f"  {TRANSPORT_REL}: {'patched' if t else 'unpatched'}")
    return 0 if (a and t) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Hermes Anthropic OAuth fix installer",
    )
    p.add_argument(
        "hermes_root",
        nargs="?",
        default=None,
        help="Path to hermes-agent root (auto-discovered if omitted)",
    )
    p.add_argument("--check", action="store_true", help="report state without modifying")
    p.add_argument("--uninstall", action="store_true", help="restore originals from backups")
    args = p.parse_args(argv)

    hermes_root = discover_hermes(args.hermes_root)

    if args.check:
        return cmd_check(hermes_root)
    if args.uninstall:
        return cmd_uninstall(hermes_root)
    return cmd_apply(hermes_root)


if __name__ == "__main__":
    sys.exit(main())
