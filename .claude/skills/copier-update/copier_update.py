#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Helper for the copier-update skill.

Verbs (all print JSON on stdout; errors go to stderr with exit 1):

  find-answers [project]             locate .copier-answers*.y(a)ml and report the current
                                     and default branch, uncommitted paths and update tasks
  branch [project] [--ref R]         refuse a dirty tree, then create chore/template-<R> (or
                                     --name) off the fresh default branch, in place or in a
                                     new --worktree
  refs [project]                     fetch the template and list its newest release tag,
                                     its default branch and its most recently committed
                                     other branches
  new-questions [project] --ref REF  questions in REF's copier.yml that are neither in the
                                     current `_commit`'s copier.yml nor already answered
  update [project] [--ref REF]       run the project's `task copier-update` (or
                                     `copier-update-from-ref` when REF is given); with --data,
                                     run the task's own `copier update` line (read with
                                     `task --dry`) plus those flags instead, then confirm each
                                     value landed in the answers file. Refuses on the default
                                     branch, and while a new question with no default has no
                                     --data answer
  conflicts [project]                run `task prune-copier-rejects`, then list the .rej
                                     files left and any inline conflict markers
  capture-rej REJ [--root DIR]       emit the report schema's `rejFile` object for one .rej
  lint [project]                     sync each uv project (so a dependency-sync hook has nothing
                                     to change), then run the all-files hook runner the way CI does
  commit [project] --draft DRAFT     refuse while any resolution in the draft is below high
                                     confidence (unless --approved names it) or the message's
                                     first paragraph spans more than one line, stage everything
                                     but tmp/, refuse conflict artefacts, commit
  report [project] DRAFT             record the commits made since the draft's project_commit,
                                     validate the draft against report.schema.json, then
                                     write the JSON report and a self-contained .html to tmp/
  pr [project] --title T --body-file F   push the branch and print the `gh pr create` command for
                                     the agent to run itself, so the permission settings decide it
  comment-report [project] --report R   once that PR is open, post the report on it as a comment

Any verb that takes a project and fails also writes <project>/tmp/copier-update-aborted.json
({verb, error, at}) so a headless run leaves a machine-readable trace of why it stopped.

The template clone is a `--mirror` in a cache dir (default $TMPDIR/copier-update-cache) so
`refs` and `new-questions` share one fetch.

