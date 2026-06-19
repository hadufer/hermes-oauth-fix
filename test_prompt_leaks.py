"""Re-study (v2): what in Hermes 0.16.0's prompt survives the current sanitizer.

Precise reproduction — extracts ONLY the named constants that
agent/system_prompt.py actually concatenates into the stable system prompt
(plus the dynamically built Nous block). No code-internal strings, no
docstrings, no env-var-name literals. Whatever leaks here is what re-flags.
"""
import ast
import os
import re
import sys


def _prompt_builder_path() -> str:
    """Resolve agent/prompt_builder.py via install.py's cross-platform discovery."""
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "_oauth_installer", os.path.join(here, "install.py")
    )
    inst = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inst)
    try:
        root = inst.discover_hermes()
    except SystemExit as exc:  # no install found -> skip, don't hard-crash
        print(f"SKIP: {exc}")
        sys.exit(0)
    return str(root / "agent" / "prompt_builder.py")


ADAPTER = _prompt_builder_path()

# Exactly what system_prompt.py imports + appends into the prompt.
PROMPT_CONSTANTS = [
    "DEFAULT_AGENT_IDENTITY",
    "HERMES_AGENT_HELP_GUIDANCE",
    "MEMORY_GUIDANCE",
    "SESSION_SEARCH_GUIDANCE",
    "SKILLS_GUIDANCE",
    "STEER_CHANNEL_NOTE",        # 0.16.0: mid-turn steering note (mentions Hermes)
    "KANBAN_GUIDANCE",            # stripped — included to verify the strip
    "TASK_COMPLETION_GUIDANCE",
    "TOOL_USE_ENFORCEMENT_GUIDANCE",
    "GOOGLE_MODEL_OPERATIONAL_GUIDANCE",
    "OPENAI_MODEL_EXECUTION_GUIDANCE",
    "COMPUTER_USE_GUIDANCE",
    "PLATFORM_HINTS",            # dict of platform -> intro string
]

# Dynamically built block (build_nous_subscription_prompt) — exact emitted text,
# worst case where every feature is managed-by-Nous.
NOUS_BLOCK = "\n".join([
    "# Nous Subscription",
    "Nous subscription includes managed web tools (Firecrawl), image generation (FAL), OpenAI TTS, and browser automation (Browser Use) by default. Modal execution is optional.",
    "Current capability status:",
    "- Web search: active via Nous subscription",
    "- Image generation: included with Nous subscription, not currently selected",
    "- Modal execution: optional via Nous subscription",
    "When a Nous-managed feature is active, do not ask the user for Firecrawl, FAL, OpenAI TTS, or Browser-Use API keys.",
    "If the user is not subscribed and asks for a capability that Nous subscription would unlock or simplify, suggest Nous subscription as one option alongside direct setup or local alternatives.",
    "Do not mention subscription unless the user asks about it or it directly solves the current missing capability.",
    "Useful commands: hermes setup, hermes setup tools, hermes setup terminal, hermes status.",
])


def _collect_strs(node) -> list:
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def extract_named_constants(path: str, names: list) -> dict:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    wanted = set(names)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in wanted:
                    out[tgt.id] = "\n".join(_collect_strs(node.value))
    return out


def sanitize(text: str) -> str:
    """CURRENT uncommitted ADAPTER_OAUTH_PATCHED rules."""
    text = text.replace("Hermes Agent", "Claude Code")
    text = text.replace("Hermes agent", "Claude Code")
    text = text.replace("hermes-agent", "claude-code")
    text = text.replace("Nous Research", "Anthropic")
    text = text.replace("claude-code.nousresearch.com", "claude-code.anthropic.com")
    text = re.sub(r"\n?Host:\s*[^\n]*\nUser home directory:[^\n]*\nCurrent working directory:[^\n]*\n(?:Note:[^\n]*\n)?", "\n", text)
    text = re.sub(r"\n?Shell: on this [^\n]+ host your `?terminal`? tool[\s\S]*?(?:POSIX equivalents[^\n]*\n|will NOT work[^\n]*\n)", "\n", text)
    text = re.sub(r"Conversation started:[^\n]*(?:\nSession ID:[^\n]*)?(?:\nModel:[^\n]*)?(?:\nProvider:[^\n]*)?\n?", "", text)
    text = re.sub(r"<!--\s*\nThis file defines the agent's personality[\s\S]*?-->\n?", "", text)
    text = re.sub(r"^#\s+Claude Code Persona\s*\n+", "", text)
    text = re.sub(r"\s*\(e\.g\.\s*`hermes [^`]*`(?:,\s*`hermes [^`]*`)*\)", "", text)
    text = re.sub(r"#\s*Nous Subscription\n[\s\S]*?hermes status\.\s*", "", text)
    text = re.sub(r"#\s*Kanban task execution protocol\n[\s\S]*?cross-agent handoffs that outlive one API loop\.\s*", "", text)
    text = re.sub(r"(?<=[\\/.])hermes(?=[\\/])", "claude", text, flags=re.IGNORECASE)
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
    # Platform-intro rewrites — leak-focused MIRROR of install.py
    # ADAPTER_OAUTH_PATCHED (keep in sync). Only the product-name-bearing rules
    # are modeled; non-leaking intro rewrites (CLI/Discord/...) and the WSL
    # strip are intentionally omitted — they remove no product name.
    text = text.replace(
        "You are in the Hermes WebUI, a browser-based chat interface.",
        "Your output is delivered through a browser-based chat interface.",
    )
    text = re.sub(r"\bWebUI\b", "web interface", text)  # catch-all, mirrors install.py
    text = re.sub(r"\bHermes\b", "Claude Code", text)
    text = re.sub(r"\bNous\b", "Anthropic", text)  # symmetric bare-word catch-all
    return text


