"""設定：エージェントの書き方・settings.json の守り・data の鍵。"""
import json
import os
import re

from helpers import REPO, fresh

AGENTS = ["ai-shacho", "ai-tencho", "ai-sekkyaku", "ai-uketsuke", "ai-shiire", "ai-butsuryu",
          "ai-eigyo", "ai-ec", "ai-koukoku", "ai-kouhou", "ai-keiri", "ai-houmu"]


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, path
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def test_agents_frontmatter():
    files = sorted((REPO / ".claude/agents").glob("*.md"))
    assert sorted(f.stem for f in files) == sorted(AGENTS)
    for f in files:
        fm = frontmatter(f)
        assert fm["name"] == f.stem and re.fullmatch(r"[a-z][a-z0-9-]*", fm["name"])
        assert len(fm["description"]) > 20
        tools = [t.strip() for t in fm["tools"].split(",")]
        assert "Read" in tools and set(tools) <= {"Read", "Grep", "Glob", "Bash", "Write", "Edit", "Agent"}
        body = f.read_text(encoding="utf-8")
        assert "knowledge/" in body and "q.py" in body, f.name


def test_commands_have_frontmatter():
    names = {f.stem for f in (REPO / ".claude/commands").glob("*.md")}
    for n in ("朝会", "経営会議", "月次決算", "一日進める", "承認", "却下", "承認待ち", "ダッシュボード", "朝のレポート", "売上どうやった"):
        assert n in names, n
        assert "description" in frontmatter(REPO / ".claude/commands" / f"{n}.md")


def test_settings_denies_writes():
    s = json.loads((REPO / ".claude/settings.json").read_text(encoding="utf-8"))
    deny, allow = s["permissions"]["deny"], s["permissions"]["allow"]
    for d in ("data", "company", "knowledge", "sim", "tools"):
        assert f"Edit(/{d}/**)" in deny
    for a in ("Edit(/reports/**)", "Edit(/approvals/pending/**)", "Edit(/logs/**)"):
        assert a in allow
    assert not any(x.startswith("Bash(python3 tools/sim.py advance") or x.startswith("Bash(python3 tools/sim.py apply") for x in allow)


def test_data_is_read_only_after_sim():
    p = fresh()
    if os.geteuid() == 0:
        return
    target = p.data / "store/POS_日別.csv"
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write("x\n")
        wrote = True
    except PermissionError:
        wrote = False
    assert not wrote
    try:
        (p.data / "store/新しいファイル.csv").write_text("x", encoding="utf-8")
        created = True
    except PermissionError:
        created = False
    assert not created