`--stored-gh-credentials` (on `refs`, `new-questions`, `update`, `pr` and `comment-report`) removes GITHUB_TOKEN
and GH_TOKEN from the environment of every git, gh and task call (and prefixes the command `pr`
prints with `env -u GITHUB_TOKEN -u GH_TOKEN`), so they fall back to the
credentials `gh auth login` stored. In a GitHub Codespace the injected token only reaches the
codespace's own repository.
"""

import argparse
import base64
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("report.schema.json")
VIEWER_PATH = Path(__file__).with_name("report.html")
ANSWERS_GLOB = ".copier-answers*.y*ml"
COPIER_FILES = ("copier.yml", "copier.yaml")
UPDATE_TASK = "copier-update"
UPDATE_FROM_REF_TASK = "copier-update-from-ref"
PRUNE_TASK = "prune-copier-rejects"
PRE_COMMIT_CONFIGS = (".pre-commit-config.yaml", ".pre-commit-config.yml")
# git-dirty fails whenever anything is uncommitted, which is always true before the update
# commit; CI's own lint run skips it for the same reason
LINT_SKIP = "git-dirty"
_SHORTHANDS = {"gh:": "https://github.com/", "gl:": "https://gitlab.com/"}


class FailError(Exception):
    pass


def _env(*, stored_gh_credentials: bool) -> dict[str, str]:
    env = dict(os.environ)
    if stored_gh_credentials:
        _ = env.pop("GITHUB_TOKEN", None)
        _ = env.pop("GH_TOKEN", None)
    return env


def _run(
    *, cmd: list[str], cwd: Path, stored_gh_credentials: bool = False, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = _env(stored_gh_credentials=stored_gh_credentials)
    if extra_env is not None:
        env.update(extra_env)
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, check=False)  # noqa: S603 # argv lists, never a shell; the variable parts come from this script's own CLI arguments and the project's task output
    except FileNotFoundError as e:
        # a missing tool is a failed run like any other, so a caller that already changed the tree still reports it
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=str(e))


def _git(*args: str, cwd: Path, stored_gh_credentials: bool = False, extra_env: dict[str, str] | None = None) -> str:
    res = _run(cmd=["git", *args], cwd=cwd, stored_gh_credentials=stored_gh_credentials, extra_env=extra_env)
    if res.returncode != 0:
        raise FailError(f"git {' '.join(args)} failed in {cwd}:\n{res.stderr.strip()}")
    return res.stdout


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def resolve_src_url(src_path: str) -> str:
    for prefix, base in _SHORTHANDS.items():
        if src_path.startswith(prefix):
            rest = src_path.removeprefix(prefix)
            if not rest.endswith(".git"):
                rest += ".git"
            return base + rest
    return src_path


_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][\w-]*):(?:[ \t]+(.*))?$")


def _top_level_values(text: str) -> dict[str, str]:
    """Map each top-level key of a YAML file to the raw text of its value, without parsing YAML.

    Everything read here sits at the top level. Copier writes an answers file as one `key: value` line per answer,
    with a list's items on the lines below it, and copier.yml puts each question at the top level with its settings
    indented below. So a key's value is the rest of its line plus every line under it up to the next top-level key.
    Values are compared as text, never interpreted. A later document (after `---`) overrides an earlier one, as
    copier merges them; a line such as `!include other.yml` is not a key and is skipped.
    """
    values: dict[str, list[str]] = {}
    key: str | None = None
    for line in text.splitlines():
        if line.startswith("---"):
            key = None
            continue
        match = _TOP_LEVEL_KEY.match(line)
        if match is not None:
            key = match.group(1)
            values[key] = [match.group(2) or ""]
            continue
        if key is None:
            continue
        if line.startswith("#"):
            continue
        values[key].append(line)
    return {name: "\n".join(lines).rstrip() for name, lines in values.items()}


def _scalar(raw: str) -> str:
    # an answer on one line, without the quotes YAML may have put around it
    first, __, rest = raw.partition("\n")
    if first and rest and not first.startswith(("|", ">")):
        # a long value YAML wrapped onto indented lines reads as one line joined by spaces
        raw = " ".join([first, *(line.strip() for line in rest.splitlines())])
    if "\n" in raw:
        return raw
    if len(raw) < 2:  # noqa: PLR2004 # a quoted value has at least its two quotes
        return raw
    if raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    if raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    return raw


def question_names(copier_yaml: str) -> list[str]:
    return [name for name in _top_level_values(copier_yaml) if not name.startswith("_")]


def _question_info(*, name: str, spec: str) -> dict[str, Any]:
    inline, __, settings = spec.partition("\n")
    if inline:
        # `name: # ...` is YAML's null with a comment after it, not a default
        if not inline.startswith("#"):
            # `name: value` is copier's short form for a question whose default is that value
            return {"name": name, "spec": inline, "has_default": True}
    settings = textwrap.dedent(settings)
    return {
        "name": name,
        "spec": settings,
        "has_default": re.search(r"^default\s*:", settings, flags=re.MULTILINE) is not None,
    }


def diff_questions(*, old_yaml: str, new_yaml: str, answered: set[str]) -> dict[str, list[Any]]:
    new = _top_level_values(new_yaml)
    old_names = set(question_names(old_yaml))
    added: list[dict[str, Any]] = []
    for name in question_names(new_yaml):
        if name in old_names:
            continue
        if name in answered:
            continue
        added.append(_question_info(name=name, spec=new[name]))
    removed = [n for n in old_names if n not in new]
    return {"new": added, "removed": sorted(removed)}


def count_hunks(rej_text: str) -> int:
    return len(re.findall(r"^@@ ", rej_text, flags=re.MULTILINE))


def capture_rej(*, path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        contents, encoding = raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        contents, encoding = base64.b64encode(raw).decode("ascii"), "base64"
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    return {
        "path": rel,
        "contents": contents,
        "encoding": encoding,
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "truncated": False,
        "hunk_count": count_hunks(raw.decode("utf-8", errors="replace")),
    }


def find_answers_files(project: Path) -> list[str]:
    # git honours local + global ignores and never descends into nested repos, so the
    # visible files are exactly the ones that could belong to this project
    out = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=project)
    hits: list[str] = []
    for rel in (Path(p) for p in out.split("\0") if p):
        if not fnmatch.fnmatch(rel.name, ANSWERS_GLOB):
            continue
        if not (project / rel).is_file():
            continue
        hits.append(rel.as_posix())
    return sorted(hits, key=lambda r: (r.count("/"), r))


def resolve_answers_file(*, project: Path, answers_file: str | None) -> str:
    if answers_file is not None:
        return answers_file
    found = find_answers_files(project)
    if len(found) == 1:
        return found[0]
    if not found:
        raise FailError(
            f"no {ANSWERS_GLOB} under {project}; check the README for where the template keeps it "
            "and pass --answers-file"
        )
    raise FailError("several answers files; pass --answers-file to pick one:\n  " + "\n  ".join(found))


def default_branch(project: Path) -> str:
    res = _run(cmd=["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=project)
    if res.returncode != 0:
        # guessing main or master would let the default-branch guard pass on a repo whose default is something else
        raise FailError(
            f"origin/HEAD is not set in {project}, so its default branch is unknown; "
            "run `git remote set-head origin --auto` there first"
        )
    return res.stdout.strip().split("/", 1)[-1]


def current_branch(project: Path) -> str | None:
    res = _run(cmd=["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=project)
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def guard_not_default_branch(project: Path) -> dict[str, str]:
    default = default_branch(project)
    branch = current_branch(project)
    if branch is None:
        raise FailError("HEAD is detached; check out a working branch for the update first")
    if branch == default:
        raise FailError(
            f"on the default branch '{default}': create a branch (or worktree) for the template update first"
        )
    return {"branch": branch, "default_branch": default}


def read_answers(*, project: Path, answers_file: str | None) -> tuple[str, dict[str, str]]:
    rel = resolve_answers_file(project=project, answers_file=answers_file)
    path = project / rel
    if not path.is_file():
        raise FailError(f"answers file not found: {path}")
    data = {key: _scalar(value) for key, value in _top_level_values(path.read_text(encoding="utf-8")).items()}
    if "_src_path" not in data:
        raise FailError(f"{path} has no _src_path")
    if _is_relative_local_path(data["_src_path"]):
        # copier reads a relative template path from the project; the mirror is cloned from elsewhere
        data["_src_path"] = str((project / data["_src_path"]).resolve())
    return rel, data


def _is_relative_local_path(src_path: str) -> bool:
    for prefix in _SHORTHANDS:
        if src_path.startswith(prefix):
            return False
    if "://" in src_path:
        return False
    if re.match(r"^[\w.-]+@[\w.-]+:", src_path) is not None:
        # scp-style ssh, such as git@github.com:owner/repo.git
        return False
    if Path(src_path).is_absolute():
        return False
    return True


def template_mirror(*, src_path: str, cache_dir: str | None, stored_gh_credentials: bool) -> Path:
    url = resolve_src_url(src_path)
    # the clone runs from the cache directory's parent, so a relative --cache-dir would be read from there
    cache_root = Path(cache_dir).resolve() if cache_dir else Path(tempfile.gettempdir()) / "copier-update-cache"
    dest = cache_root / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".git")
    if dest.is_dir():
        _ = _git("fetch", "--prune", "--tags", "--quiet", cwd=dest, stored_gh_credentials=stored_gh_credentials)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["clone", "--mirror", "--quiet"]
    if "://" in url:
        args.append("--filter=blob:none")
    _ = _git(*args, url, str(dest), cwd=dest.parent, stored_gh_credentials=stored_gh_credentials)
    return dest


def show_file(*, mirror: Path, ref: str, stored_gh_credentials: bool) -> str:
    errors: list[str] = []
    for name in COPIER_FILES:
        try:
            # a --filter=blob:none mirror fetches the blob from the template repo here, which needs the same credentials
            return _git("show", f"{ref}:{name}", cwd=mirror, stored_gh_credentials=stored_gh_credentials)
        except FailError as e:
            errors.append(str(e))
    raise FailError(f"no {'/'.join(COPIER_FILES)} at {ref}:\n" + "\n".join(errors))


def project_tasks(project: Path) -> set[str]:
    if shutil.which("task") is None:
        return set()
    res = _run(cmd=["task", "--list-all", "--json"], cwd=project)
    if res.returncode != 0:
        return set()
    return {t["name"] for t in json.loads(res.stdout).get("tasks", [])}


def copier_version(project: Path) -> str | None:
    res = _run(cmd=["copier", "--version"], cwd=project)
    if res.returncode != 0:
        return None
    match = re.search(r"\d+(\.\d+)+", res.stdout)
    if match is None:
        return res.stdout.strip()
    return match.group(0)


def dirty_paths(project: Path) -> list[str]:
    return [line for line in _git("status", "--porcelain", cwd=project).splitlines() if line]


def cmd_find_answers(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    return {
        "answers_files": find_answers_files(project),
        "branch": current_branch(project),
        "default_branch": default_branch(project),
        "dirty": dirty_paths(project),
        "tasks": sorted(project_tasks(project) & {UPDATE_TASK, UPDATE_FROM_REF_TASK, PRUNE_TASK}),
    }


def cmd_branch(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    dirty = dirty_paths(project)
    if dirty:
        raise FailError("the tree has uncommitted changes; commit them or set them aside first:\n" + "\n".join(dirty))
    default = default_branch(project)
    name = a.name
    if name is None:
        name = "chore/template-" + re.sub(r"[^A-Za-z0-9._-]+", "-", a.ref).strip("-")
    _ = _git("fetch", "--quiet", "origin", default, cwd=project)
    if a.worktree is None:
        _ = _git("switch", "-c", name, f"origin/{default}", cwd=project)
        path = project
    else:
        # git runs in the project, so a relative --worktree is resolved here first, from where the command was typed
        path = Path(a.worktree).resolve()
        _ = _git("worktree", "add", "-b", name, str(path), f"origin/{default}", cwd=project)
    return {"branch": name, "path": str(path.resolve()), "base": f"origin/{default}"}


def cmd_refs(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    answers_file, answers = read_answers(project=project, answers_file=a.answers_file)
    mirror = template_mirror(
        src_path=answers["_src_path"], cache_dir=a.cache_dir, stored_gh_credentials=a.stored_gh_credentials
    )
    default = _git("symbolic-ref", "--short", "HEAD", cwd=mirror).strip()
    fmt = "%(refname:short)%00%(objectname:short)%00%(committerdate:iso-strict)%00%(subject)"
    branches: dict[str, dict[str, str]] = {}
    for line in _git(
        "for-each-ref", "--sort=-committerdate", f"--format={fmt}", "refs/heads/", cwd=mirror
    ).splitlines():
        name, sha, date, subject = line.split("\0", 3)
        branches[name] = {"name": name, "sha": sha, "date": date, "subject": subject}
    tags = release_tags(mirror)
    latest_tag = None
    if tags:
        latest_tag = {"name": tags[0], "sha": _git("rev-parse", "--short", f"{tags[0]}^{{commit}}", cwd=mirror).strip()}
    recent = [b for n, b in branches.items() if n != default][: a.count]
    return {
        "answers_file": answers_file,
        "src_path": answers["_src_path"],
        "url": resolve_src_url(answers["_src_path"]),
        "current_commit": answers.get("_commit"),
        "latest_tag": latest_tag,
        "default_branch": branches.get(default),
        "recent_branches": recent,
    }


def cmd_new_questions(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    answers_file, answers = read_answers(project=project, answers_file=a.answers_file)
    current = answers.get("_commit")
    if not current:
        raise FailError("answers file has no _commit; cannot diff copier.yml against the current version")
    mirror = template_mirror(
        src_path=answers["_src_path"], cache_dir=a.cache_dir, stored_gh_credentials=a.stored_gh_credentials
    )
    diff = diff_questions(
        old_yaml=show_file(mirror=mirror, ref=current, stored_gh_credentials=a.stored_gh_credentials),
        new_yaml=show_file(mirror=mirror, ref=a.ref, stored_gh_credentials=a.stored_gh_credentials),
        answered={str(k) for k in answers if not str(k).startswith("_")},
    )
    return {
        "answers_file": answers_file,
        "from_ref": current,
        "to_ref": a.ref,
        "new": diff["new"],
        "removed": diff["removed"],
        "data_flags": [f"--data {q['name']}=<VALUE>" for q in diff["new"]],
    }


def _parse_data(data: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for kv in data:
        if "=" not in kv:
            raise FailError(f"--data expects KEY=VALUE, got {kv!r}")
        key, value = kv.split("=", 1)
        parsed[key] = value
    return parsed


def task_copier_command(*, project: Path, task_name: str, task_vars: list[str]) -> list[str]:
    """Read the `copier update` line the project's update task would run, without running it.

    The task is the source of truth for the flags this template family relies on. When
    answers have to be passed in, the update runs this exact line with `--data` flags
    appended, instead of a hand-assembled copier command.
    """
    res = _run(cmd=["task", "--dry", task_name, *task_vars], cwd=project)
    if res.returncode != 0:
        raise FailError(f"task --dry {task_name} failed:\n{(res.stdout + res.stderr).strip()}")
    # task echoes each command it would run to stderr
    output = res.stderr + res.stdout
    for line in output.splitlines():
        command = re.sub(r"^task: \[[^\]]+\] ", "", line).strip()
        if command.startswith("copier update"):
            return shlex.split(command)
    raise FailError(f"`task --dry {task_name}` printed no `copier update` line:\n{output.strip()}")


def _copier_answers_file(command: list[str]) -> str:
    for index, arg in enumerate(command):
        if arg == "--answers-file":
            return command[index + 1]
        if arg == "-a":
            return command[index + 1]
        if arg.startswith("--answers-file="):
            return arg.removeprefix("--answers-file=")
    return ".copier-answers.yml"


def unanswerable_questions(
    *, answers: dict[str, Any], ref: str, answered: set[str], a: argparse.Namespace
) -> list[str]:
    mirror = template_mirror(
        src_path=answers["_src_path"], cache_dir=a.cache_dir, stored_gh_credentials=a.stored_gh_credentials
    )
    current = answers.get("_commit")
    if not current:
        raise FailError("answers file has no _commit; cannot tell which template questions are new")
    diff = diff_questions(
        old_yaml=show_file(mirror=mirror, ref=current, stored_gh_credentials=a.stored_gh_credentials),
        new_yaml=show_file(mirror=mirror, ref=ref, stored_gh_credentials=a.stored_gh_credentials),
        answered={str(k) for k in answers if not str(k).startswith("_")},
    )
    missing: list[str] = []
    for question in diff["new"]:
        if question["has_default"]:
            continue
        if question["name"] in answered:
            continue
        if re.search(r"^when\s*:", question["spec"], flags=re.MULTILINE) is not None:
            # copier skips such a question while its `when` is false, and leaves an answer to it out of the answers
            # file; while true, `copier update --defaults` stops with "is required" before it renders anything
            continue
        missing.append(question["name"])
    return missing


_RELEASE_TAG = re.compile(r"^v?\d+(\.\d+)*$")


def release_tags(mirror: Path) -> list[str]:
    """List the template's release tags, newest first: the ones copier picks its default target from.

    Copier updates to the newest PEP 440 release and skips prereleases, while `git tag --sort=-v:refname` puts
    `v1.2.0-rc1` ahead of `v1.2.0`, sorts tags such as `latest` in with the versions, and ranks every `v` tag apart
    from the unprefixed ones. So this keeps the release-shaped tags and orders them by their numbers.
    """
    tags: list[str] = []
    for tag in _git("tag", cwd=mirror).split():
        if _RELEASE_TAG.match(tag) is None:
            continue
        tags.append(tag)
    return sorted(tags, key=lambda tag: tuple(int(part) for part in tag.removeprefix("v").split(".")), reverse=True)


def latest_tag(*, answers: dict[str, Any], a: argparse.Namespace) -> str:
    mirror = template_mirror(
        src_path=answers["_src_path"], cache_dir=a.cache_dir, stored_gh_credentials=a.stored_gh_credentials
    )
    tags = release_tags(mirror)
    if not tags:
        raise FailError("the template has no tags; pass --ref")
    return tags[0]


def update_command(
    *, project: Path, task_name: str, task_vars: list[str], data: dict[str, str], data_file: str | None
) -> list[str]:
    if not data and data_file is None:
        return ["task", task_name, *task_vars]
    cmd = task_copier_command(project=project, task_name=task_name, task_vars=task_vars)
    for key, value in data.items():
        cmd += ["--data", f"{key}={value}"]
    if data_file is not None:
        cmd += ["--data-file", data_file]
    return cmd


def cmd_update(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    where = guard_not_default_branch(project)
    answers_file, answers = read_answers(project=project, answers_file=a.answers_file)
    tasks = project_tasks(project)
    if a.ref is None:
        task_name, task_vars, target_ref = UPDATE_TASK, [], latest_tag(answers=answers, a=a)
    else:
        task_name, task_vars, target_ref = UPDATE_FROM_REF_TASK, [f"REF={a.ref}"], a.ref
    if task_name not in tasks:
        raise FailError(
            f"the project has no `task {task_name}`; this skill only updates through the project's own task"
        )
    task_answers_file = _copier_answers_file(
        task_copier_command(project=project, task_name=task_name, task_vars=task_vars)
    )
    if Path(task_answers_file) != Path(answers_file):
        # the task would update another template's instance while this checks and reports the selected one
        raise FailError(
            f"`task {task_name}` updates {task_answers_file}, not the selected {answers_file}; "
            "this skill only updates the instance the project's own task updates"
        )
    data = _parse_data(a.data)
    answered = set(data)
    if a.data_file is not None:
        # only the keys: the values stay in the file, which copier reads from the project directory
        answered |= set(_top_level_values((project / a.data_file).read_text(encoding="utf-8")))
    missing = unanswerable_questions(answers=answers, ref=target_ref, answered=answered, a=a)
    if missing:
        raise FailError(
            f"new template questions with no default need an answer via --data or --data-file: {', '.join(missing)}"
        )
    cmd = update_command(project=project, task_name=task_name, task_vars=task_vars, data=data, data_file=a.data_file)
    res = _run(cmd=cmd, cwd=project, stored_gh_credentials=a.stored_gh_credentials)
    _, new_answers = read_answers(project=project, answers_file=answers_file)
    # TODO: consider comparing by parsed value: copier saves `--data enabled=True` (or `yes`) as `true`, which this
    # text comparison reports as dropped, so for now a boolean has to be passed the way copier writes it
    dropped = [k for k, v in data.items() if str(new_answers.get(k)) != v]
    if res.returncode == 0 and dropped:
        raise FailError(f"copier ran but these --data answers did not reach {answers_file}: {', '.join(dropped)}")
    changed = [
        str(key)
        for key in sorted(set(answers) | set(new_answers))
        if not str(key).startswith("_") and answers.get(key) != new_answers.get(key)
    ]
    conflicts = sorted(
        {m.group(1) for m in re.finditer(r"^\s*conflict\s+(\S+)", res.stdout + res.stderr, flags=re.MULTILINE)}
    )
    return {
        **where,
        "command": cmd,
        "copier_version": copier_version(project),
        "returncode": res.returncode,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "from_version": answers.get("_commit"),
        "to_version": new_answers.get("_commit"),
        "answers_file": answers_file,
        "answers_changed": changed,
        "conflicts": conflicts,
    }


def find_conflict_markers(project: Path) -> list[dict[str, Any]]:
    # only the labelled forms: a bare ======= is a legitimate RST/Markdown underline, and git
    # always writes the outer markers with a trailing space and a label
    res = _run(
        cmd=["git", "grep", "-n", "-I", "-E", "--untracked", r"^(<{7} |>{7} )", "--", ".", ":!*.rej"],
        cwd=project,
    )
    if res.returncode > 1:
        raise FailError(f"git grep failed:\n{res.stderr.strip()}")
    hits: list[dict[str, Any]] = []
    for line in res.stdout.splitlines():
        path, lineno, text = line.split(":", 2)
        hits.append({"path": path, "line": int(lineno), "text": text})
    return hits


def list_rej_files(project: Path) -> list[dict[str, Any]]:
    rejs: list[dict[str, Any]] = []
    for p in sorted(project.rglob("*.rej")):
        parts = p.relative_to(project).parts
        if ".git" in parts:
            continue
        if "node_modules" in parts:
            continue
        rel = p.relative_to(project).as_posix()
        rejs.append(
            {
                "path": rel,
                "target": rel.removesuffix(".rej"),
                "hunk_count": count_hunks(p.read_text(encoding="utf-8", errors="replace")),
            }
        )
    return rejs


def cmd_conflicts(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    if PRUNE_TASK not in project_tasks(project):
        raise FailError(f"the project has no `task {PRUNE_TASK}`")
    # the task exits non-zero while real conflicts remain: that is the answer, not a failure
    res = _run(cmd=["task", PRUNE_TASK], cwd=project)
    output = (res.stdout + res.stderr).strip()
    rej_files = list_rej_files(project)
    # a crash also exits non-zero, and would leave false positives listed as real conflicts
    if "Traceback (most recent call last)" in output:
        raise FailError(f"`task {PRUNE_TASK}` crashed, so the .rej files left may not all be real conflicts:\n{output}")
    if res.returncode != 0:
        # a task that failed before the script ran pruned nothing, so its .rej files may still hold false positives
        if "Remaining .rej conflicts:" not in output:
            raise FailError(f"`task {PRUNE_TASK}` failed without listing the conflicts it left:\n{output}")
    return {
        "prune_output": output,
        "prune_returncode": res.returncode,
        "rej_files": rej_files,
        "conflict_markers": find_conflict_markers(project),
    }


def cmd_capture_rej(a: argparse.Namespace) -> dict[str, Any]:
    return capture_rej(path=Path(a.rej), root=Path(a.root))


def detect_lint(project: Path) -> dict[str, Any] | None:
    for cfg in PRE_COMMIT_CONFIGS:
        if (project / cfg).is_file():
            return {"command": ["pre-commit", "run", "--all-files"], "config": cfg, "skip": LINT_SKIP}
    return None


def uv_lock_dirs(project: Path) -> list[Path]:
    dirs: list[Path] = []
    for tracked in _git("ls-files", "-z", cwd=project).split("\0"):
        if not tracked:
            continue
        if Path(tracked).name != "uv.lock":
            continue
        dirs.append(project / Path(tracked).parent)
    return dirs


def sync_uv_projects(project: Path) -> dict[str, list[str]]:
    """Run `uv sync --frozen` wherever a uv.lock is tracked, so a dependency-sync hook finds nothing to change.

    Such a hook fails whenever its sync installed or removed anything, which is the case after every fresh clone
    and every copier update, so without this the first lint of a checkout always failed and the second passed.
    `synced` names the directories whose environment changed; `sync_failed` carries uv's error for the rest.
    """
    synced: list[str] = []
    failed: list[str] = []
    for lock_dir in uv_lock_dirs(project):
        name = str(lock_dir.relative_to(project))
        res = _run(cmd=["uv", "sync", "--frozen"], cwd=lock_dir)
        if res.returncode != 0:
            failed.append(f"{name}: {res.stderr.strip()}")
            continue
        if "Installed" in res.stderr:
            synced.append(name)
        elif "Uninstalled" in res.stderr:
            synced.append(name)
    return {"synced": synced, "sync_failed": failed}


def cmd_lint(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    lint = detect_lint(project)
    if lint is None:
        return {"command": None, "reason": "no pre-commit config in project"}
    sync = sync_uv_projects(project)
    res = _run(cmd=lint["command"], cwd=project, extra_env={"SKIP": lint["skip"]})
    hooks = parse_hook_results(res.stdout + res.stderr)
    return {**lint, **sync, "returncode": res.returncode, **hooks, "stdout": res.stdout, "stderr": res.stderr}


def parse_hook_results(output: str) -> dict[str, list[str]]:
    """Find the hooks that failed or rewrote files, and pre-commit's own errors, in a pre-commit run's output.

    Each failing hook prints a `<name>....Failed` line followed by `- key: value` lines (`hook id`, `duration`
    for verbose hooks, `exit code`, `files were modified by this hook`), in no fixed order. A hook that only
    rewrote files is a mechanical fix; one with an exit code needs a hand-made fix.
    """
    failed: list[str] = []
    modified: list[str] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not line.rstrip().endswith("Failed"):
            continue
        block: list[str] = []
        for detail in lines[index + 1 :]:
            if not detail.startswith("- "):
                break
            block.append(detail)
        hook_id = next(
            (d.removeprefix("- hook id: ") for d in block if d.startswith("- hook id: ")), line.split(".")[0]
        )
        if any(d.startswith("- exit code") for d in block):
            failed.append(hook_id)
        if "- files were modified by this hook" in block:
            modified.append(hook_id)
    errors = [line for line in lines if line.startswith("[ERROR]")]
    return {"failed_hooks": failed, "modifying_hooks": modified, "pre_commit_errors": errors}


def unconfident_resolutions(*, draft: dict[str, Any], approved: set[str]) -> list[dict[str, Any]]:
    held: list[dict[str, Any]] = []
    for resolution in draft.get("resolutions", []):
        if resolution.get("confidence") == "high":
            continue
        if resolution.get("filename") in approved:
            continue
        held.append(
            {
                "filename": resolution.get("filename"),
                "confidence": resolution.get("confidence"),
                "reason": resolution.get("reason"),
            }
        )
    return held


def subject_lines(message: str) -> list[str]:
    paragraph: list[str] = []
    for line in message.splitlines():
        if line.strip():
            paragraph.append(line)
            continue
        if paragraph:
            break
    return paragraph


def require_one_line_subject(message_file: Path) -> None:
    subject = subject_lines(message_file.read_text(encoding="utf-8"))
    if len(subject) > 1:
        raise FailError(
            "the message's first paragraph spans more than one line, which git joins into one long subject; "
            "put a blank line after the subject line:\n  " + "\n  ".join(subject)
        )


def _require_pre_commit_hook(project: Path) -> None:
    # the commit runs every hook not in --skip only through the git hook, so without it nothing would be checked
    hook = project / _git("rev-parse", "--git-path", "hooks/pre-commit", cwd=project).strip()
    if not hook.is_file():
        raise FailError(f"no pre-commit git hook installed in {project}; run `prek install` or `pre-commit install`")
    if not os.access(hook, os.X_OK):
        raise FailError(
            f"the pre-commit git hook in {project} is not executable, so git would skip it; run `prek install` or"
            " `pre-commit install` again"
        )


def cmd_commit(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    where = guard_not_default_branch(project)
    _require_pre_commit_hook(project)
    require_one_line_subject(Path(a.message_file))
    draft = json.loads(Path(a.draft).read_text(encoding="utf-8"))
    # the confidence gate reads `filename` and `confidence`; a draft with other keys would pass it unchecked
    errors = validate_report(draft)
    if errors:
        raise FailError(
            "the draft does not match report.schema.json, so its confidences can't be checked:\n" + "\n".join(errors)
        )
    held = unconfident_resolutions(draft=draft, approved=set(a.approved))
    if held:
        raise FailError(
            "resolutions below high confidence need the user's decision before committing "
            "(rerun with --approved FILE once they have decided):\n"
            + "\n".join(f"  {h['filename']} ({h['confidence']}): {h['reason']}" for h in held)
        )
    # stage everything, then unstage tmp/: a ":!tmp" pathspec on a gitignored tmp/ makes
    # git exit 1 with addIgnoredFile advice
    _ = _git("add", "-A", "--", ".", cwd=project)
    _ = _git("reset", "-q", "--", "tmp", cwd=project)
    staged = [p for p in _git("diff", "--cached", "--name-only", "-z", cwd=project).split("\0") if p]
    if not staged:
        raise FailError("nothing staged: did the update run?")
    # deleting a tracked artifact removes it from the tree, so only paths the commit adds or changes are checked
    kept = [p for p in _git("diff", "--cached", "--name-only", "--diff-filter=d", "-z", cwd=project).split("\0") if p]
    leftovers: list[str] = []
    for path in kept:
        if path.endswith((".rej", ".orig")):
            leftovers.append(path)
            continue
        if "node_modules" in Path(path).parts:
            # a node_modules symlink made to run hooks in a worktree is not ignored by a
            # `node_modules/` rule, which only matches directories
            leftovers.append(path)
    if leftovers:
        _ = _git("reset", "-q", cwd=project)
        raise FailError("refusing to commit these paths:\n  " + "\n  ".join(leftovers))
    markers = [m for m in find_conflict_markers(project) if m["path"] in staged]
    if markers:
        _ = _git("reset", "-q", cwd=project)
        raise FailError(
            "refusing to commit inline conflict markers:\n  " + "\n  ".join(f"{m['path']}:{m['line']}" for m in markers)
        )
    # git runs in the project, so a relative --message-file is resolved here first, from where the command was typed
    message_file = str(Path(a.message_file).resolve())
    _ = _git("commit", "-q", "-F", message_file, cwd=project, extra_env={"SKIP": ",".join(a.skip)})
    return {
        **where,
        "sha": _git("rev-parse", "HEAD", cwd=project).strip(),
        "subject": _git("log", "-1", "--format=%s", cwd=project).strip(),
        "files": staged,
        "skipped_hooks": a.skip,
    }


def _resolved(*, spec: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    # the schema's only references are to its own definitions, "#/$defs/<name>"
    ref = spec.get("$ref")
    if ref is None:
        return spec
    return defs[ref.removeprefix("#/$defs/")]


def _object_errors(*, value: object, spec: dict[str, Any], path: str, defs: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: must be an object"]
    properties: dict[str, Any] = spec.get("properties", {})
    errors: list[str] = []
    if spec.get("additionalProperties") is False:
        errors += [
            f"{path}: unknown field {key!r}; the fields are {', '.join(properties)}"
            for key in value
            if key not in properties
        ]
    errors += [f"{path}: missing {key!r}" for key in spec.get("required", []) if key not in value]
    for key, field_value in value.items():
        field = _resolved(spec=properties.get(key, {}), defs=defs)
        errors += _field_errors(value=field_value, field=field, path=f"{path}/{key}", defs=defs)
    return errors + _conditional_errors(value=value, spec=spec, path=path)


def _scalar_errors(*, value: object, field: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    if "enum" in field and value not in field["enum"]:
        errors.append(f"{path}: {value!r} is not one of {', '.join(map(str, field['enum']))}")
    kind = field.get("type")
    # the report reads these for truthiness, where the string "false" counts as true
    if kind == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: must be true or false, not {value!r}")
    if kind == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: must be a string, not {value!r}")
    # bool is an int in Python, but not an integer in the schema
    if kind == "integer":
        if isinstance(value, bool):
            errors.append(f"{path}: must be a whole number, not {value!r}")
        elif not isinstance(value, int):
            errors.append(f"{path}: must be a whole number, not {value!r}")
    return errors


def _field_errors(*, value: object, field: dict[str, Any], path: str, defs: dict[str, Any]) -> list[str]:
    errors = _scalar_errors(value=value, field=field, path=path)
    # the report maps over these, and one that isn't a list stops the whole page rendering
    if field.get("type") == "array":
        if not isinstance(value, list):
            return [*errors, f"{path}: must be a list, not {value!r}"]
        if len(value) < field.get("minItems", 0):
            errors.append(f"{path}: needs at least {field['minItems']} item(s), not {len(value)}")
        items = _resolved(spec=field.get("items", {}), defs=defs)
        if "properties" in items:
            for index, item in enumerate(value):
                errors += _object_errors(value=item, spec=items, path=f"{path}/{index}", defs=defs)
    if "properties" in field:
        errors += _object_errors(value=value, spec=field, path=path, defs=defs)
    return errors


def _property_holds(*, field_value: object, constraint: dict[str, Any]) -> bool:
    if "const" in constraint:
        if field_value != constraint["const"]:
            return False
    if "enum" in constraint:
        if field_value not in constraint["enum"]:
            return False
    if "properties" in constraint:
        if not isinstance(field_value, dict):
            return False
        if not _condition_holds(value=field_value, condition=constraint):
            return False
    return True


def _condition_holds(*, value: dict[str, Any], condition: dict[str, Any]) -> bool:
    for key in condition.get("required", []):
        if key not in value:
            return False
    for key, constraint in condition.get("properties", {}).items():
        if key not in value:
            continue
        if not _property_holds(field_value=value[key], constraint=constraint):
            return False
    return True


def _conditional_errors(*, value: dict[str, Any], spec: dict[str, Any], path: str) -> list[str]:
    """Check an object against its schema's `allOf` if/then rules, such as an unfinished resolution's needs_review.

    Only the keywords those rules use are understood: `required`, and `const` or `enum` on a property, or, in an `if`,
    a property's own `properties` and `required`, for a rule on a field of a nested object such as `rej_file`.
    """
    errors: list[str] = []
    for rule in spec.get("allOf", []):
        if not _condition_holds(value=value, condition=rule["if"]):
            continue
        then: dict[str, Any] = rule["then"]
        errors += [
            f"{path}: missing {key!r}; {rule['description']}" for key in then.get("required", []) if key not in value
        ]
        for key, constraint in then.get("properties", {}).items():
            if key not in value:
                continue
            if "const" in constraint:
                if value[key] != constraint["const"]:
                    errors.append(f"{path}/{key}: must be {json.dumps(constraint['const'])}; {rule['description']}")
    return errors


def validate_report(report: object) -> list[str]:
    """Catch what a hand-written draft gets wrong: a misnamed, missing or misshapen field, or a value off its list.

    report.schema.json documents the whole shape, but checking all of it would take a JSON Schema library, and this
    script sticks to the standard library. These checks take the field names, the required fields and each field's
    allowed values from that schema, for the report and every object nested in it, through its `$defs` references
    and the items of its lists.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _object_errors(value=report, spec=schema, path="<root>", defs=schema["$defs"])


