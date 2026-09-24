import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / ".claude" / "skills" / "comment-audit" / "comment-audit.py"


def load_comment_audit() -> ModuleType:
    # the script's hyphenated filename is not importable by name
    spec = importlib.util.spec_from_file_location("comment_audit", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_git_env() -> dict[str, str]:
    # keep the developer's global config (commit signing, hooks) out of the throwaway repos
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "COMMENT_GATE_", "CLAUDE_"))}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    return env


def git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 -- fixed git argv in a temp repo
        ["git", *args],  # noqa: S607 -- git is resolved from PATH like everywhere else in the suite
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=isolated_git_env(),
    ).stdout.strip()


def commit_file(repo: Path, name: str, content: str) -> str:
    _ = (repo / name).write_text(content, encoding="utf-8")
    _ = git(repo, "add", name)
    _ = git(repo, "commit", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path: Path, *, mode: str = "block") -> Path:
    """Build a repo whose main is pushed to a bare origin, with the gate configured to `mode`."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    repo.mkdir()
    _ = git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _ = git(repo, "init", "-b", "main")
    _ = git(repo, "remote", "add", "origin", str(origin))
    config = repo / ".config" / "claude"
    config.mkdir(parents=True)
    _ = (config / "comment-audit.toml").write_text(f'mode = "{mode}"\n', encoding="utf-8")
    _ = git(repo, "add", ".config")
    _ = git(repo, "commit", "-m", "init")
    _ = git(repo, "push", "-u", "origin", "main")
    return repo


def run_gate(command: str, *, cwd: Path, project_dir: Path) -> subprocess.CompletedProcess[str]:
    payload = {"tool_input": {"command": command}, "cwd": str(cwd)}
    env = isolated_git_env()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(  # noqa: S603 -- our own script
        [sys.executable, str(SCRIPT_PATH), "gate"],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
