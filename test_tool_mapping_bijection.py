"""Transparency proof: does the tool-name mapping round-trip for EVERY
Hermes 0.15.1 tool? If yes, tool dispatch behaves exactly as un-patched.

Tests, over the real registered tool set:
  1. Round-trip:   unrename(rename(n)) == n   for every tool n.
  2. Injectivity:  no two distinct tools share a disguised name.
  3. Reverse-collision: no real tool name equals another tool's disguise.
"""
import importlib.util
import os
import sys
from typing import Dict  # noqa: F401  (used by exec'd helper block)

# ── 1. Load rename/unrename straight out of install.py (single source) ──
_here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("inst", os.path.join(_here, "install.py"))
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)

# Locate the hermes-agent install the same way the installer does (portable).
try:
    HERMES = str(inst.discover_hermes())
except SystemExit as exc:  # no install found -> skip, don't hard-crash
    print(f"SKIP: {exc}")
    sys.exit(0)

USED_FALLBACK = False  # set True when the live registry can't be reached

ns: dict = {"Dict": Dict, "_MCP_TOOL_PREFIX": "mcp_"}
exec(inst.ADAPTER_HELPERS_BLOCK, ns)
rename = ns["_oauth_rename_tool"]
unrename = ns["_oauth_unrename_tool"]

# ── 2. Enumerate the REAL 0.15.1 tool set (registry = ground truth) ──
def real_tools() -> list:
    sys.path.insert(0, HERMES)
    try:
        from tools.registry import registry  # type: ignore
        names = registry.get_all_tool_names()
        if names:
            return sorted(set(names))
    except Exception as exc:  # noqa: BLE001
        global USED_FALLBACK
        USED_FALLBACK = True
        print(f"  (registry import failed: {exc.__class__.__name__}: {exc})")
        print("  → falling back to a FROZEN static tool list (NOT authoritative)\n")
    # Static fallback (scanned from tools/ name="..." declarations)
    return sorted(set([
        "browser_back", "browser_cdp", "browser_click", "browser_console",
        "browser_dialog", "browser_get_images", "browser_navigate",
        "browser_press", "browser_scroll", "browser_snapshot", "browser_type",
        "browser_vision", "clarify", "computer_use", "cronjob", "delegate_task",
        "discord", "discord_admin", "execute_code", "feishu_doc_read",
        "feishu_drive_add_comment", "feishu_drive_list_comment_replies",
        "feishu_drive_list_comments", "feishu_drive_reply_comment",
        "ha_call_service", "ha_get_state", "ha_list_entities", "ha_list_services",
        "image_generate", "kanban_block", "kanban_comment", "kanban_complete",
        "kanban_create", "kanban_heartbeat", "kanban_link", "kanban_list",
        "kanban_show", "kanban_unblock", "memory", "mixture_of_agents", "patch",
        "process", "read_file", "search_files", "send_message", "session_search",
        "skill_manage", "skill_view", "skills_list", "terminal", "text_to_speech",
        "todo", "video_analyze", "video_generate", "vision_analyze", "web_extract",
        "web_search", "write_file", "x_search", "yb_query_group_info",
        "yb_query_group_members", "yb_search_sticker", "yb_send_dm", "yb_send_sticker",
    ]))


def main() -> int:
    tools = real_tools()
    # Native MCP-server tools (registered as mcp_<server>_<tool>) — add samples.
    tools += ["mcp_filesystem_read_file", "mcp__github__create_issue"]
    tools = sorted(set(tools))

    print("=" * 74)
    print(f"BIJECTION TEST over {len(tools)} Hermes 0.15.1 tool names")
    print("=" * 74)

    rt_fail = []          # round-trip failures
    disguise_map: dict = {}  # disguised -> [originals]  (collision detector)

    for n in tools:
        d = rename(n)
        b = unrename(d)
        if b != n:
            rt_fail.append((n, d, b))
        disguise_map.setdefault(d, []).append(n)

    collisions = {d: src for d, src in disguise_map.items() if len(src) > 1}

    # reverse-collision: a real tool name that is ALSO some other tool's disguise
    tool_set = set(tools)
    reverse = []
    for d, src in disguise_map.items():
        if d in tool_set and d not in src:
            reverse.append((d, src))

    print(f"\n1. ROUND-TRIP  unrename(rename(n)) == n")
    if not rt_fail:
        print(f"   [OK] all {len(tools)} tools round-trip exactly")
    else:
        print(f"   [FAIL] {len(rt_fail)} tools do NOT round-trip:")
        for n, d, b in rt_fail:
            print(f"      {n}  ->  {d}  ->  {b}   (expected {n})")

    print(f"\n2. INJECTIVITY  distinct tools never share a disguise")
    if not collisions:
        print(f"   [OK] no two tools map to the same disguised name")
    else:
        print(f"   [FAIL] {len(collisions)} disguise collisions:")
        for d, src in collisions.items():
            print(f"      {src}  ALL map to  {d}")

    print(f"\n3. REVERSE-COLLISION  disguise never equals a different real tool")
    if not reverse:
        print(f"   [OK] no disguise shadows a real tool name")
    else:
        print(f"   [FAIL] {len(reverse)}:")
        for d, src in reverse:
            print(f"      {src} -> {d}, but {d} is itself a real tool")

    ok = not (rt_fail or collisions or reverse)
    print("\n" + "=" * 74)
    if USED_FALLBACK:
        # Couldn't reach the live registry: the static list is frozen and may
        # miss new 0.15.1 tools, so a green result here is NOT authoritative.
        print("VERDICT: INCONCLUSIVE - live registry unavailable; checked a "
              "frozen static list only (not authoritative)")
    else:
        print("VERDICT:", "FULLY TRANSPARENT - behaves as un-patched [OK]" if ok
              else "NOT transparent - gaps above must be fixed [FAIL]")
    print("=" * 74)

    # Show the disguise scheme for a representative sample
    print("\nDisguise scheme sample:")
    for n in ["read_file", "terminal", "browser_click", "browser_cdp",
              "kanban_show", "session_search", "web_search", "yb_send_sticker",
              "mcp_filesystem_read_file", "mcp__github__create_issue"]:
        if n in tool_set:
            print(f"   {n:28s} ->  {rename(n)}")
    return 2 if USED_FALLBACK else (0 if ok else 1)


if __name__ == "__main__":
    sys.exit(main())
