"""make_engine_commit_equiv.py: the evidence that two engine commits of one release differ in version strings only (ENGINE-COMMIT-EQUIV).

Each test builds a throwaway git repository in a temporary directory (a base commit, then one or more head commits), runs the tool on it as a
subprocess, and reads the exit status, the markdown and the JSON entry. No engine repository, no image, no network: git is the only program the
tests start. Git reads no user or system configuration (GIT_CONFIG_GLOBAL, GIT_CONFIG_NOSYSTEM), so a developer's diff.noprefix or signing
setting changes nothing, and the identity of the throwaway commits is set with -c on every git command.
Run with `python -m pytest test_make_engine_commit_equiv.py -q` from this directory.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_engine_commit_equiv as M  # noqa: E402

TOOL = HERE / "make_engine_commit_equiv.py"
REGISTRY = HERE / "engine_commit_equiv.json"
OLD, NEW = "26.11.1", "26.12.1"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
IDENT = ["-c", "user.name=Test Author", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]

# The base commit is what upstream has just before "Set release version to NEW": the pom still says NEW-SNAPSHOT, the studio package file and the
# server.json image identifier still say the release before (OLD). The version bump changes exactly those three lines.
BASE_FILES = {
    "pom.xml": f"<project>\n  <groupId>com.example</groupId>\n  <version>{NEW}-SNAPSHOT</version>\n  <name>engine</name>\n</project>\n",
    "studio/package.json": f'{{\n  "name": "studio",\n  "version": "{OLD}",\n  "private": true\n}}\n',
    "server.json": f'{{\n  "image": "arcadedata/arcadedb:{OLD}",\n  "port": 2480\n}}\n',
    "src/Engine.txt": "line one\nline two\nline three\n",
}
VERSION_BUMP = {
    "pom.xml": BASE_FILES["pom.xml"].replace(f"{NEW}-SNAPSHOT", NEW),
    "studio/package.json": BASE_FILES["studio/package.json"].replace(OLD, NEW),
    "server.json": BASE_FILES["server.json"].replace(OLD, NEW),
}
ENTRY_SCOPE = "the native server image only; release pair only"


def _git(repo, *args):
    return subprocess.run(["git", *IDENT, "-C", str(repo), *args], capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def _commit(repo, files, message):
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(repo, "add", *files)                         # explicit paths
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _pair(root, *head_steps):
    """(repo, base, head) in a new directory under `root`: the base commit, then one head commit per step (a dict of file -> new text).
    No step means the version bump."""
    repo = root / "engine"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    base = _commit(repo, BASE_FILES, "base")
    head = base
    for i, files in enumerate(head_steps or (VERSION_BUMP,)):
        head = _commit(repo, files, f"head {i}")
    return repo, base, head


def _out(root):
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _run(repo, base, head, out, *extra, release=NEW, old=OLD):
    cmd = [sys.executable, str(TOOL), "--repo", str(repo), "--base", base, "--head", head, "--release", release, "--old-release", old,
           "--out-md", str(out / "equiv.md"), "--out-json", str(out / "equiv.json"), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=60)


# ---- accepted
def test_a_head_that_only_changes_version_strings_is_accepted(tmp_path):
    repo, base, head = _pair(tmp_path)
    out = _out(tmp_path)
    r = _run(repo, base, head, out)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"ACCEPTED {NEW}: 3 files, 6 version-string lines, 0 non-version lines; {base[:10]} == {head[:10]}"
    entry = json.loads((out / "equiv.json").read_text())
    assert list(entry) == [NEW]                                                  # one entry, keyed by the release
    assert entry[NEW] == {"pin": base, "equivalent": [head], "files_changed": 3, "version_string_lines": 6, "non_version_lines": 0,
                          "evidence": f"ENGINE-COMMIT-EQUIV-{NEW}.md", "scope": ENTRY_SCOPE}
    md = (out / "equiv.md").read_text()
    assert f"RESULT: ACCEPTED {NEW} pin={base} equivalent={head} version_string_lines=6 non_version_lines=0" in md
    assert "- version-string changed lines: 6" in md and "- non-version changed lines: 0" in md
    assert "`studio/package.json`" in md and "`server.json`" in md and "`pom.xml`" in md


def test_the_entry_has_exactly_the_keys_and_types_of_the_26_11_1_registry_entry(tmp_path):
    repo, base, head = _pair(tmp_path)
    out = _out(tmp_path)
    assert _run(repo, base, head, out).returncode == 0
    written = json.loads((out / "equiv.json").read_text())[NEW]
    real = json.loads(REGISTRY.read_text())["26.11.1"]
    assert set(written) == set(real)
    assert {k: type(v) for k, v in written.items()} == {k: type(v) for k, v in real.items()}
    assert written["scope"] == real["scope"] == ENTRY_SCOPE
    assert written["non_version_lines"] == real["non_version_lines"] == 0


def test_the_evidence_field_names_the_markdown_and_can_be_set(tmp_path):
    repo, base, head = _pair(tmp_path)
    out = _out(tmp_path)
    assert _run(repo, base, head, out).returncode == 0
    assert json.loads((out / "equiv.json").read_text())[NEW]["evidence"] == f"ENGINE-COMMIT-EQUIV-{NEW}.md"
    assert _run(repo, base, head, out, "--evidence", f"ENGINE-COMMIT-EQUIV-{NEW}.md (kept with the release notes)").returncode == 0
    assert json.loads((out / "equiv.json").read_text())[NEW]["evidence"] == f"ENGINE-COMMIT-EQUIV-{NEW}.md (kept with the release notes)"


def test_the_status_lines_go_into_the_markdown_and_are_kept_beside_it(tmp_path):
    repo, base, head = _pair(tmp_path)
    out = _out(tmp_path)
    status = tmp_path / "STATUS.txt"
    status.write_text(f"unrelated line\nPAIR VERIFIED {NEW} wheel=/some/where/arcadedb.whl\nNATIVE_SERVER_VERSION={NEW} (build {head}/1/UNKNOWN)\n"
                      f"NATIVE_SERVER_COMMIT={head}\n")
    assert _run(repo, base, head, out, "--status", str(status)).returncode == 0
    want = [f"PAIR VERIFIED {NEW}", f"NATIVE_SERVER_VERSION={NEW} (build {head}/1/UNKNOWN)", f"NATIVE_SERVER_COMMIT={head}"]
    assert (out / "equiv.md").read_text().count("\n".join(want)) == 1               # the wheel= tail is cut, the unrelated line is left out
    assert (out / "equiv.status-lines.txt").read_text().splitlines() == want
    status.unlink()                                                                # the next dry run truncates STATUS: the saved lines are read back
    assert _run(repo, base, head, out).returncode == 0
    md = (out / "equiv.md").read_text()
    assert "\n".join(want) in md and "no status file given" not in md


# ---- refused
def test_a_head_that_also_changes_one_non_version_line_is_refused(tmp_path):
    repo, base, head = _pair(tmp_path, {**VERSION_BUMP, "src/Engine.txt": "line one\nline 2\nline three\n"})
    out = _out(tmp_path)
    r = _run(repo, base, head, out)
    assert r.returncode == 1
    md = (out / "equiv.md").read_text()
    assert f"RESULT: REFUSED {NEW} pin={base} equivalent={head} version_string_lines=6 non_version_lines=2" in md   # the pair - and + of one line
    assert "  - `src/Engine.txt`: `-line two`" in md and "  - `src/Engine.txt`: `+line 2`" in md
    assert "REFUSED: 2 non-version changed lines, 1 commits between the two" in r.stderr
    assert not (out / "equiv.json").exists()                                      # a refused pair never writes a registry entry


def test_a_hunk_whose_removed_and_added_counts_differ_is_refused(tmp_path):
    base_pom = BASE_FILES["pom.xml"]
    old_lines = f"  <version>{NEW}-SNAPSHOT</version>\n"
    # 1 removed, 2 added: the version line is rewritten correctly but a line is added right after it (one hunk), so none of the 3 lines counts
    more = base_pom.replace(old_lines, f"  <version>{NEW}</version>\n  <extra>1</extra>\n")
    # 2 removed, 1 added: the version line and the line after it are replaced by one version line
    fewer = base_pom.replace(old_lines + "  <name>engine</name>\n", f"  <version>{NEW}</version>\n")
    for name, pom in (("added", more), ("removed", fewer)):
        assert pom != base_pom
        root = tmp_path / name
        repo, base, head = _pair(root, {**VERSION_BUMP, "pom.xml": pom})
        out = _out(root)
        r = _run(repo, base, head, out)
        assert r.returncode == 1, name
        md = (out / "equiv.md").read_text()
        assert f"RESULT: REFUSED {NEW} pin={base} equivalent={head} version_string_lines=4 non_version_lines=3" in md, name   # package.json and server.json only
        assert "  - `pom.xml`: `" in md, name
        assert not (out / "equiv.json").exists(), name


def test_two_commits_between_base_and_head_are_refused_even_when_every_line_is_a_version_string(tmp_path):
    first = {"pom.xml": VERSION_BUMP["pom.xml"]}
    second = {"studio/package.json": VERSION_BUMP["studio/package.json"], "server.json": VERSION_BUMP["server.json"]}
    repo, base, head = _pair(tmp_path, first, second)
    out = _out(tmp_path)
    r = _run(repo, base, head, out)
    assert r.returncode == 1
    md = (out / "equiv.md").read_text()
    assert f"RESULT: REFUSED {NEW} pin={base} equivalent={head} version_string_lines=6 non_version_lines=0" in md
    assert f"(`git log {base[:10]}..{head[:10]}`): 2" in md
    assert "REFUSED: 0 non-version changed lines, 2 commits between the two" in r.stderr
    assert not (out / "equiv.json").exists()


def test_a_dev_version_is_refused_before_anything_is_written(tmp_path):
    repo, base, head = _pair(tmp_path)
    out = _out(tmp_path)
    r = _run(repo, base, head, out, release=f"{NEW}.dev0")
    assert r.returncode == 1 and "REFUSING: the equivalence is for a RELEASE pair" in r.stderr
    assert list(out.iterdir()) == []


# ---- the classification itself (a -U0 diff of one line pair)
def _one_pair(removed, added):
    return f"diff --git a/pom.xml b/pom.xml\nindex 1111111..2222222 100644\n--- a/pom.xml\n+++ b/pom.xml\n@@ -3 +3 @@\n-{removed}\n+{added}\n"


def test_snapshot_is_an_optional_suffix_of_the_release_strings_and_nothing_else():
    def version_lines(removed, added):
        ver, non = M.classify(_one_pair(removed, added), OLD, NEW)
        return ver, len(non)

    assert version_lines(f"<version>{NEW}-SNAPSHOT</version>", f"<version>{NEW}</version>") == (2, 0)           # the release commit drops the suffix
    assert version_lines(f"<version>{OLD}-SNAPSHOT</version>", f"<version>{NEW}-SNAPSHOT</version>") == (2, 0)  # the suffix on both sides
    assert version_lines(f'"version": "{OLD}",', f'"version": "{NEW}",') == (2, 0)
    assert version_lines(f"image: arcadedata/arcadedb:{OLD}", f"image: arcadedata/arcadedb:{NEW}") == (2, 0)
    assert version_lines(f"<version>{NEW}-SNAPSHOT</version>", "<version>26.12.2-SNAPSHOT</version>") == (0, 2)  # a third version is a real change
    assert version_lines(f"<version>{NEW}-SNAPSHOT</version>", f"<version>{NEW}-RC1</version>") == (0, 2)       # only -SNAPSHOT is optional
    assert version_lines(f"<version>{NEW}</version><name>a</name>", f"<version>{NEW}</version><name>b</name>") == (0, 2)   # same version, other text


# ---- --help and the exit status
def test_help_documents_every_argument_and_the_exit_status_and_a_missing_argument_exits_2():
    r = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True, env=ENV, timeout=60)
    assert r.returncode == 0
    for flag in ("--repo", "--base", "--head", "--release", "--old-release", "--status", "--out-md", "--out-json", "--evidence"):
        assert flag in r.stdout, flag
    assert "CLASSIFICATION" in r.stdout and "EXIT STATUS" in r.stdout and "exactly one commit" in r.stdout
    r = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, env=ENV, timeout=60)
    assert r.returncode == 2 and "--repo" in r.stderr