def render_report_html(report: dict[str, Any]) -> str:
    # the JSON sits inside a <script> block, where "</" ends it and "<!--" followed by "<script" keeps it from ending
    # at all, so no "<" appears literally; JSON reads < back as "<"
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    return VIEWER_PATH.read_text(encoding="utf-8").replace("__REPORT_JSON__", payload)


def _commits_since(*, project: Path, report: dict[str, Any]) -> list[dict[str, str]]:
    """Return the commits on HEAD after the report's project_commit, newest first.

    `report` runs right after an update's own commits (the update commit, then any fix commits), so these are exactly
    the commits that update made. A branch carrying several updates gets one report per update, so listing the whole
    branch instead would repeat the same list under every report.
    """
    project_commit = report.get("project_commit")
    if not isinstance(project_commit, dict):
        return []
    sha = project_commit.get("sha")
    if not isinstance(sha, str):
        return []
    log = _git("log", "--format=%h%x00%s", f"{sha}..HEAD", cwd=project).strip()
    return [dict(zip(("sha", "subject"), line.split("\0", 1), strict=True)) for line in log.splitlines()]


def cmd_report(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    report = json.loads(Path(a.draft).read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise FailError("draft must be a JSON object")
    now = _now()
    _ = report.setdefault("schema_version", "1.0.0")
    _ = report.setdefault("operation", "copier-update")
    _ = report.setdefault("resolved_at", _iso(now))
    if "commits" not in report:
        report["commits"] = _commits_since(project=project, report=report)
    errors = validate_report(report)
    if errors:
        raise FailError("report invalid, nothing written:\n" + "\n".join(errors))
    out_dir = project / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"copier-update-report-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    _ = out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    html = out.with_suffix(".html")
    _ = html.write_text(render_report_html(report), encoding="utf-8")
    return {
        "report": str(out),
        "html": str(html),
        "html_url": html.resolve().as_uri(),
        "resolutions": len(report["resolutions"]),
        "needs_review": [r["filename"] for r in report["resolutions"] if r.get("needs_review")],
        "tmp_gitignored": _run(cmd=["git", "check-ignore", "-q", "tmp"], cwd=project).returncode == 0,
    }


def report_markdown(*, report: dict[str, Any], commits: list[dict[str, str]]) -> str:
    copier = report.get("copier", {})
    resolutions = report.get("resolutions", [])
    lines = [
        "## Copier template update",
        "",
        f"**Template** `{copier.get('src_path', '?')}`: `{copier.get('from_version', '?')}` → `{copier.get('to_version', '?')}`",
        f"**Copier** {copier.get('copier_version', '?')}",
    ]
    if copier.get("answers_changed"):
        lines.append("**Answers changed** " + ", ".join(f"`{k}`" for k in copier["answers_changed"]))
    if commits:
        lines += ["", "**Commits**", *[f"- `{c['sha']}` {c['subject']}" for c in commits]]
    review = [r for r in resolutions if r.get("needs_review")]
    if review:
        lines += ["", "### Needs review", ""]
        lines += [
            f"- `{r['filename']}`: {r.get('resolution_strategy', '?')}, confidence {r.get('confidence', '?')}: {r['reason']}"
            for r in review
        ]
    lines += ["", "### Resolutions", "", "| File | Strategy | Confidence | Review |", "|---|---|---|---|"]
    for r in resolutions:
        flag = ""
        if r.get("needs_review"):
            flag = "yes"
        lines.append(
            f"| `{r['filename']}` | {r.get('resolution_strategy', '—')} | {r.get('confidence', '—')} | {flag} |"
        )
    lines += ["", "<details><summary>Per-file detail</summary>", ""]
    for r in resolutions:
        lines += [f"**`{r['filename']}`**", "", f"- What: {r['description']}", f"- Why: {r['reason']}", ""]
    lines += ["</details>"]
    return "\n".join(lines) + "\n"


def _remote_repo(*, project: Path, remote: str) -> str:
    remote_url = _git("remote", "get-url", remote, cwd=project).strip()
    return re.sub(r"^(https://github\.com/|git@github\.com:)", "", remote_url).removesuffix(".git")


def cmd_pr(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    where = guard_not_default_branch(project)
    base = a.base or where["default_branch"]
    branch = where["branch"]
    creds = a.stored_gh_credentials
    _ = _git("push", "-u", a.remote, f"HEAD:{branch}", cwd=project, stored_gh_credentials=creds)
    log = _git("log", "--format=%h%x00%s", f"{a.remote}/{base}..HEAD", cwd=project).strip()
    commits = [dict(zip(("sha", "subject"), line.split("\0", 1), strict=True)) for line in log.splitlines()]
    repo = _remote_repo(project=project, remote=a.remote)
    prefix = ""
    if creds:
        prefix = "env -u GITHUB_TOKEN -u GH_TOKEN "
    create = ["gh", "pr", "create", "--repo", repo, "--base", base, "--head", branch, "--title", a.title]
    create += ["--body-file", str(Path(a.body_file).resolve())]
    if not a.ready:
        create.append("--draft")
    # whether an agent may open a PR is for the permission settings to decide, so it is printed for the agent to run
    # as its own command rather than run here
    return {
        **where,
        "base": base,
        "title": a.title,
        "draft": not a.ready,
        "command": prefix + shlex.join(create),
        "commits": commits,
    }


def cmd_comment_report(a: argparse.Namespace) -> dict[str, Any]:
    project = Path(a.project)
    where = guard_not_default_branch(project)
    branch = where["branch"]
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    # `report` wrote it valid, but a report edited by hand since would fail mid-format, after nothing could be posted
    errors = validate_report(report)
    if errors:
        raise FailError(f"{a.report} does not match report.schema.json, nothing posted:\n" + "\n".join(errors))
    # gh runs in the project, so a path relative to where the command was typed would be read from the wrong place
    comment = (project / "tmp" / "pr-comment.md").resolve()
    comment.parent.mkdir(exist_ok=True)
    _ = comment.write_text(report_markdown(report=report, commits=report.get("commits", [])), encoding="utf-8")
    res = _run(
        # the PR lives where cmd_pr opened it: in --remote's repo, whatever gh would pick from this checkout
        cmd=[
            "gh",
            "pr",
            "comment",
            branch,
            "--repo",
            _remote_repo(project=project, remote=a.remote),
            "--body-file",
            str(comment),
        ],
        cwd=project,
        stored_gh_credentials=a.stored_gh_credentials,
    )
    if res.returncode != 0:
        raise FailError(f"gh pr comment failed (is the PR open yet?):\n{(res.stdout + res.stderr).strip()}")
    comment.unlink()
    return {**where, "comment_url": res.stdout.strip().splitlines()[-1]}


def write_abort_marker(*, a: argparse.Namespace, error: str) -> None:
    project = Path(getattr(a, "project", "") or "")
    if not (project / ".git").exists():
        return
    try:
        (project / "tmp").mkdir(exist_ok=True)
        _ = (project / "tmp" / "copier-update-aborted.json").write_text(
            json.dumps({"verb": a.verb, "error": error, "at": _iso(_now())}, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)

    def verb(
        name: str, fn: Callable[[argparse.Namespace], dict[str, Any]], *, answers: bool = False, remote: bool = False
    ) -> argparse.ArgumentParser:
        sp = sub.add_parser(name)
        sp.add_argument("project", nargs="?", default=".")
        if answers:
            sp.add_argument("--answers-file", default=None, help="relative to project; discovered when omitted")
            sp.add_argument("--cache-dir", default=None)
        if remote:
            sp.add_argument(
                "--stored-gh-credentials", action="store_true", help="drop GITHUB_TOKEN/GH_TOKEN for git, gh and task"
            )
        sp.set_defaults(fn=fn)
        return sp

    _ = verb("find-answers", cmd_find_answers)
    br = verb("branch", cmd_branch)
    br.add_argument("--ref", default="latest", help="the template ref, for the default branch name")
    br.add_argument("--name", default=None, help="branch name (default: chore/template-<ref>)")
    br.add_argument("--worktree", default=None, help="create the branch in a new worktree at this path")
    refs = verb("refs", cmd_refs, answers=True, remote=True)
    refs.add_argument("--count", type=int, default=3, help="recent branches besides the default")
    nq = verb("new-questions", cmd_new_questions, answers=True, remote=True)
    nq.add_argument("--ref", required=True)
    up = verb("update", cmd_update, answers=True, remote=True)
    up.add_argument("--ref", default=None, help="template ref; omitted means copier's default, the latest tag")
    up.add_argument("--data", action="append", default=[], metavar="KEY=VALUE")
    up.add_argument("--data-file", default=None)
    _ = verb("conflicts", cmd_conflicts)
    _ = verb("lint", cmd_lint)
    cm = verb("commit", cmd_commit)
    cm.add_argument("--draft", required=True, help="the resolution draft; its confidences gate the commit")
    cm.add_argument(
        "--approved", action="append", default=[], metavar="FILE", help="a below-high resolution the user decided on"
    )
    cm.add_argument("--message-file", required=True, help="the full commit message")
    cm.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="HOOK",
        help="a hook id `lint` still lists in failed_hooks; every other hook runs on the commit",
    )
    rp = verb("report", cmd_report)
    rp.add_argument("draft")
    pr = verb("pr", cmd_pr, remote=True)
    pr.add_argument("--title", required=True)
    pr.add_argument("--body-file", required=True, help="the filled-in PR template")
    pr.add_argument("--base", default=None)
    pr.add_argument("--remote", default="origin")
    pr.add_argument("--ready", action="store_true", help="open it ready for review instead of as a draft")
    cm_report = verb("comment-report", cmd_comment_report, remote=True)
    cm_report.add_argument("--report", required=True, help="the report JSON from `report`")
    cm_report.add_argument("--remote", default="origin")

    cr = sub.add_parser("capture-rej")
    cr.add_argument("rej")
    cr.add_argument("--root", default=".")
    cr.set_defaults(fn=cmd_capture_rej)
    return p


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        # one line, so it can be read back with jq or tail -1 even when uv adds its own lines
        print(json.dumps(a.fn(a), default=str))  # noqa: T201 # the JSON on stdout is the interface
    # OSError and ValueError: a missing or malformed file (--draft, --report, a .rej) or unreadable task JSON
    except (FailError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)  # noqa: T201 # errors go to stderr for the caller
        write_abort_marker(a=a, error=str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
