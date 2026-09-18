"""The engine checkout must be exactly the locked revision plus the patch series.

`assert_tree_matches` rebuilt the expected tree and compares file CONTENT. The
check it replaced compared modified filenames and asked each patch whether it
was reversible, which accepts an extra line inside a file the patches already
touch - the case the review used to show the hole. The repository below is
synthetic on purpose: it is a fixture for the checker, not a claim about
upstream.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from engine_patches import apply_all, assert_tree_matches, sha256  # noqa: E402

BASE = """#include "combat/BattleContext.h"

void BattleContext::useSkillCard() {
    switch (card) {
        case CardId::DISARM:
            addToBot( Actions::DebuffEnemy<MS::STRENGTH>(t, -2, false) );
            break;

        case CardId::DISCOVERY:
            break;
    }
}
"""

RULE_FIXED = BASE.replace("(t, -2, false)", "(t, up ? -3 : -2, false)")
LOG_ADDED = RULE_FIXED.replace("    }\n}", "    }\n    recordEvent(card);\n}")


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                          cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def engine(tmp_path):
    """A locked base and two real incremental patches on top of it."""
    upstream = tmp_path / "upstream"
    (upstream / "src" / "combat").mkdir(parents=True)
    target = upstream / "src" / "combat" / "BattleContext.cpp"
    target.write_text(BASE, encoding="utf-8")
    (upstream / "README.md").write_text("synthetic fixture\n", encoding="utf-8")
    git(upstream, "init", "-q")
    git(upstream, "add", "-A")
    git(upstream, "commit", "-q", "-m", "base")
    base_commit = git(upstream, "rev-parse", "HEAD").stdout.strip()

    root = tmp_path / "repo"
    patches_dir = root / "native" / "patches"
    patches_dir.mkdir(parents=True)
    patches = []
    # Real diffs, produced by git, so the fixture cannot pass on a malformed patch.
    for name, text in (("0001-rule.patch", RULE_FIXED), ("0002-log.patch", LOG_ADDED)):
        target.write_text(text, encoding="utf-8")
        diff = subprocess.run(["git", "diff"], cwd=upstream, check=True,
                              capture_output=True, text=True).stdout
        assert diff, f"no diff produced for {name}"
        path = patches_dir / name
        path.write_text(diff, encoding="utf-8")
        patches.append({"file": f"native/patches/{name}", "sha256": sha256(path)})
        git(upstream, "add", "-A")
        git(upstream, "commit", "-q", "-m", name)
    git(upstream, "reset", "--hard", "-q", base_commit)  # back to the locked base
    return root, upstream, patches, target


def test_the_series_applies_in_order_and_the_tree_then_matches(engine):
    root, upstream, patches, target = engine
    apply_all(root, upstream, patches)
    assert_tree_matches(root, upstream, patches)
    assert "up ? -3 : -2" in target.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8").count("recordEvent(card)") == 1


def test_applying_twice_does_not_apply_a_patch_again(engine):
    root, upstream, patches, target = engine
    apply_all(root, upstream, patches)
    once = sha256(target)
    apply_all(root, upstream, patches)
    assert sha256(target) == once, "a second apply rewrote an already-patched file"
    assert_tree_matches(root, upstream, patches)


def test_an_unregistered_extra_byte_in_a_touched_file_is_rejected(engine):
    root, upstream, patches, target = engine
    apply_all(root, upstream, patches)
    target.write_text(target.read_text(encoding="utf-8") + "// local experiment\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Content differs"):
        assert_tree_matches(root, upstream, patches)


def test_a_removed_rule_hunk_is_rejected(engine):
    root, upstream, patches, target = engine
    apply_all(root, upstream, patches)
    target.write_text(BASE, encoding="utf-8")  # rule fragment reverted in place
    with pytest.raises(SystemExit, match="Content differs|does not apply"):
        assert_tree_matches(root, upstream, patches)


def test_a_half_applied_series_is_not_a_complete_series(engine):
    root, upstream, patches, target = engine
    apply_all(root, upstream, patches[:1])  # only the first patch
    with pytest.raises(SystemExit, match="Content differs"):
        assert_tree_matches(root, upstream, patches)


def test_an_unregistered_file_is_rejected(engine):
    root, upstream, patches, target = engine
    apply_all(root, upstream, patches)
    (upstream / "src" / "combat" / "scratch.cpp").write_text("int main(){}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="untracked"):
        assert_tree_matches(root, upstream, patches)
