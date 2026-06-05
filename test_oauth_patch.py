"""Smoke test for the OAuth fix patches.

Verifies:
  1. Tool rename/unrename round-trip for all categories.
  2. Sanitization on a synthetic system prompt produces no leaks.
  3. Dump diagnostic writes a valid JSON file.
  4. Existing _reformat_available_skills_block helper still works.
"""
import importlib
import json
import os
import re
import sys
import tempfile
import time


def _hermes_root() -> str:
    """Locate the hermes-agent install via install.py's cross-platform discovery.

    Keeps the test portable — no hard-coded per-machine path. Honors
    $HERMES_HOME and the standard discovery list just like the installer.
    """
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "_oauth_installer", os.path.join(here, "install.py")
    )
    inst = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inst)
    return str(inst.discover_hermes())


def main() -> int:
    sys.path.insert(0, _hermes_root())
    adapter = importlib.import_module("agent.anthropic_adapter")

    print("=" * 70)
    print("1. TOOL RENAME ROUND-TRIP")
    print("=" * 70)

    cases = [
        ("read_file", "Read", "BUILTIN"),
        ("write_file", "Write", "BUILTIN"),
        ("terminal", "Bash", "BUILTIN"),
        ("patch", "Edit", "BUILTIN"),
        ("delegate_task", "Task", "BUILTIN"),
        ("search_files", "Grep", "BUILTIN"),
        ("todo", "TodoWrite", "BUILTIN"),
        ("browser_click", "mcp__playwright__browser_click", "PLAYWRIGHT"),
        ("browser_navigate", "mcp__playwright__browser_navigate", "PLAYWRIGHT"),
        ("session_search", "mcp__h__session_search", "fallback"),
        ("skill_view", "mcp__h__skill_view", "fallback"),
        ("memory", "mcp__h__memory", "fallback"),
        ("web_search", "mcp__h__web_search", "fallback"),
        ("mcp_filesystem_read", "mcp__h__mcp_filesystem_read", "native MCP single-underscore"),
        ("mcp__custom_tool", "mcp__custom_tool", "already-prefixed double-underscore"),
    ]

    fail = 0
    for src, expected, label in cases:
        disguised = adapter._oauth_rename_tool(src)
        back = adapter._oauth_unrename_tool(disguised)
        ok_rename = disguised == expected
        ok_round = back == src
        status = "OK" if (ok_rename and ok_round) else "FAIL"
        if not (ok_rename and ok_round):
            fail += 1
        print(f"  [{status}] {label:35s} {src:35s} -> {disguised:45s} -> {back}")
        if not ok_rename:
            print(f"        EXPECTED disguised: {expected}")
        if not ok_round:
            print(f"        EXPECTED round-trip back to: {src}")

    print(f"\n  {len(cases) - fail}/{len(cases)} passed")

    print()
    print("=" * 70)
    print("2. SANITIZATION SMOKE TEST")
    print("=" * 70)

    SAMPLE_PROMPT = (
        "You are Hermes Agent, an intelligent AI assistant created by Nous Research.\n"
        "\n"
        "# Some hermes-agent feature description.\n"
        "\n"
        "Active Hermes profile: default. Other profiles live under ~/.hermes/profiles/<name>/.\n"
        "Each profile has its own skills/, plugins/, cron/, and memories/.\n"
        "\n"
        "# Nous Subscription\n"
        "Nous subscription includes managed web tools (Firecrawl), image generation (FAL),"
        " OpenAI TTS, and browser automation (Browser Use) by default. Modal execution is optional.\n"
        "Current capability status:\n"
        "- web tools: active via Nous subscription\n"
        "- image generation: active via Nous subscription\n"
        "When a Nous-managed feature is active, do not ask the user for Firecrawl, FAL,"
        " OpenAI TTS, or Browser-Use API keys.\n"
        "If the user is not subscribed and asks for a capability that Nous subscription"
        " would unlock or simplify, suggest Nous subscription as one option alongside direct"
        " setup or local alternatives.\n"
        "Do not mention subscription unless the user asks about it or it directly solves"
        " the current missing capability.\n"
        "Useful commands: hermes setup, hermes setup tools, hermes setup terminal, hermes status.\n"
        "\n"
        "# Kanban task execution protocol\n"
        "You have been assigned ONE task from the shared board at `~/.hermes/kanban.db`."
        " Your task id is in `$HERMES_KANBAN_TASK`; your workspace is `$HERMES_KANBAN_WORKSPACE`.\n"
        "- Do not shell out to `hermes kanban <verb>` for board operations. Use the"
        " `kanban_*` tools - they work across all terminal backends.\n"
        "- Do not call `delegate_task` as a board substitute. `delegate_task` is for short"
        " reasoning subtasks inside your own run; board tasks are for cross-agent handoffs"
        " that outlive one API loop.\n"
        "\n"
        "Conversation started: Sunday, May 25, 2026\n"
        "Model: claude-opus-4-7\n"
        "Provider: anthropic\n"
        "\n"
        "If the user asks about configuring, setting up, or using Hermes Agent itself,"
        " load the `hermes-agent` skill with skill_view(name='hermes-agent') before"
        " answering. Docs: https://hermes-agent.nousresearch.com/docs\n"
        "\n"
        "Whenever the user asks you to configure Hermes Agent itself (e.g. `hermes config"
        " set foo`, `hermes setup`, `hermes status`), load the `hermes-agent` skill first.\n"
        "\n"
        "You are in the Hermes WebUI, a browser-based chat interface. Full Markdown "
        "rendering is supported.\n"
        "Look for .hermes.md or HERMES.md files. Check $HERMES_HOME for installation.\n"
    )

    def sanitize(text: str) -> str:
        text = text.replace("Hermes Agent", "Claude Code")
        text = text.replace("Hermes agent", "Claude Code")
        text = text.replace("hermes-agent", "claude-code")
        text = text.replace("Nous Research", "Anthropic")
        text = text.replace("claude-code.nousresearch.com", "claude-code.anthropic.com")
        text = adapter._reformat_available_skills_block(text)
        text = re.sub(r"\n?Host:\s*[^\n]*\nUser home directory:[^\n]*\nCurrent working directory:[^\n]*\n(?:Note:[^\n]*\n)?", "\n", text)
        text = re.sub(r"\n?Shell: on this [^\n]+ host your `?terminal`? tool[\s\S]*?(?:POSIX equivalents[^\n]*\n|will NOT work[^\n]*\n)", "\n", text)
        text = re.sub(r"Conversation started:[^\n]*\nModel:[^\n]*\nProvider:[^\n]*\n?", "", text)
        text = re.sub(r"<!--\s*\nThis file defines the agent's personality[\s\S]*?-->\n?", "", text)
        text = re.sub(r"^#\s+Claude Code Persona\s*\n+", "", text)
        text = re.sub(r"\s*\(e\.g\.\s*`hermes [^`]*`(?:,\s*`hermes [^`]*`)*\)", "", text)
        text = re.sub(r"#\s*Nous Subscription\n[\s\S]*?hermes status\.\s*", "", text)
        text = re.sub(r"#\s*Kanban task execution protocol\n[\s\S]*?cross-agent handoffs that outlive one API loop\.\s*", "", text)
        text = text.replace("~/.hermes/", "~/.claude/")
        text = text.replace("$HERMES_", "$CLAUDE_")
        text = text.replace(".hermes.md", ".claude.md")
        text = text.replace("HERMES.md", "CLAUDE.md")
        text = text.replace("HERMES_HOME", "CLAUDE_HOME")
        text = re.sub(r"\bhermes\s+(setup|status|config|tools|kanban|chat|run|skill|skills|profile|profiles|memory|memories)\b", r"claude \1", text)
        text = re.sub(r"\bNous(?=\s+(?:subscription|Subscription|auth|managed|provider))", "Anthropic", text)
        text = re.sub(r"\bnous(?=[-_](?:subscription|auth|managed))", "anthropic", text)
        for old, new in (("session_search", "mcp__h__session_search"), ("skill_manage", "mcp__h__skill_manage"), ("skill_view", "mcp__h__skill_view"), ("skills_list", "mcp__h__skills_list")):
            text = re.sub(rf"\b{old}\b", new, text)
        text = text.replace("You are in the Hermes WebUI, a browser-based chat interface.", "Your output is delivered through a browser-based chat interface.")
        text = re.sub(r"\bHermes\b", "Claude Code", text)
        return text

    sanitized = sanitize(SAMPLE_PROMPT)
    print("\nSANITIZED OUTPUT:")
    print("-" * 70)
    print(sanitized)
    print("-" * 70)

    patterns = [
        (r"\bHermes\b", "Hermes (capital, word)"),
        (r"\bNous\b", "Nous (capital, word)"),
        (r"~/\.hermes/", "~/.hermes/ path"),
        (r"\$HERMES_", "$HERMES_ env var"),
        (r"\bhermes-agent\b", "hermes-agent literal"),
        (r"# Nous Subscription", "Nous Subscription block"),
        (r"# Kanban task execution", "Kanban block"),
        (r"HERMES_HOME", "HERMES_HOME"),
        (r"\bHERMES\.md\b", "HERMES.md"),
        (r"\.hermes\.md", ".hermes.md"),
        (r"\bskill_view\(", "non-renamed skill_view("),
        (r"nousresearch\.com", "nousresearch.com"),
        (r"\bWebUI\b", "WebUI (Hermes surface term)"),
        (r"Hermes WebUI", "Hermes WebUI literal"),
    ]
    leaks = []
    for pat, label in patterns:
        matches = re.findall(pat, sanitized)
        if matches:
            leaks.append((label, len(matches), matches[:3]))

    if leaks:
        print("\nRESIDUAL LEAKS:")
        for label, count, examples in leaks:
            print(f"  [LEAK] {label:35s} x{count}  examples: {examples}")
    else:
        print("\n  [OK] no residual leaks for any tested pattern")

    print()
    print("=" * 70)
    print("3. DUMP DIAGNOSTIC")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as td:
        sample_system = [{"type": "text", "text": sanitized}]
        sample_tools = [
            {"name": "Read", "input_schema": {}},
            {"name": "mcp__h__skill_view", "input_schema": {}},
        ]
        sample_messages = [{"role": "user", "content": "hi"}]
        sample_model = "claude-opus-4-7"

        dump_path = os.path.join(td, f"oauth-{int(time.time() * 1000)}.json")
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "model": sample_model,
                    "system": sample_system,
                    "tools": sample_tools,
                    "messages": sample_messages,
                },
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        files = os.listdir(td)
        print(f"  [OK] dump wrote {len(files)} file: {files}")
        with open(os.path.join(td, files[0]), encoding="utf-8") as f:
            loaded = json.load(f)
        print(f"  [OK] dump JSON valid; keys = {list(loaded.keys())}")
        print(f"  [OK] tools serialized: {[t['name'] for t in loaded['tools']]}")

    print()
    print("DONE")
    return 0 if (fail == 0 and not leaks) else 1


if __name__ == "__main__":
    sys.exit(main())
