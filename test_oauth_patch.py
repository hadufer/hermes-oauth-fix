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
    try:
        return str(inst.discover_hermes())
    except SystemExit as exc:  # no install found -> skip, don't hard-crash
        print(f"SKIP: {exc}")
        sys.exit(0)


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
        "\n"
        # --- 0.16.0-specific blocks ---
        "## Mid-turn user steering\n"
        "While you work, the user can send an out-of-band message that Hermes appends to "
        "the end of a tool result.\n"
        "\n"
        "Runtime surface: you're running inside the Hermes desktop GUI app.\n"
        "\n"
        "Terminal backend: modal. Your tools all operate inside this modal environment — "
        "NOT on the machine where Hermes itself is running. The cwd of the Hermes process "
        "is irrelevant.\n"
        "\n"
        "Active Hermes profile: default. Other profiles (if any) live under "
        "~/.hermes/profiles/<name>/. Each profile has its own skills/, plugins/, cron/, "
        "and memories/.\n"
        "\n"
        "## Skills (mandatory)\n"
        "Whenever the user asks you to configure, set up, install, enable, disable, modify, "
        "or troubleshoot Hermes Agent itself — its CLI, config, models, providers, tools, "
        "skills, voice, gateway, plugins, or any feature — load the `hermes-agent` skill "
        "first. It has the actual commands (e.g. `hermes config set foo`, `hermes tools`, "
        "`hermes setup`).\n"
        "<available_skills>\n"
        "  software-development: Build and debug software.\n"
        "    - plan: Plan mode: write an actionable markdown plan to .hermes/plans then act.\n"
        "    - requesting-code-review: Pre-commit review of the working tree.\n"
        "    - debugging-hermes-tui-commands: Debug the Hermes TUI slash commands.\n"
        "</available_skills>\n"
    )

    def sanitize(text: str) -> str:
        # Reformat (and skill-name disguise) runs FIRST, matching install.py.
        text = adapter._reformat_available_skills_block(text)
        text = text.replace("Hermes Agent", "Claude Code")
        text = text.replace("Hermes agent", "Claude Code")
        text = text.replace("hermes-agent", "claude-code")
        text = text.replace("Nous Research", "Anthropic")
        text = text.replace("claude-code.nousresearch.com", "claude-code.anthropic.com")
        text = re.sub(r"\n?Host:\s*[^\n]*\nUser home directory:[^\n]*\nCurrent working directory:[^\n]*\n(?:Note:[^\n]*\n)?", "\n", text)
        text = re.sub(r"\n?Shell: on this [^\n]+ host your `?terminal`? tool[\s\S]*?(?:POSIX equivalents[^\n]*\n|will NOT work[^\n]*\n)", "\n", text)
        text = re.sub(r"Conversation started:[^\n]*\nModel:[^\n]*\nProvider:[^\n]*\n?", "", text)
        text = re.sub(r"<!--\s*\nThis file defines the agent's personality[\s\S]*?-->\n?", "", text)
        text = re.sub(r"^#\s+Claude Code Persona\s*\n+", "", text)
        text = re.sub(r"\s*\(e\.g\.\s*`hermes [^`]*`(?:,\s*`hermes [^`]*`)*\)", "", text)
        text = re.sub(r"#\s*Nous Subscription\n[\s\S]*?hermes status\.\s*", "", text)
        text = re.sub(r"#\s*Kanban task execution protocol\n[\s\S]*?cross-agent handoffs that outlive one API loop\.\s*", "", text)
        text = text.replace(".hermes/", ".claude/")
        text = text.replace("$HERMES_", "$CLAUDE_")
        text = text.replace(".hermes.md", ".claude.md")
        text = text.replace("HERMES.md", "CLAUDE.md")
        text = text.replace("HERMES_HOME", "CLAUDE_HOME")
        text = re.sub(r"\bhermes\s+(setup|status|config|tools|kanban|chat|run|skill|skills|profile|profiles|memory|memories)\b", r"claude \1", text)
        text = re.sub(r"\bNous(?=\s+(?:subscription|Subscription|auth|managed|provider))", "Anthropic", text)
        text = re.sub(r"\bnous(?=[-_](?:subscription|auth|managed))", "anthropic", text)
        for old, new in (("session_search", "mcp__h__session_search"), ("skill_manage", "mcp__h__skill_manage"), ("skill_view", "mcp__h__skill_view"), ("skills_list", "mcp__h__skills_list")):
            text = re.sub(rf"\b{old}\b", new, text)
        # Leak-focused MIRROR of install.py ADAPTER_OAUTH_PATCHED (keep in sync);
        # non-leaking intro rewrites and the WSL strip are omitted on purpose.
        text = text.replace("You are in the Hermes WebUI, a browser-based chat interface.", "Your output is delivered through a browser-based chat interface.")
        text = re.sub(r"\bWebUI\b", "web interface", text)  # catch-all, mirrors install.py
        text = re.sub(r"\bHermes\b", "Claude Code", text)
        text = re.sub(r"\bNous\b", "Anthropic", text)  # symmetric bare-word catch-all
        return text

    sanitized = sanitize(SAMPLE_PROMPT)
    print("\nSANITIZED OUTPUT:")
    print("-" * 70)
    print(sanitized)
    print("-" * 70)

    patterns = [
        (r"\bHermes\b", "Hermes (capital, word)"),
        (r"\bhermes\b", "hermes (lower, word) — e.g. skill-name slug"),
        (r"\bNous\b", "Nous (capital, word)"),
        (r"\bnous\b", "nous (lower, word)"),
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
    print("3. END-TO-END: REAL build_anthropic_kwargs(is_oauth=True) + DUMP")
    print("=" * 70)
    # Feed the RAW (unsanitized) prompt through the actual code path that runs
    # before every Anthropic request, with the diagnostic dump enabled, then
    # grep what it serialized. This validates the live patched sanitizer — not
    # the mirror above — so it catches drift between the two and any regression
    # in the real adapter for this Hermes version.
    e2e_leaks = []
    with tempfile.TemporaryDirectory() as td:
        os.environ["HERMES_OAUTH_FIX_DUMP_DIR"] = td
        try:
            messages = [
                {"role": "system", "content": SAMPLE_PROMPT},
                {"role": "user", "content": "hi"},
            ]
            tools = [
                {"type": "function", "function": {"name": n, "description": "d",
                 "parameters": {"type": "object", "properties": {}}}}
                for n in ("read_file", "skill_view", "browser_click")
            ]
            adapter.build_anthropic_kwargs(
                "claude-opus-4-7", messages, tools, 4096, None, is_oauth=True,
            )
        finally:
            os.environ.pop("HERMES_OAUTH_FIX_DUMP_DIR", None)

        dumps = [f for f in os.listdir(td) if f.endswith(".json")]
        if not dumps:
            print("  [FAIL] no dump written — sanitizer path did not run")
            return 1
        loaded = json.load(open(os.path.join(td, dumps[0]), encoding="utf-8"))
        print(f"  [OK] dump JSON valid; keys = {list(loaded.keys())}")
        print(f"  [OK] tools serialized: {[t['name'] for t in loaded['tools']]}")

        real_system = "\n".join(
            b.get("text", "") for b in loaded.get("system", []) if isinstance(b, dict)
        )
        for pat, label in patterns:
            m = re.findall(pat, real_system)
            if m:
                e2e_leaks.append((label, len(m), m[:3]))
        if e2e_leaks:
            print("\n  RESIDUAL LEAKS in REAL dumped system prompt:")
            for label, count, examples in e2e_leaks:
                print(f"    [LEAK] {label:35s} x{count}  examples: {examples}")
        else:
            print("  [OK] real dumped system prompt has no residual leaks")

    print()
    print("=" * 70)
    print("4. SKILL-NAME DISGUISE ROUND-TRIP (skill_view/skill_manage args)")
    print("=" * 70)
    # Self-contained: drive disguise -> undisguise explicitly (no reliance on
    # earlier sections having populated the global map). Verifies the token is
    # gone from the disguised name AND the inbound reverse recovers the exact
    # on-disk name, for lowercase, hyphenated, and Title-case slugs.
    skill_fail = 0
    for original in ("debugging-hermes-tui-commands", "hermes-s6-container-supervision",
                     "hermes-agent", "Hermes-Toolkit"):
        disguised = adapter._oauth_disguise_skill_name(original)
        back = adapter._oauth_undisguise_skill_name(disguised)
        token_gone = "hermes" not in disguised.lower() and "nous" not in disguised.lower()
        ok = (back == original) and token_gone and (disguised != original)
        skill_fail += 0 if ok else 1
        print(f"  [{'OK' if ok else 'FAIL'}] {original!r} -> {disguised!r} -> {back!r}")
    # Substring safety: a word that merely CONTAINS "nous"/"hermes" is untouched.
    for safe in ("luminous-ui", "ominous-mode", "synchronous-jobs"):
        d = adapter._oauth_disguise_skill_name(safe)
        ok = d == safe
        skill_fail += 0 if ok else 1
        print(f"  [{'OK' if ok else 'FAIL'}] substring-safe: {safe!r} -> {d!r} (must be unchanged)")
    # A token-free skill must be left untouched and never reverse-mapped.
    plain = adapter._oauth_undisguise_skill_name("requesting-code-review")
    plain_ok = plain == "requesting-code-review"
    skill_fail += 0 if plain_ok else 1
    print(f"  [{'OK' if plain_ok else 'FAIL'}] token-free skill untouched: {plain!r}")

    print()
    print("DONE")
    return 0 if (fail == 0 and not leaks and not e2e_leaks and not skill_fail) else 1


if __name__ == "__main__":
    sys.exit(main())