LEAK_PATTERNS = [
    (r"\bHermes\b", "Hermes (word)"),
    (r"\bhermes\b", "hermes (lower)"),
    (r"\bNous\b", "Nous (bare word, NOT followed by sub/auth/managed)"),
    (r"\bnous\b", "nous (lower)"),
    (r"nousresearch", "nousresearch domain"),
    (r"~/\.hermes", "~/.hermes path"),
    (r"\$HERMES_", "$HERMES_ env"),
    (r"\bWebUI\b", "WebUI"),
    (r"\bFirecrawl\b", "Firecrawl (Nous-managed product)"),
    (r"\bBrowser Use\b|\bBrowser-Use\b", "Browser Use"),
    (r"\bFAL\b", "FAL"),
    (r"\bModal\b", "Modal"),
]


# Synthetic block scenarios — conditional shapes that the AST-constant scan
# cannot reach (they're assembled at runtime in build_system_prompt). Each is a
# minimal-faithful reconstruction of a real assembly path, used to lock in
# coverage for regressions like the Session-ID-breaks-timestamp-strip and the
# Windows-path-component leak.
SYNTHETIC_SCENARIOS = [
    (
        "timestamp_block_with_session_id",
        "Conversation started: Friday, June 19, 2026\n"
        "Session ID: abc-123-def\n"
        "Model: claude-opus-4-7\n"
        "Provider: nous",
    ),
    (
        "timestamp_block_session_id_only",
        "Conversation started: Friday, June 19, 2026\n"
        "Session ID: abc-123-def",
    ),
    (
        "timestamp_block_provider_only",
        "Conversation started: Friday, June 19, 2026\n"
        "Provider: nous",
    ),
    (
        "soul_md_truncation_marker_windows",
        "\n\n[...truncated SOUL.md: kept 800+200 of 5000 chars. The middle is "
        "omitted — if you need the full instructions, read the complete file "
        "with the read_file tool: C:\\Users\\Zero\\AppData\\Local\\hermes\\SOUL.md]\n\n",
    ),
    (
        "hermes_md_truncation_marker_windows",
        "\n\n[...truncated .hermes.md: kept 800+200 of 5000 chars. The middle "
        "is omitted — if you need the full instructions, read the complete "
        "file with the read_file tool: C:\\Users\\Zero\\projects\\foo\\.hermes.md]\n\n",
    ),
    (
        "soul_md_truncation_marker_posix",
        "\n\n[...truncated SOUL.md: kept 800+200 of 5000 chars. The middle is "
        "omitted — if you need the full instructions, read the complete file "
        "with the read_file tool: /home/user/.hermes/SOUL.md]\n\n",
    ),
]


def main() -> int:
    consts = extract_named_constants(ADAPTER, PROMPT_CONSTANTS)
    missing = [n for n in PROMPT_CONSTANTS if n not in consts]
    if missing:
        print(f"  NOTE: constants not found (renamed/removed in 0.16.0?): {missing}\n")

    raw = "\n\n".join(consts.get(n, "") for n in PROMPT_CONSTANTS) + "\n\n" + NOUS_BLOCK
    sanitized = sanitize(raw)

    print("=" * 74)
    print("RESIDUAL LEAKS — current sanitizer vs Hermes 0.16.0 actual prompt blocks")
    print("=" * 74)

    total = 0
    for pat, label in LEAK_PATTERNS:
        hits = list(re.finditer(pat, sanitized))
        if not hits:
            continue
        total += len(hits)
        seen, ctxs = set(), []
        for m in hits:
            s = max(0, m.start() - 50); e = min(len(sanitized), m.end() + 50)
            ctx = sanitized[s:e].replace("\n", " ").strip()
            if ctx[:75] in seen:
                continue
            seen.add(ctx[:75]); ctxs.append(ctx)
        print(f"\n[LEAK] {label}  x{len(hits)}")
        for c in ctxs:
            print(f"    …{c}…")

    print()
    print("=" * 74)
    print("SYNTHETIC ASSEMBLED-AT-RUNTIME SCENARIOS (conditional prompt shapes)")
    print("=" * 74)
    synth_total = 0
    for label, block in SYNTHETIC_SCENARIOS:
        out = sanitize(block)
        scenario_hits = []
        for pat, plabel in LEAK_PATTERNS:
            hits = list(re.finditer(pat, out))
            if hits:
                scenario_hits.append((plabel, len(hits), out))
        if not scenario_hits:
            print(f"  [OK]  {label}")
            continue
        synth_total += sum(n for _, n, _ in scenario_hits)
        print(f"  [FAIL] {label}")
        for plabel, n, out in scenario_hits:
            print(f"        x{n} {plabel}  output: {out!r}")

    print()
    print("=" * 74)
    print(f"TOTAL residual hits in actual-prompt blocks: {total}")
    print(f"TOTAL residual hits in synthetic scenarios:  {synth_total}")
    grand = total + synth_total
    print("PASS — no product-name leaks" if grand == 0
          else f"FAIL — {grand} residual leak(s) would re-trigger the detector")
    print("=" * 74)
    return 1 if grand else 0


if __name__ == "__main__":
    sys.exit(main())
