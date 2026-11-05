#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Helper for the backport-copier-change skill.

Verbs (all print JSON on stdout; errors go to stderr with exit 1):

  chain FILE [--layer R] [--out F]  the template that owns FILE (per the repo's
                                    .config/.copier-managed-files.json), and every repo from
                                    the chosen layer (default: the owner) down to this one, in
                                    the order a change flows, with each repo's visibility
                                    (--also R adds another repo, placed after its parent template)
  consumers --template R            repos whose answers file names template R, per code search, most
                                    recently merged first, each marked a template (copier.yml at its
                                    root) or a project, and whether it is on R's latest tag
  checkout --branch B --path P      clone (--repo) or fetch the repo at P, refuse a dirty tree,
                                    and switch to B: the local branch, else origin's (resuming in
                                    a fresh clone), else a new one off the fresh default branch;
                                    with --worktree-of DIR, make P a new worktree of DIR instead.
                                    Installs .claude/ node packages when they are missing, the
                                    pre-commit hooks, and each uv project's environment
  behind [--checkout DIR | --repo R] [--parent-checkout DIR]
                                    the repo's `_commit` against its parent template's newest tag,
                                    from a checkout or, with --repo, from a shallow fetch of R's
                                    default branch; with the parent's checkout, also the catch-up
                                    commits on the parent's branch to pull one by one before the
                                    change, and whether the newest tag lacks a pin taken from the
                                    parent's branch
  push --chain F [--checkout DIR]   push the branch and print its full head SHA; for a public repo,
                                    first refuse any unpushed commit whose message or changes name a
                                    private repo from the chain
  net-diff [--checkout DIR]         drop copier's staged-then-reversed changes, list the net
                                    change against HEAD, and say whether only `_commit` moved
  scan --chain F --repo R --file T  private repo names from the chain that text T would leak
                                    into public repo R
  pr-command --chain F --title T --body-file B   scan, then print the command that opens the
                                    branch's draft PR, for the agent to run
  pr-body --pr N --chain F --body-file B   scan, merge in whatever anyone else changed in the PR's
                                    description since it was posted, and print the command that
                                    replaces it
  ci --repo OWNER/NAME --sha SHA     wait for every push and pull_request CI run on SHA, then for
                                    every one of their jobs to report completed, and list each
                                    job's conclusion, and any job that never started, with
                                    GitHub's reason, and any run that failed before creating a job
  ai-review --repo R --pr N         wait for every AI reviewer the repo configures (one module
                                    per reviewer in ai_reviewers/) to give its verdict on the
                                    PR's latest commit: clean, flagged or skipped, settled when
                                    everything a flagged review found has since been fixed or
                                    answered, or head_not_reviewed when a reviewer stays quiet about
                                    a new head (with its own note under held_back when it says it is
                                    out of allowance; while it says a review is running, this keeps
                                    waiting). changed_since_last_review counts only the branch's own
                                    commits, not a merge of the default branch;
                                    a flagged reviewer's entry lists its open findings (id, type,
                                    path, line, url, body_text), read through the pr-comments skill
  merge-command --repo R --pr N --checkout DIR
                                    refuse while the PR's branch is behind its base; else the
                                    commands that mark the draft ready and merge it the way the
                                    repo allows, in order, for the agent to run one by one
  tag --repo R --pr N               wait for the PR to merge and for a tag on its merge
                                    commit (the tag-on-merge workflow) and print it
  delete-branch --repo R --branch B --checkout DIR --chain F --downstream DIR ...
                                    delete a template repo's merged branch, on GitHub and locally,
                                    once every repo generated from it records no commit only it holds
  update-branch --checkout DIR --branch B --chain F [--finish]
                                    merge the default branch into the feature branch when it is
                                    checked out there and clean, and push; on a conflict, leave
                                    the merge for the agent to resolve, then --finish commits
                                    and pushes once nothing is unmerged or marked; for a public
                                    repo, first refuse as push does
  cleanup --worktree DIR            remove a clean, fully pushed worktree

No verb opens, marks ready or merges a PR. Whether an agent may do those is decided by the permission
settings, so the verbs check what they can and print the command; the agent runs it itself and the settings decide. A
script must never be a way around them. Pushes, deleting a merged branch and PR comments are routine and the verbs
do them.

Every gh and git call runs without GITHUB_TOKEN and GH_TOKEN, so it uses the credentials
`gh auth login` stored. In a GitHub Codespace the injected token only reaches the
codespace's own repository.
"""

import argparse
import datetime
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from ai_reviewers import REVIEWERS

MANIFEST = Path(".config/.copier-managed-files.json")
ANSWERS = Path(".config/.copier-answers.yml")


MAX_CONSECUTIVE_FAILURES = 5
TRANSIENT = re.compile(r"HTTP 5\d\d|connection reset|timed out|TLS handshake|EOF", re.IGNORECASE)


class FailError(Exception):
    pass


class TransientError(FailError):
    pass


def _attempt(*, cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    _ = env.pop("GITHUB_TOKEN", None)
    _ = env.pop("GH_TOKEN", None)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, check=False)  # noqa: S603 # argv lists, never a shell; the variable parts come from this script's own CLI arguments


def _run(*, cmd: list[str], cwd: Path | None = None) -> str:
    res = _attempt(cmd=cmd, cwd=cwd)
    if res.returncode != 0:
        output = (res.stdout + res.stderr).strip()
        if TRANSIENT.search(output):
            raise TransientError(f"{' '.join(cmd)} failed:\n{output}")
        raise FailError(f"{' '.join(cmd)} failed:\n{output}")
    return res.stdout


def _git(*args: str, cwd: Path) -> str:
    return _run(cmd=["git", *args], cwd=cwd)


def _gh_json(*args: str, cwd: Path | None = None) -> Any:  # noqa: ANN401 # gh's JSON output has a different shape per command
    return json.loads(_run(cmd=["gh", *args], cwd=cwd))


def _repo_slug(src: str) -> str:
    slug = re.sub(r"^(gh:|https://github\.com/|git@github\.com:)", "", src)
    return slug.removesuffix(".git")


def _commit_in(answers: str) -> str | None:
    match = re.search(r"^_commit: (\S+)$", answers, flags=re.MULTILINE)
    if match is None:
        return None
    return match.group(1)


def _answers_commit(repo: Path) -> str | None:
    path = repo / ANSWERS
    if not path.is_file():
        return None
    return _commit_in(path.read_text())


SEARCH_ATTEMPTS = 3
# GitHub's code search allows a few requests a minute, and the limit resets each minute
SEARCH_LIMIT_RESET_SECONDS = 61
# one page of code search hits; a template has a few dozen consumers, and more pages would spend that rate limit
CODE_SEARCH_LIMIT = 100


def _gh_search(*args: str) -> Any:  # noqa: ANN401 # gh's JSON output has a different shape per command
    attempt = 1
    while True:
        try:
            return _gh_json("search", "code", *args)
        except FailError as e:
            if "rate limit" not in str(e).lower():
                raise
            if attempt >= SEARCH_ATTEMPTS:
                raise
        attempt += 1
        time.sleep(SEARCH_LIMIT_RESET_SECONDS)


def _src_paths(*, query: str, extra: list[str]) -> list[dict[str, Any]]:
    hits = _gh_search(
        query,
        "--filename",
        ".copier-answers.yml",
        *extra,
        "--json",
        "repository,path,textMatches",
        "--limit",
        str(CODE_SEARCH_LIMIT),
    )
    if len(hits) >= CODE_SEARCH_LIMIT:
        raise FailError(
            f"code search for {query!r} returned {CODE_SEARCH_LIMIT} hits, its limit here, so the list of repos"
            " generated from the template may be incomplete"
        )
    return [
        {
            "repo": hit["repository"]["nameWithOwner"],
            "private": hit["repository"].get("isPrivate"),
            "answers_file": hit["path"],
            "src": match.group(1),
            # the fragment is a few lines around the match, and copier writes _commit right before _src_path
            "commit": _commit_in(fragment["fragment"]),
        }
        for hit in hits
        for fragment in hit.get("textMatches", [])
        if (match := re.search(r"^_src_path: (\S+)$", fragment["fragment"], flags=re.MULTILINE)) is not None
    ]


REPO_CACHE = Path(tempfile.gettempdir()) / "backport-repo-cache"


def _default_branch_answers(repo: str) -> str:
    """Read a repo's answers file on its default branch, which records the template it is on today.

    A known repo's file comes straight from git, by a depth-1 fetch of the remote's HEAD into a bare cache repo:
    code search allows only a few requests a minute, and returns only a snippet of the file.
    """
    cache = REPO_CACHE / (repo.replace("/", "__") + ".git")
    if not cache.is_dir():
        cache.mkdir(parents=True)
        _ = _git("init", "--bare", "--quiet", cwd=cache)
    _ = _git("fetch", "--depth", "1", "--quiet", f"https://github.com/{repo}.git", "HEAD", cwd=cache)
    for path in (ANSWERS.as_posix(), ".copier-answers.yml"):
        res = _attempt(cmd=["git", "show", f"FETCH_HEAD:{path}"], cwd=cache)
        if res.returncode == 0:
            return res.stdout
    raise FailError(f"{repo} has no {ANSWERS.as_posix()} or .copier-answers.yml on its default branch")


def _src_and_commit(*, answers: str, where: str) -> tuple[str, str | None]:
    src = re.search(r"^_src_path: (\S+)$", answers, flags=re.MULTILINE)
    if src is None:
        raise FailError(f"{where} has no _src_path")
    return src.group(1), _commit_in(answers)


def parent_template(repo: str) -> str:
    src, __ = _src_and_commit(answers=_default_branch_answers(repo), where=f"{repo}'s answers file")
    return _repo_slug(src)


def _template_repos(owners: set[str]) -> set[str]:
    # a template keeps its copier questions file at its root; a generated project has only an answers file
    # code search allows only a few requests a minute, so each filename is one search across every owner
    templates: set[str] = set()
    owner_flags = [flag for owner in sorted(owners) for flag in ("--owner", owner)]
    for name in ("copier.yml", "copier.yaml"):
        hits = _gh_search("--filename", name, *owner_flags, "--json", "repository,path", "--limit", "100")
        templates.update(hit["repository"]["nameWithOwner"] for hit in hits if hit["path"] == name)
    return templates


def _last_merged_at(repo: str) -> str | None:
    # gh lists the newest-created PRs first, which are not always the newest merged
    prs = _gh_json("pr", "list", "--repo", repo, "--state", "merged", "--limit", "10", "--json", "mergedAt")
    return max((pr["mergedAt"] for pr in prs), default=None)


def cmd_consumers(a: argparse.Namespace) -> dict[str, Any]:
    repos: dict[str, dict[str, Any]] = {}
    for found in _src_paths(query=f"gh:{a.template}", extra=[]):
        # the search matches loosely, so keep only answers files that name this template exactly
        if _repo_slug(found["src"]) != a.template:
            continue
        repos[found["repo"]] = found
    templates = _template_repos({repo.split("/", 1)[0] for repo in repos})
    latest = _latest_tag(a.template)
    for repo, found in repos.items():
        found["kind"] = "project"
        if repo in templates:
            found["kind"] = "template"
        found["on_latest_tag"] = found["commit"] == latest
        found["last_merged_at"] = _last_merged_at(repo)
    return {
        "template": a.template,
        "latest_tag": latest,
        # the most recently active first: the likeliest to have working CI and someone watching it
        "consumers": sorted(repos.values(), key=lambda r: r["last_merged_at"] or "", reverse=True),
        "note": "GitHub code search covers each repo's default branch and only repos it has indexed",
    }


def _owner_index(*, templates: list[dict[str, Any]], file: str) -> int | None:
    # the last manifest entry listing a file is the template that places it
    owner_index = None
    for index, entry in enumerate(templates):
        if file in entry["managed_files"]:
            owner_index = index
    return owner_index


def _layer_index(*, templates: list[dict[str, Any]], layer: str | None, owner_index: int | None, file: str) -> int:
    if layer is not None:
        slugs = [_repo_slug(t["src"]) for t in templates]
        if layer not in slugs:
            raise FailError(f"{layer} is not in this repo's template chain: {', '.join(slugs)}")
        return slugs.index(layer)
    if owner_index is None:
        raise FailError(f"{file} is not listed in {MANIFEST}; pass --layer with the template it should go in")
    return owner_index


def _place_extra_repos(*, chain: list[dict[str, Any]], extras: list[str]) -> None:
    """Insert each extra repo into the chain right after the repo it is generated from.

    A parent can be any repo already in the chain except the originating one, another extra repo included (a
    project generated from an extra template), so extras are placed as their parents become available.
    """
    parents = {extra: parent_template(extra) for extra in extras}
    pending = list(extras)
    while pending:
        placeable = [e for e in pending if parents[e] in [link["repo"] for link in chain if link["role"] != "origin"]]
        if not placeable:
            in_chain = ", ".join(link["repo"] for link in chain if link["role"] != "origin")
            raise FailError(
                "these repos are generated from templates that are not in the chain: "
                + ", ".join(f"{e} (from {parents[e]})" for e in pending)
                + f"; the chain has {in_chain}"
            )
        for extra in placeable:
            # an extra repo pulls right after its parent's CI is green
            insert_at = [link["repo"] for link in chain].index(parents[extra]) + 1
            chain.insert(insert_at, {"repo": extra, "src": None, "role": "also", "parent": parents[extra]})
            pending.remove(extra)


def cmd_chain(a: argparse.Namespace) -> dict[str, Any]:
    repo = Path(a.repo)
    templates: list[dict[str, Any]] = json.loads((repo / MANIFEST).read_text())["templates"]
    owner_index = _owner_index(templates=templates, file=a.file)
    start_index = _layer_index(templates=templates, layer=a.layer, owner_index=owner_index, file=a.file)
    # the manifest lists the chain root first, so everything after the chosen layer is downstream of it
    # each repo records its parent: the template its answers file names, which `delete-branch` needs to know which
    # repos must be re-pinned before a template's branch can go
    chain: list[dict[str, Any]] = []
    for index in range(start_index, len(templates)):
        parent = None
        if index > start_index:
            parent = _repo_slug(templates[index - 1]["src"])
        chain.append(
            {
                "repo": _repo_slug(templates[index]["src"]),
                "src": templates[index]["src"],
                "role": "template",
                "parent": parent,
            }
        )
    chain[0]["role"] = "layer"
    origin = _git("remote", "get-url", "origin", cwd=repo).strip()
    chain.append(
        {
            "repo": _repo_slug(origin),
            "src": None,
            "role": "origin",
            "path": str(repo.resolve()),
            "parent": _repo_slug(templates[-1]["src"]),
        }
    )
    _place_extra_repos(chain=chain, extras=a.also)
    for link in chain:
        link["visibility"] = _gh_json("repo", "view", link["repo"], "--json", "visibility")["visibility"]
    owner = None
    if owner_index is not None:
        owner = _repo_slug(templates[owner_index]["src"])
    result = {"file": a.file, "owner": owner, "layer": chain[0]["repo"], "chain": chain}
    if a.out is not None:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        _ = Path(a.out).write_text(json.dumps(result, indent=2) + "\n")
    return result


def _default_branch(checkout: Path) -> str:
    res = _attempt(cmd=["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=checkout)
    if res.returncode == 0:
        return res.stdout.strip().removeprefix("origin/")
    return _gh_json("repo", "view", "--json", "defaultBranchRef", cwd=checkout)["defaultBranchRef"]["name"]


def _has_ref(*, checkout: Path, ref: str) -> bool:
    return _attempt(cmd=["git", "rev-parse", "--verify", "-q", ref], cwd=checkout).returncode == 0


def _dirty(checkout: Path) -> list[str]:
    return [line for line in _git("status", "--porcelain", cwd=checkout).splitlines() if line]


PRE_COMMIT_CONFIGS = (".pre-commit-config.yaml", ".pre-commit-config.yml")


def _set_up_hooks(checkout: Path) -> dict[str, Any]:
    """Install the repo's pre-commit hooks and sync its uv projects, as setting up a clone by hand would.

    A fresh clone has no git hooks, so its commits would skip every check its CI runs. Its uv environments are empty
    too, and a dependency-sync hook fails the first commit whose sync installs anything. A sync that fails (a lock
    file a template renders, say) is reported rather than stopping the checkout.
    """
    installed = False
    for config in PRE_COMMIT_CONFIGS:
        if (checkout / config).is_file():
            _ = _run(cmd=["pre-commit", "install"], cwd=checkout)
            installed = True
            break
    synced: list[str] = []
    failed: list[str] = []
    for tracked in _git("ls-files", "-z", cwd=checkout).split("\0"):
        if Path(tracked).name != "uv.lock":
            continue
        lock_dir = Path(tracked).parent
        res = _attempt(cmd=["uv", "sync", "--frozen"], cwd=checkout / lock_dir)
        if res.returncode != 0:
            failed.append(f"{lock_dir}: {res.stderr.strip()}")
            continue
        synced.append(str(lock_dir))
    return {"pre_commit_installed": installed, "uv_synced": synced, "uv_sync_failed": failed}


def _install_claude_packages(checkout: Path) -> bool:
    claude = checkout / ".claude"
    if not (claude / "package-lock.json").is_file():
        return False
    if (claude / "node_modules").exists():
        return False
    _ = _run(cmd=["npm", "ci", "--no-audit", "--no-fund"], cwd=claude)
    return True


def cmd_checkout(a: argparse.Namespace) -> dict[str, Any]:
    if a.worktree_of is not None:
        source = Path(a.worktree_of)
        path = Path(a.path)
        _ = _git("fetch", "--quiet", "origin", cwd=source)
        default = _default_branch(source)
        if path.exists():
            raise FailError(f"{path} already exists; reuse it or pick another --path")
        if _has_ref(checkout=source, ref=f"refs/heads/{a.branch}"):
            # resuming: the branch outlives a worktree whose directory went with an earlier session's scratchpad
            _ = _git("worktree", "prune", cwd=source)
            _ = _git("worktree", "add", str(path), a.branch, cwd=source)
        else:
            _ = _git("worktree", "add", "-b", a.branch, str(path), f"origin/{default}", cwd=source)
    else:
        path = Path(a.path)
        if path.exists():
            dirty = _dirty(path)
            if dirty:
                raise FailError(f"{path} has uncommitted changes:\n" + "\n".join(dirty))
            _ = _git("fetch", "--quiet", "--tags", "origin", cwd=path)
        elif a.repo is None:
            raise FailError(f"{path} does not exist; pass --repo to clone it")
        else:
            _ = _run(cmd=["gh", "repo", "clone", a.repo, str(path)])
        default = _default_branch(path)
        if _has_ref(checkout=path, ref=f"refs/heads/{a.branch}"):
            _ = _git("switch", a.branch, cwd=path)
        elif _has_ref(checkout=path, ref=f"refs/remotes/origin/{a.branch}"):
            # resuming in a fresh clone (a new session's scratchpad): carry on from what was pushed
            _ = _git("switch", "-c", a.branch, "--track", f"origin/{a.branch}", cwd=path)
        else:
            _ = _git("switch", "-c", a.branch, f"origin/{default}", cwd=path)
    return {
        "path": str(path.resolve()),
        "branch": a.branch,
        "default_branch": default,
        "head": _git("rev-parse", "HEAD", cwd=path).strip(),
        "installed_claude_packages": _install_claude_packages(path),
        "hooks": _set_up_hooks(path),
    }


# copier records an untagged ref as `git describe` output: <tag>-<count>-g<sha>
UNTAGGED_SUFFIX = re.compile(r"-\d+-g([0-9a-f]+)$")


def _base_tag(commit: str) -> str:
    return UNTAGGED_SUFFIX.sub("", commit)


def _latest_tag(repo: str) -> str:
    url = f"https://github.com/{repo}.git"
    tags = [
        line.split("\t", 1)[1].removeprefix("refs/tags/")
        for line in _run(cmd=["git", "ls-remote", "--tags", "--refs", "--sort=-v:refname", url]).splitlines()
    ]
    if not tags:
        raise FailError(f"{url} has no tags")
    return tags[0]


def cmd_behind(a: argparse.Namespace) -> dict[str, Any]:
    if a.repo is None:
        answers_path = Path(a.checkout) / ANSWERS
        src, current = _src_and_commit(answers=answers_path.read_text(), where=str(answers_path))
    else:
        # needs no checkout, so it works while planning, before any exists
        src, current = _src_and_commit(answers=_default_branch_answers(a.repo), where=f"{a.repo}'s answers file")
    parent = _repo_slug(src)
    latest = _latest_tag(parent)
    based_on = None
    if current is not None:
        based_on = _base_tag(current)
    result: dict[str, Any] = {
        "parent": parent,
        "current": current,
        "based_on": based_on,
        "latest_tag": latest,
        "behind": based_on != latest,
    }
    if a.parent_checkout is not None:
        result["pull_points"] = _catch_up_pull_points(Path(a.parent_checkout))
        if result["behind"]:
            result["latest_tag_lacks_pin"] = _latest_tag_lacks_pin(
                parent=Path(a.parent_checkout), current=current, latest=latest
            )
    return result


def _latest_tag_lacks_pin(*, parent: Path, current: str | None, latest: str) -> bool:
    """Whether the parent's newest tag was released without the commit this repo pins.

    Mid-backport, a child pins a commit on the parent's backport branch. When the parent's default branch releases a
    tag meanwhile, that tag doesn't contain the pinned commit, so a copier update to the tag would drop the change.
    The parent's default branch has to be merged into its backport branch instead, and that head pulled here.
    """
    if current is None:
        return False
    match = UNTAGGED_SUFFIX.search(current)
    if match is None:
        return False
    _ = _git("fetch", "--quiet", "--tags", "origin", cwd=parent)
    res = _attempt(cmd=["git", "merge-base", "--is-ancestor", match.group(1), latest], cwd=parent)
    if res.returncode == 0:
        return False
    if res.returncode == 1:
        return True
    raise FailError(f"git merge-base --is-ancestor {match.group(1)} {latest} failed in {parent}:\n{res.stderr.strip()}")


def _catch_up_pull_points(parent: Path) -> list[dict[str, str]]:
    """List the commits on the parent's branch that caught it up to a release of its own template.

    A parent whose branch starts with such a catch-up carries unrelated template content into anything that pulls its
    branch head. Pulling each catch-up commit first, as its own commit, keeps the child's history to one thing per
    commit: a catch-up commit is one that moved the parent's own `_commit` to a release tag.
    """
    default = _default_branch(parent)
    points: list[dict[str, str]] = []
    log = _git("log", "--reverse", "--format=%H%x00%s", f"origin/{default}..HEAD", "--", ANSWERS.as_posix(), cwd=parent)
    for line in log.splitlines():
        sha, subject = line.split("\0", 1)
        answers = _git("show", f"{sha}:{ANSWERS.as_posix()}", cwd=parent)
        commit = _commit_in(answers)
        if commit is not None and _base_tag(commit) == commit:
            points.append({"sha": sha, "subject": subject, "parent_commit": commit})
    return points


def _added_text(*, checkout: Path, sha: str) -> str:
    """Return the paths a commit touches and the lines it adds, the part of its diff a push publishes anew.

    A merge commit's combined diff heads each file with `diff --cc <path>` instead, and for a binary file that header
    is the only place its path appears.
    """
    diff = _git("show", "--format=", "--no-color", "--no-ext-diff", "-M", "--unified=0", sha, cwd=checkout)
    added: list[str] = []
    for line in diff.splitlines():
        if line.startswith(("diff --git ", "diff --cc ", "rename to ")):
            added.append(line)
            continue
        if line.startswith("+"):
            added.append(line[1:])
    return "\n".join(added)


def _leaking_commits(*, checkout: Path, pushed: list[str], repo: str, chain: dict[str, Any]) -> list[str]:
    leaks: list[str] = []
    for sha in _git("rev-list", "HEAD", *[f"^{ref}" for ref in pushed], cwd=checkout).split():
        in_message = scan_text(text=_git("log", "-1", "--format=%B", sha, cwd=checkout), repo=repo, chain=chain)
        in_changes = scan_text(text=_added_text(checkout=checkout, sha=sha), repo=repo, chain=chain)
        if in_message:
            leaks.append(f"{sha[:12]} message: {', '.join(in_message)}")
        if in_changes:
            leaks.append(f"{sha[:12]} changes: {', '.join(in_changes)}")
    return leaks


def _require_no_leaks(*, checkout: Path, branch: str, default: str, chain_file: str) -> None:
    """Refuse a push of `branch` that would publish a private repo's name.

    Only what the push adds is scanned: the commits on HEAD that neither origin's default branch nor origin's copy of
    `branch` holds. After a merge of the default branch, that is the branch's unpushed commits and the merge commit
    itself, not the default branch's own history.
    """
    pushed = [f"origin/{default}"]
    if _has_ref(checkout=checkout, ref=f"refs/remotes/origin/{branch}"):
        pushed.append(f"origin/{branch}")
    repo = _repo_slug(_git("remote", "get-url", "origin", cwd=checkout).strip())
    leaks = _leaking_commits(
        checkout=checkout, pushed=pushed, repo=repo, chain=json.loads(Path(chain_file).read_text())
    )
    if leaks:
        raise FailError(
            f"{repo} is public and these unpushed commits name a private repo in their message or changes; nothing was "
            "pushed. Reword or edit them (they are not on GitHub yet, so rewriting them is safe), then push again:\n"
            + "\n".join(leaks)
        )


def cmd_push(a: argparse.Namespace) -> dict[str, Any]:
    checkout = Path(a.checkout)
    branch = _git("symbolic-ref", "--short", "HEAD", cwd=checkout).strip()
    default = _default_branch(checkout)
    if branch == default:
        raise FailError(f"refusing to push the default branch {branch}")
    _require_no_leaks(checkout=checkout, branch=branch, default=default, chain_file=a.chain)
    _ = _git("push", "-u", "origin", branch, cwd=checkout)
    return {"branch": branch, "sha": _git("rev-parse", "HEAD", cwd=checkout).strip()}


def cmd_net_diff(a: argparse.Namespace) -> dict[str, Any]:
    checkout = Path(a.checkout)
    # copier can stage a change and reverse it in the working tree; only the net change
    # against HEAD is real, so drop the index's half
    _ = _git("reset", "-q", cwd=checkout)
    changed = [p for p in _git("diff", "HEAD", "--name-only", cwd=checkout).splitlines() if p]
    untracked: list[str] = []
    for path in _git("ls-files", "--others", "--exclude-standard", cwd=checkout).splitlines():
        parts = Path(path).parts
        if parts[0] == "tmp":
            continue
        if "node_modules" in parts:
            continue
        untracked.append(path)
    before = None
    head_answers = _attempt(cmd=["git", "show", f"HEAD:{ANSWERS.as_posix()}"], cwd=checkout)
    if head_answers.returncode == 0:
        before = _commit_in(head_answers.stdout)
    answers_lines = [
        line
        for line in _git("diff", "HEAD", "--unified=0", "--", ANSWERS.as_posix(), cwd=checkout).splitlines()
        if re.match(r"^[+-](?![+-])", line)
    ]
    only_commit = all(re.match(r"^[+-]_commit: ", line) for line in answers_lines)
    # copier can write a template's new block over the repo's own lines next to it and reject re-adding them, so
    # a file that lost lines needs a look even when its .rej has been dealt with
    removed_lines: dict[str, int] = {}
    for line in _git("diff", "HEAD", "--numstat", cwd=checkout).splitlines():
        __, removed, path = line.split("\t", 2)
        if removed not in {"0", "-"}:
            removed_lines[path] = int(removed)
    return {
        "changed": changed,
        "removed_lines": removed_lines,
        "untracked": untracked,
        "rej_files": [p for p in untracked if p.endswith(".rej")],
        "commit_before": before,
        "commit_after": _answers_commit(checkout),
        "only_commit_changed": changed == [ANSWERS.as_posix()] and not untracked and only_commit,
    }


def private_names(chain: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for link in chain["chain"]:
        if link["visibility"] == "PUBLIC":
            continue
        names += [link["repo"], link["repo"].split("/", 1)[1]]
    return names


def scan_text(*, text: str, repo: str, chain: dict[str, Any]) -> list[str]:
    visibility = next((link["visibility"] for link in chain["chain"] if link["repo"] == repo), None)
    if visibility is None:
        visibility = _gh_json("repo", "view", repo, "--json", "visibility")["visibility"]
    if visibility != "PUBLIC":
        return []
    # no trailing boundary: a worktree or clone named after the repo leaks the name too
    return sorted(
        {name for name in private_names(chain) if re.search(rf"(?<![\w-]){re.escape(name)}", text, flags=re.IGNORECASE)}
    )


def cmd_scan(a: argparse.Namespace) -> dict[str, Any]:
    chain = json.loads(Path(a.chain).read_text())
    hits = scan_text(text=Path(a.file).read_text(), repo=a.repo, chain=chain)
    return {"repo": a.repo, "private_names_found": hits, "ok": not hits}


def cmd_pr_command(a: argparse.Namespace) -> dict[str, Any]:
    """Check a draft PR's title and body, then print the command that opens it.

    Opening a PR writes to GitHub, so the agent runs the printed command as its own command rather than this script
    running it.
    """
    checkout = Path(a.checkout)
    chain = json.loads(Path(a.chain).read_text())
    repo = _repo_slug(_git("remote", "get-url", "origin", cwd=checkout).strip())
    hits = scan_text(text=f"{a.title}\n{Path(a.body_file).read_text()}", repo=repo, chain=chain)
    if hits:
        raise FailError(f"{repo} is public and the PR title or body names a private repo: {', '.join(hits)}")
    branch = _git("symbolic-ref", "--short", "HEAD", cwd=checkout).strip()
    if not _has_ref(checkout=checkout, ref=f"refs/remotes/origin/{branch}"):
        raise FailError(f"{branch} is not on origin yet; run `push` first")
    base = _default_branch(checkout)
    _record_pending_body(checkout=checkout, body=Path(a.body_file).read_text())
    argv = [
        "gh",
        "pr",
        "create",
        # every flag explicit, so the command works from any directory
        "--draft",
        "--repo",
        repo,
        "--base",
        base,
        "--head",
        branch,
        "--title",
        a.title,
        "--body-file",
        str(Path(a.body_file).resolve()),
    ]
    return {
        "repo": repo,
        "base": base,
        "branch": branch,
        "command": "env -u GITHUB_TOKEN -u GH_TOKEN " + shlex.join(argv),
    }


# the body this skill last printed a command to post, and the last one it saw on GitHub: the base for merging in
# whatever anyone else changed since
PENDING_BODY = Path("tmp/pr-body.pending.md")
POSTED_BODY = Path("tmp/pr-body.posted.md")
# the description as it stood when a merge conflicted: the agent's resolution already accounts for it
SEEN_BODY = Path("tmp/pr-body.seen.md")


def _record_pending_body(*, checkout: Path, body: str) -> None:
    path = checkout / PENDING_BODY
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(body)


def _normalized(body: str) -> str:
    # GitHub may hand a body back with CRLF line ends and trailing spaces trimmed
    lines = [line.rstrip() for line in body.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def _merge_base(*, checkout: Path, live: str) -> str:
    seen = checkout / SEEN_BODY
    if seen.is_file():
        if _normalized(seen.read_text()) == _normalized(live):
            return seen.read_text()
    pending = checkout / PENDING_BODY
    posted = checkout / POSTED_BODY
    if pending.is_file():
        if _normalized(pending.read_text()) == _normalized(live):
            # the printed command was run, and nobody has changed the description since
            _ = posted.write_text(pending.read_text())
        elif not posted.is_file():
            return pending.read_text()
    if not posted.is_file():
        raise FailError(f"{posted} is missing, so edits by others can't be told from ours; compare by hand:\n{live}")
    return posted.read_text()


_CONFLICT = re.compile(
    r"^<<<<<<< yours\n(?P<ours>.*?)^\|\|\|\|\|\|\| as last posted\n(?P<base>.*?)^=======\n(?P<theirs>.*?)^>>>>>>> on GitHub now\n",
    re.MULTILINE | re.DOTALL,
)


def _keep_both_additions(merged: str) -> str:
    # both sides adding text at the same place (our new line and a reviewer's appended summary, say) is no real
    # conflict: keep ours, then theirs; a conflict over lines that were already there stays for a person to resolve
    def resolve(match: re.Match[str]) -> str:
        if match.group("base").strip():
            return match.group(0)
        return match.group("ours") + "\n" + match.group("theirs")

    return _CONFLICT.sub(resolve, merged)


def cmd_pr_body(a: argparse.Namespace) -> dict[str, Any]:
    """Merge a PR's new description with whatever else changed in it since it was posted, and print the edit command.

    A person, or an AI reviewer adding its summary, may have edited the description since this skill posted it. A
    three-way merge (base: the description as last posted, ours: the new one, theirs: the one on GitHub now) keeps
    their changes beside ours, and `others_changes` shows them for the user. Where both changed the same lines, the
    merge stops with conflict markers left in the merged file to resolve.
    """
    checkout = Path(a.checkout)
    repo = _repo_slug(_git("remote", "get-url", "origin", cwd=checkout).strip())
    new = Path(a.body_file).read_text()
    hits = scan_text(text=new, repo=repo, chain=json.loads(Path(a.chain).read_text()))
    if hits:
        raise FailError(f"{repo} is public and the PR body names a private repo: {', '.join(hits)}")
    live = _gh_json("pr", "view", a.pr, "--repo", repo, "--json", "body")["body"]
    base = _normalized(_merge_base(checkout=checkout, live=live))
    tmp = checkout / "tmp"
    merged = tmp / "pr-body.merged.md"
    _ = merged.write_text(_normalized(new))
    _ = (tmp / "pr-body.base.md").write_text(base)
    _ = (tmp / "pr-body.live.md").write_text(_normalized(live))
    res = _attempt(
        cmd=[
            "git",
            "merge-file",
            "--diff3",
            "-L",
            "yours",
            "-L",
            "as last posted",
            "-L",
            "on GitHub now",
            str(merged),
            str(tmp / "pr-body.base.md"),
            str(tmp / "pr-body.live.md"),
        ]
    )
    # git merge-file exits with the number of conflicts, at most 127, or 255 when it fails outright
    if res.returncode > 127:  # noqa: PLR2004 # git merge-file's highest conflict count
        raise FailError(f"git merge-file failed:\n{(res.stdout + res.stderr).strip()}")
    if res.returncode > 0:
        _ = merged.write_text(_normalized(_keep_both_additions(merged.read_text())))
    if "<<<<<<< yours" in merged.read_text():
        _ = (checkout / SEEN_BODY).write_text(_normalized(live))
        raise FailError(
            f"someone else changed the same lines of {repo}#{a.pr}'s description: resolve the conflicts in "
            f"{merged}, copy the result to {a.body_file}, and rerun"
        )
    others = difflib.unified_diff(
        base.splitlines(), _normalized(live).splitlines(), "as last posted", "on GitHub now", lineterm=""
    )
    _record_pending_body(checkout=checkout, body=merged.read_text())
    (checkout / SEEN_BODY).unlink(missing_ok=True)
    argv = ["gh", "pr", "edit", a.pr, "--repo", repo, "--body-file", str(merged.resolve())]
    return {
        "repo": repo,
        "others_changes": "\n".join(others),
        "command": "env -u GITHUB_TOKEN -u GH_TOKEN " + shlex.join(argv),
    }


def _wait[T](*, timeout: int, interval: int, what: str, probe: Callable[[], T | None]) -> T:
    deadline = time.monotonic() + timeout
    failures = 0
    while True:
        try:
            result = probe()
        except TransientError as e:
            # the GitHub API returns the odd 5xx mid-wait; only a run of them is a real failure
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise FailError(
                    f"{MAX_CONSECUTIVE_FAILURES} failed checks in a row while waiting for {what}: {e}"
                ) from e
        else:
            failures = 0
            if result is not None:
                return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FailError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(min(interval, remaining))


CI_EVENTS = {"push", "pull_request", "pull_request_target"}
# a push starts its push runs and, with a PR open, its pull_request runs within seconds of each other
LATE_RUN_SECONDS = 30


def cmd_ci(a: argparse.Namespace) -> dict[str, Any]:
    """Wait for every CI run on a commit, whatever its event, and report each job's conclusion.

    With a PR open, a repo whose CI also runs on pull_request may skip most push-run jobs as duplicates, and some
    jobs (such as a tagged-template check) run only on the PR, while another repo's CI runs only on push. So rather
    than guess which events will run, this takes every push and pull_request run that appears for the commit, and
    judges by all of them together.
    """

    def find_runs() -> list[int] | None:
        runs = _gh_json("run", "list", "--repo", a.repo, "--limit", "50", "--json", "databaseId,headSha,event")
        ids = [r["databaseId"] for r in runs if r["headSha"].startswith(a.sha) and r["event"] in CI_EVENTS]
        return ids or None

    run_ids = _wait(timeout=600, interval=15, what=f"a CI run for {a.sha}", probe=find_runs)
    first_seen = time.monotonic()

    # a run can report completed while some of its jobs still say in_progress, so wait on the jobs themselves, and on
    # every run, since one commit can trigger several workflows and events
    def finished() -> list[dict[str, Any]] | None:
        nonlocal run_ids
        run_ids = sorted({*run_ids, *(find_runs() or [])})
        views = [
            _gh_json(
                "run", "view", str(run_id), "--repo", a.repo, "--json", "status,conclusion,jobs,url,workflowName,event"
            )
            for run_id in run_ids
        ]
        for view in views:
            if view["status"] != "completed":
                return None
            if [j for j in view["jobs"] if j["status"] != "completed"]:
                return None
        if time.monotonic() - first_seen < LATE_RUN_SECONDS:
            return None
        return views

    views = _wait(timeout=a.timeout, interval=30, what=f"the CI runs for {a.sha} to finish", probe=finished)
    jobs = [
        {"workflow": v["workflowName"], "event": v["event"], "name": j["name"], "conclusion": j["conclusion"]}
        for v in views
        for j in v["jobs"]
    ]
    # a job that failed without running a single step never got a runner (a spent Actions budget, say), so there is
    # nothing in the code to fix
    not_started = [j["name"] for v in views for j in v["jobs"] if j["conclusion"] == "failure" and not j["steps"]]
    reasons: set[str] = set()
    if not_started:
        for run_id in run_ids:
            reasons.update(_failure_annotations(repo=a.repo, run_id=run_id))
    failed = [j["name"] for j in jobs if j["conclusion"] not in {"success", "skipped"} and j["name"] not in not_started]
    failed_runs = _jobless_failed_runs(views)
    return {
        "events": sorted({v["event"] for v in views}),
        "runs": [
            {"id": run_id, "event": v["event"], "url": v["url"], "conclusion": v["conclusion"]}
            for run_id, v in zip(run_ids, views, strict=True)
        ],
        "passed": not failed and not not_started and not failed_runs,
        "failed_jobs": failed,
        "failed_runs": failed_runs,
        "not_started_jobs": not_started,
        "not_started_reasons": sorted(reasons),
        "jobs": jobs,
    }


def _jobless_failed_runs(views: list[dict[str, Any]]) -> list[str]:
    """List the URL of each run that failed before creating a single job, such as one with an invalid workflow file.

    Such a run has no job to put in failed_jobs, so without this it would count as passed.
    """
    urls: list[str] = []
    for view in views:
        if view["jobs"]:
            continue
        if view["conclusion"] == "success":
            continue
        if view["conclusion"] == "skipped":
            continue
        urls.append(view["url"])
    return urls


def _failure_annotations(*, repo: str, run_id: int) -> list[str]:
    # gh's JSON has no annotations; its text view lists them last, a failure's message after an "X "
    text = _run(cmd=["gh", "run", "view", str(run_id), "--repo", repo])
    __, __, annotations = text.partition("\nANNOTATIONS\n")
    return [line.removeprefix("X ").strip() for line in annotations.splitlines() if line.startswith("X ")]


def _pr_review_state(*, repo: str, pr: str, reviewers: list[ModuleType]) -> dict[str, Any]:
    """Read the PR's head, when its last commit was made, and each reviewer's bodies and last reviewed commit.

    Review and comment bodies are kept apart, oldest first: a review of the head is a verdict even in wording a
    reviewer module does not know, while a comment (a walkthrough, a summary) may still be waiting to be refreshed.
    """
    view = _gh_json("pr", "view", pr, "--repo", repo, "--json", "headRefOid,comments,reviews,commits")
    bodies: dict[str, dict[str, list[str]]] = {r.NAME: {"reviews": [], "comments": []} for r in reviewers}
    last_reviewed: dict[str, str | None] = {r.NAME: None for r in reviewers}
    for kind, stamp in (("reviews", "submittedAt"), ("comments", "createdAt")):
        for item in sorted(view[kind], key=lambda i: i.get(stamp) or ""):
            for reviewer in reviewers:
                if not reviewer.LOGIN.search(item["author"]["login"]):
                    continue
                bodies[reviewer.NAME][kind].append(item["body"])
                if not item.get("commit"):
                    continue
                if not item["body"]:
                    # a review with no text is the reviewer answering a thread, not a review of that commit
                    continue
                last_reviewed[reviewer.NAME] = item["commit"]["oid"]
    return {
        "head": view["headRefOid"],
        "head_committed_at": view["commits"][-1]["committedDate"],
        "bodies": bodies,
        "last_reviewed": last_reviewed,
    }


def _summed_count(total: str | None, count: str) -> str:
    # git numstat writes "-" for a binary file, which has no line counts to add
    if total is None:
        return count
    if total == "-":
        return total
    if count == "-":
        return count
    return str(int(total) + int(count))


def _changes_since(*, checkout: Path, since: str, head: str) -> list[dict[str, str]]:
    """List each file the branch's own commits changed after `since`, with the lines they added and removed.

    Merges and commits already on the default branch are left out, so merging the default branch in (update-branch)
    is not counted as a change the reviewer hasn't seen. A file's counts are summed over the commits that touched it.
    """
    cmd = [
        "git",
        "log",
        "--no-merges",
        "--numstat",
        "--format=",
        f"{since}..{head}",
        "--not",
        f"origin/{_default_branch(checkout)}",
    ]
    res = _attempt(cmd=cmd, cwd=checkout)
    if res.returncode != 0:
        _ = _git("fetch", "--quiet", "origin", cwd=checkout)
        res = _attempt(cmd=cmd, cwd=checkout)
        if res.returncode != 0:
            # an empty list would read as "nothing changed since the last review"
            raise FailError(f"{' '.join(cmd)} failed:\n{(res.stdout + res.stderr).strip()}")
    added: dict[str, str] = {}
    removed: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if not line:
            continue
        lines_added, lines_removed, path = line.split("\t", 2)
        added[path] = _summed_count(added.get(path), lines_added)
        removed[path] = _summed_count(removed.get(path), lines_removed)
    return [{"file": path, "added": added[path], "removed": removed[path]} for path in added]


def _quiet_on_head(*, reviewer: ModuleType, state: dict[str, Any], checkout: Path) -> dict[str, Any] | None:
    """Give a verdict for a reviewer that reviewed this PR before but has stayed quiet about its latest commit.

    A reviewer can leave a small follow-up commit unreviewed without saying so, or say that it is out of allowance or
    still reviewing. Once its module's quiet period has passed since that commit, the verdict reports the silence,
    with the reviewer's own note under held_back when it left one, and the agent judges from the changes since the
    last reviewed commit whether to wait for the review, ask for one, or go on.
    """
    last = state["last_reviewed"][reviewer.NAME]
    if last is None:
        return None
    committed = datetime.datetime.fromisoformat(state["head_committed_at"]).timestamp()
    quiet = time.time() - committed
    if quiet < reviewer.QUIET_AFTER_SECONDS:
        return None
    if reviewer.still_reviewing(state["bodies"][reviewer.NAME]["comments"]):
        return None
    return {
        "verdict": "head_not_reviewed",
        "last_reviewed": last,
        "minutes_since_head_commit": int(quiet // 60),
        "held_back": reviewer.held_back(state["bodies"][reviewer.NAME]["comments"]),
        "changed_since_last_review": _changes_since(checkout=checkout, since=last, head=state["head"]),
    }


def enabled_reviewers(*, checkout: Path, names: list[str]) -> list[ModuleType]:
    if names:
        known = {r.NAME: r for r in REVIEWERS}
        unknown = [n for n in names if n not in known]
        if unknown:
            raise FailError(f"no reviewer module for {', '.join(unknown)}; known: {', '.join(known)}")
        return [known[n] for n in names]
    return [r for r in REVIEWERS if any((checkout / f).is_file() for f in r.CONFIG_FILES)]


_FINDING_KEYS = ("id", "type", "path", "line", "url", "body_text")


def _reviewer_findings(*, repo: str, pr: str, checkout: Path, reviewer: ModuleType) -> list[dict[str, Any]]:
    """List the reviewer's open threads on the PR, read through the pr-comments skill from the checkout.

    The checkout is the working directory, so each thread's line maps to its HEAD; the read script picks its own
    credentials, the stored login first.
    """
    read = Path(__file__).resolve().parent.parent / "pr-comments" / "read.py"
    threads = json.loads(_run(cmd=[str(read), pr, "--repo", repo], cwd=checkout))
    findings: list[dict[str, Any]] = []
    for thread in threads:
        if not reviewer.LOGIN.search(thread["author"]):
            continue
        findings.append({key: thread[key] for key in _FINDING_KEYS})
    return findings


def _add_findings(*, result: dict[str, Any], repo: str, pr: str, checkout: Path, reviewer: ModuleType) -> None:
    """List a flagged reviewer's open findings, and call it settled when none is left open.

    A finding drops out of the open list once it is resolved, or once the user's reply has the last word in it, so a
    flagged review with no open finding left has nothing more to act on.
    """
    try:
        findings = _reviewer_findings(repo=repo, pr=pr, checkout=checkout, reviewer=reviewer)
    except FailError as e:
        # the verdict stands; the agent reads the threads itself
        result["findings_error"] = str(e)
        return
    result["findings"] = findings
    if not findings:
        result["verdict"] = "settled"


def cmd_ai_review(a: argparse.Namespace) -> dict[str, Any]:
    reviewers = enabled_reviewers(checkout=Path(a.checkout), names=a.reviewer)
    if not reviewers:
        return {"verdict": "none_configured", "reviewers": {}}
    verdicts: dict[str, dict[str, Any]] = {}
    latest: dict[str, dict[str, list[str]]] = {}
    verdicts_head = ""

    def all_reviewed() -> str | None:
        nonlocal verdicts_head
        state = _pr_review_state(repo=a.repo, pr=a.pr, reviewers=reviewers)
        # a verdict holds only for the head it was reached on, so a push mid-wait sends every reviewer back to classify
        if state["head"] != verdicts_head:
            verdicts.clear()
            verdicts_head = state["head"]
        bodies = state["bodies"]
        latest.update(bodies)
        for reviewer in reviewers:
            if reviewer.NAME in verdicts:
                continue
            result = _reviewer_verdict(reviewer=reviewer, state=state, repo=a.repo, pr=a.pr, checkout=Path(a.checkout))
            if result is not None:
                verdicts[reviewer.NAME] = result
        if len(verdicts) < len(reviewers):
            return None
        return state["head"]

    try:
        head = _wait(timeout=a.timeout, interval=60, what=f"every AI reviewer on PR {a.pr}", probe=all_reviewed)
    except FailError as e:
        raise _review_timeout(error=e, reviewers=reviewers, verdicts=verdicts, latest=latest) from e
    return {"verdict": _overall_verdict(verdicts), "head": head, "reviewers": verdicts}


def _reviewer_verdict(
    *, reviewer: ModuleType, state: dict[str, Any], repo: str, pr: str, checkout: Path
) -> dict[str, Any] | None:
    bodies = state["bodies"][reviewer.NAME]
    result = reviewer.classify(reviews=bodies["reviews"], comments=bodies["comments"], head=state["head"])
    if result is None:
        result = _quiet_on_head(reviewer=reviewer, state=state, checkout=checkout)
    if result is None:
        return None
    if result["verdict"] == "flagged":
        _add_findings(result=result, repo=repo, pr=pr, checkout=checkout, reviewer=reviewer)
    return result


def _review_timeout(
    *,
    error: FailError,
    reviewers: list[ModuleType],
    verdicts: dict[str, dict[str, Any]],
    latest: dict[str, dict[str, list[str]]],
) -> FailError:
    # only reviewers with no review of the head are still waiting, so "no allowance left" in their last review
    # footer is the likely reason
    waiting = [r for r in reviewers if r.NAME not in verdicts]
    used_up = [r.NAME for r in waiting if r.allowance_used_up(latest.get(r.NAME, {}).get("reviews", []))]
    note = ""
    if used_up:
        note = f"; out of review allowance: {', '.join(used_up)}"
    return FailError(
        f"{error}. Still waiting on {', '.join(r.NAME for r in waiting)}{note}. Verdicts so far: {json.dumps(verdicts)}"
    )


def _overall_verdict(verdicts: dict[str, dict[str, Any]]) -> str:
    # the most serious verdict wins: a finding, then a review nobody could read, then a skipped review
    found = {result["verdict"] for result in verdicts.values()}
    for verdict in ("flagged", "unrecognized", "skipped", "head_not_reviewed", "settled"):
        if verdict in found:
            return verdict
    return "clean"


def cmd_merge_command(a: argparse.Namespace) -> dict[str, Any]:
    settings = _gh_json("repo", "view", a.repo, "--json", "squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed")
    # whether the branch has a merge queue is only readable through `gh api`; if it has one, gh says so and the method
    # flag is dropped
    if settings["squashMergeAllowed"]:
        merge = f"gh pr merge {a.pr} --repo {a.repo} --squash"
    elif settings["rebaseMergeAllowed"]:
        merge = f"gh pr merge {a.pr} --repo {a.repo} --rebase"
    else:
        merge = f"gh pr merge {a.pr} --repo {a.repo} --merge"
    pr = _gh_json("pr", "view", a.pr, "--repo", a.repo, "--json", "isDraft,state,baseRefName,headRefName,headRefOid")
    if pr["state"] != "OPEN":
        raise FailError(f"PR {a.pr} is already {pr['state'].lower()}; there is nothing to merge")
    checkout = Path(a.checkout)
    base = pr["baseRefName"]
    _ = _git("fetch", "--quiet", "origin", base, pr["headRefName"], cwd=checkout)
    behind_by = int(_git("rev-list", "--count", f"{pr['headRefOid']}..origin/{base}", cwd=checkout))
    if behind_by:
        raise FailError(
            f"PR {a.pr}'s branch is {behind_by} commit(s) behind {base}, so CI never ran on what the merge would "
            f"produce: run update-branch on {checkout}, ci on the new head, then the pre-merge check again"
        )
    draft = pr["isDraft"]
    # `tag` confirms the merge afterwards, since gh pr merge can succeed without printing anything
    steps = [merge]
    if draft:
        steps.insert(0, f"gh pr ready {a.pr} --repo {a.repo}")
    return {
        "draft": draft,
        "commands": [f"env -u GITHUB_TOKEN -u GH_TOKEN {step}" for step in steps],
    }


def cmd_tag(a: argparse.Namespace) -> dict[str, Any]:
    def merged() -> str | None:
        view = _gh_json("pr", "view", a.pr, "--repo", a.repo, "--json", "state,mergeCommit")
        if view["state"] == "CLOSED":
            raise FailError(f"PR {a.pr} was closed without merging")
        if view["state"] != "MERGED":
            return None
        return view["mergeCommit"]["oid"]

    merge_sha = _wait(timeout=a.timeout, interval=30, what=f"PR {a.pr} to merge", probe=merged)
    if a.merge_only:
        return {"merge_commit": merge_sha, "tag": None}

    def tagged() -> str | None:
        out = _run(cmd=["git", "ls-remote", "--tags", f"https://github.com/{a.repo}.git"])
        for line in out.splitlines():
            sha, ref = line.split("\t", 1)
            # annotated tags appear twice; the peeled ^{} line carries the commit
            if sha == merge_sha:
                return ref.removeprefix("refs/tags/").removesuffix("^{}")
        return None

    tag = _wait(timeout=a.timeout, interval=30, what=f"a tag on {merge_sha[:9]}", probe=tagged)
    return {"merge_commit": merge_sha, "tag": tag}


def _merged_pr(*, repo: str, branch: str) -> int:
    prs = _gh_json("pr", "list", "--repo", repo, "--head", branch, "--state", "merged", "--json", "number")
    if not prs:
        raise FailError(f"{repo} has no merged PR from {branch}")
    return prs[0]["number"]


def _require_downstream_off_branch(*, checkout: Path, branch: str, downstream: Path) -> str:
    current = _answers_commit(downstream)
    if current is None:
        raise FailError(f"{downstream / ANSWERS} has no _commit")
    match = UNTAGGED_SUFFIX.search(current)
    if match is None:
        return current
    _ = _git("fetch", "--quiet", "origin", branch, cwd=checkout)
    res = _attempt(cmd=["git", "merge-base", "--is-ancestor", match.group(1), f"origin/{branch}"], cwd=checkout)
    if res.returncode == 0:
        raise FailError(f"{downstream} still records {current}, which is on {branch}; re-pin it to the tag first")
    if res.returncode != 1:
        raise FailError(
            f"git merge-base --is-ancestor {match.group(1)} origin/{branch} failed in {checkout}:\n{res.stderr.strip()}"
        )
    return current


def _require_every_child(*, repo: str, downstream: list[Path], chain: dict[str, Any]) -> None:
    given: list[str] = []
    for path in downstream:
        src, __ = _src_and_commit(answers=(path / ANSWERS).read_text(), where=str(path / ANSWERS))
        if _repo_slug(src) != repo:
            raise FailError(f"{path} is generated from {_repo_slug(src)}, not {repo}")
        given.append(_repo_slug(_git("remote", "get-url", "origin", cwd=path).strip()))
    children = [link["repo"] for link in chain["chain"] if link.get("parent") == repo]
    missing = [child for child in children if child not in given]
    if missing:
        raise FailError(
            f"{repo}'s branch is still needed until every repo generated from it is re-pinned; "
            f"also pass --downstream for: {', '.join(missing)}"
        )


def _default_to_switch_to(checkout: Path) -> str:
    """Return the default branch the checkout can move to off the branch being deleted, or refuse before anything is.

    Moving there resets the local default branch to origin's, so a dirty worktree, or a local default branch holding
    commits origin lacks, refuses here: found only after the remote branch is gone, a rerun could no longer delete it.
    """
    dirty = _dirty(checkout)
    if dirty:
        raise FailError(f"{checkout} has uncommitted changes; nothing was deleted:\n" + "\n".join(dirty))
    default = _default_branch(checkout)
    _ = _git("fetch", "--quiet", "origin", default, cwd=checkout)
    if _has_ref(checkout=checkout, ref=f"refs/heads/{default}"):
        unpushed = _git("log", "--oneline", f"origin/{default}..{default}", cwd=checkout).strip()
        if unpushed:
            raise FailError(
                f"{default} in {checkout} has commits not on origin, which moving it to origin/{default} would drop;"
                f" nothing was deleted:\n{unpushed}"
            )
    return default


def _require_branch_pushed(*, checkout: Path, branch: str) -> None:
    if not _has_ref(checkout=checkout, ref=f"refs/remotes/origin/{branch}"):
        return
    unpushed = _git("log", "--oneline", f"origin/{branch}..{branch}", cwd=checkout).strip()
    if unpushed:
        raise FailError(
            f"{branch} in {checkout} has commits not on origin, which deleting it would drop; nothing was deleted:\n"
            f"{unpushed}"
        )


def _delete_branch(*, checkout: Path, branch: str) -> bool:
    has_local = _has_ref(checkout=checkout, ref=f"refs/heads/{branch}")
    switch_to = None
    if has_local:
        _require_branch_pushed(checkout=checkout, branch=branch)
        if _git("symbolic-ref", "--short", "HEAD", cwd=checkout).strip() == branch:
            switch_to = _default_to_switch_to(checkout)
    _ = _git("push", "origin", "--delete", branch, cwd=checkout)
    if not has_local:
        return False
    if switch_to is not None:
        _ = _git("switch", "-C", switch_to, f"origin/{switch_to}", cwd=checkout)
    _ = _git("branch", "-D", branch, cwd=checkout)
    return True


def cmd_delete_branch(a: argparse.Namespace) -> dict[str, Any]:
    """Delete a template repo's merged backport branch once nothing downstream points into it.

    Copier template repos keep merged branches (auto-delete is off), because a repo whose
    answers file records a commit only that branch holds cannot be updated once the branch is
    gone. So the branch goes only when its PR is merged and every repo generated from it (each
    one whose parent in the chain is this repo, since a repo's answers file names only its
    direct parent) records a tag, or a commit the branch does not contain.
    """
    checkout = Path(a.checkout)
    merged_pr = _merged_pr(repo=a.repo, branch=a.branch)
    downstream = [Path(d) for d in a.downstream]
    _require_every_child(repo=a.repo, downstream=downstream, chain=json.loads(Path(a.chain).read_text()))
    current: dict[str, str] = {}
    for path in downstream:
        current[str(path)] = _require_downstream_off_branch(checkout=checkout, branch=a.branch, downstream=path)
    deleted_local = False
    if not a.dry_run:
        deleted_local = _delete_branch(checkout=checkout, branch=a.branch)
    return {
        "repo": a.repo,
        "branch": a.branch,
        "merged_pr": merged_pr,
        "downstream_commits": current,
        "dry_run": a.dry_run,
        "deleted_local": deleted_local,
    }


def _conflict_state(checkout: Path) -> dict[str, list[str]]:
    unmerged = [p for p in _git("diff", "--name-only", "--diff-filter=U", cwd=checkout).splitlines() if p]
    # a file can be marked resolved with its markers still in it, which is what nearly got committed last time
    res = _attempt(cmd=["git", "grep", "-l", "-I", "-E", r"^(<{7} |>{7} )", "--", "."], cwd=checkout)
    markers = [p for p in res.stdout.splitlines() if p]
    return {"unmerged": unmerged, "conflict_markers": markers}


def _require_feature_branch(*, checkout: Path, branch: str) -> None:
    current = _git("symbolic-ref", "--short", "HEAD", cwd=checkout).strip()
    if current != branch:
        raise FailError(f"{checkout} has {current} checked out, not {branch}; someone may be working there")


def _branch_commits(*, checkout: Path, since: str, paths: list[str]) -> dict[str, list[str]]:
    """List the feature branch's own commits touching each conflicted file, newest first.

    A file the branch changed after the backport copied it (an add/add conflict on a helper or a skill) is resolved
    from the default branch's side with those commits re-applied; one the branch never changed since takes the
    default branch's side alone. The list is what tells the two apart.
    """
    commits: dict[str, list[str]] = {}
    for path in paths:
        log = _git("log", "--format=%h %s", f"{since}..HEAD", "--", path, cwd=checkout)
        commits[path] = [line for line in log.splitlines() if line]
    return commits


def _stage_resolved(*, checkout: Path, unmerged: list[str]) -> list[str]:
    """Stage the unmerged paths whose conflict is resolved: text with no marker left, or removed from the tree.

    A binary file has no markers to check, so it is left for the agent to stage by hand once resolved.
    """
    binaries: list[str] = []
    for path in unmerged:
        try:
            content = (checkout / path).read_bytes()
        except FileNotFoundError:
            continue
        if b"\0" in content:
            binaries.append(path)
    if binaries:
        raise FailError(
            "these unmerged files are binary, so nothing shows whether they are resolved; stage them by hand:\n  "
            + "\n  ".join(binaries)
        )
    _ = _git("add", "--", *unmerged, cwd=checkout)
    return unmerged


def cmd_update_branch(a: argparse.Namespace) -> dict[str, Any]:
    """Merge the default branch into a feature branch and push it, or finish a merge whose conflicts are resolved.

    PRs are squash-merged, so the feature branch's own commits never reach the default branch; a merge brings it up
    to date without rewriting its history, resolves any conflict once instead of per commit, and pushes without
    force. A merge that conflicts is left in progress for the agent to resolve and show the user; `--finish` then
    stages the resolved files, commits and pushes, once no conflict marker is left.
    """
    checkout = Path(a.checkout)
    _require_feature_branch(checkout=checkout, branch=a.branch)
    default = _default_branch(checkout)
    staged: list[str] = []
    if a.finish:
        state = _conflict_state(checkout)
        if state["conflict_markers"]:
            raise FailError(f"the merge is not resolved yet: {json.dumps(state)}")
        if state["unmerged"]:
            staged = _stage_resolved(checkout=checkout, unmerged=state["unmerged"])
        if _has_ref(checkout=checkout, ref="MERGE_HEAD"):
            _ = _git("commit", "--no-edit", cwd=checkout)
    else:
        dirty = _dirty(checkout)
        if dirty:
            raise FailError(f"{checkout} has uncommitted changes:\n" + "\n".join(dirty))
        _ = _git("fetch", "--quiet", "origin", cwd=checkout)
        unpushed = ""
        if _has_ref(checkout=checkout, ref=f"origin/{a.branch}"):
            unpushed = _git("log", "--oneline", f"origin/{a.branch}..HEAD", cwd=checkout).strip()
        if unpushed and not a.allow_unpushed:
            raise FailError(
                f"{a.branch} has commits that are not on GitHub yet, which this push would add to its PR; ask the user, "
                f"then rerun with --allow-unpushed if they belong there:\n{unpushed}"
            )
        res = _attempt(cmd=["git", "merge", "--no-edit", f"origin/{default}"], cwd=checkout)
        if res.returncode != 0:
            state = _conflict_state(checkout)
            if not state["unmerged"]:
                raise FailError(f"git merge origin/{default} failed:\n{(res.stdout + res.stderr).strip()}")
            return {
                "branch": a.branch,
                "merged": f"origin/{default}",
                "status": "conflicts",
                **state,
                "branch_commits": _branch_commits(
                    checkout=checkout, since=f"origin/{default}", paths=state["unmerged"]
                ),
                "next": "resolve each file, show the user the resolution, and after their approval rerun with --finish",
            }
    _require_no_leaks(checkout=checkout, branch=a.branch, default=default, chain_file=a.chain)
    _ = _git("push", "origin", a.branch, cwd=checkout)
    return {
        "branch": a.branch,
        "merged": f"origin/{default}",
        "status": "pushed",
        "head": _git("rev-parse", "HEAD", cwd=checkout).strip(),
        "staged": staged,
    }


def cmd_cleanup(a: argparse.Namespace) -> dict[str, Any]:
    worktree = Path(a.worktree).resolve()
    dirty = _dirty(worktree)
    if dirty:
        raise FailError(f"{worktree} has uncommitted changes:\n" + "\n".join(dirty))
    branch = _git("symbolic-ref", "--short", "HEAD", cwd=worktree).strip()
    unpushed = _git("log", "--oneline", f"origin/{branch}..HEAD", cwd=worktree).strip()
    if unpushed:
        raise FailError(f"{branch} has commits not on origin:\n{unpushed}")
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=worktree).strip()).parent
    _ = _git("worktree", "remove", str(worktree), cwd=common)
    return {"removed": str(worktree), "branch": branch}


AddVerb = Callable[[str], argparse.ArgumentParser]


def _add_chain_verbs(add: AddVerb) -> None:
    chain = add("chain")
    chain.add_argument("file", help="the template-managed file, relative to the repo root")
    chain.add_argument("--repo", default=".")
    chain.add_argument(
        "--layer", default=None, help="OWNER/NAME of the template the change goes in, when it is not the file's owner"
    )
    chain.add_argument("--out", default=None, help="also write the chain here, for scan and pr-command")
    chain.add_argument(
        "--also", action="append", default=[], metavar="OWNER/NAME", help="another repo to thread the change through"
    )
    chain.set_defaults(fn=cmd_chain)
    cs = add("consumers")
    cs.add_argument("--template", required=True, help="OWNER/NAME of a template in the chain")
    cs.set_defaults(fn=cmd_consumers)


def _add_checkout_verbs(add: AddVerb) -> None:
    co = add("checkout")
    co.add_argument("--branch", required=True)
    co.add_argument("--path", required=True, help="where the clone or worktree lives")
    co.add_argument("--repo", default=None, help="OWNER/NAME to clone when --path does not exist yet")
    co.add_argument(
        "--worktree-of", default=None, help="make --path a new worktree of this checkout instead of a clone"
    )
    co.set_defaults(fn=cmd_checkout)
    for name, fn in (("behind", cmd_behind), ("push", cmd_push), ("net-diff", cmd_net_diff)):
        sp = add(name)
        sp.add_argument("--checkout", default=".")
        sp.set_defaults(fn=fn)
        if name == "push":
            sp.add_argument(
                "--chain", required=True, help="the chain file, to check commit messages and changes for a public repo"
            )
        if name == "behind":
            sp.add_argument(
                "--parent-checkout",
                default=None,
                help="the parent's checkout on its backport branch, to list catch-ups",
            )
            sp.add_argument(
                "--repo", default=None, help="OWNER/NAME to read from its default branch instead of a checkout"
            )
    sc = add("scan")
    sc.add_argument("--chain", required=True)
    sc.add_argument("--repo", required=True, help="OWNER/NAME the text will be posted to")
    sc.add_argument("--file", required=True)
    sc.set_defaults(fn=cmd_scan)
    op = add("pr-command")
    op.add_argument("--checkout", default=".")
    op.add_argument("--chain", required=True)
    op.add_argument("--title", required=True)
    op.add_argument("--body-file", required=True)
    op.set_defaults(fn=cmd_pr_command)
    pb = add("pr-body")
    pb.add_argument("--checkout", default=".")
    pb.add_argument("--chain", required=True)
    pb.add_argument("--pr", required=True)
    pb.add_argument("--body-file", required=True)
    pb.set_defaults(fn=cmd_pr_body)
    db = add("delete-branch")
    db.add_argument("--repo", required=True, help="OWNER/NAME of the template repo")
    db.add_argument("--branch", required=True)
    db.add_argument("--checkout", required=True, help="a local checkout of that template repo")
    db.add_argument("--chain", required=True, help="the chain file, to know every repo generated from this one")
    db.add_argument(
        "--downstream",
        action="append",
        required=True,
        help="the checkout of a repo generated from this one; one per such repo",
    )
    db.add_argument("--dry-run", action="store_true", help="check the conditions without deleting")
    db.set_defaults(fn=cmd_delete_branch)
    ub = add("update-branch")
    ub.add_argument("--checkout", required=True, help="the checkout that has the feature branch")
    ub.add_argument("--branch", required=True)
    ub.add_argument(
        "--chain", required=True, help="the chain file, to check commit messages and changes for a public repo"
    )
    ub.add_argument("--finish", action="store_true", help="commit and push a merge whose conflicts are resolved")
    ub.add_argument(
        "--allow-unpushed", action="store_true", help="push commits that were not on GitHub yet; only after asking"
    )
    ub.set_defaults(fn=cmd_update_branch)
    cl = add("cleanup")
    cl.add_argument("--worktree", required=True)
    cl.set_defaults(fn=cmd_cleanup)


def _add_github_verbs(add: AddVerb) -> None:
    for name, fn, default_timeout in (
        ("ci", cmd_ci, 3600),
        ("ai-review", cmd_ai_review, 5400),
        ("merge-command", cmd_merge_command, 0),
        ("tag", cmd_tag, 7200),
    ):
        sp = add(name)
        sp.add_argument("--repo", required=True, help="OWNER/NAME")
        sp.set_defaults(fn=fn)
        sp.add_argument("--timeout", type=int, default=default_timeout, help="seconds")
        if name == "ci":
            sp.add_argument("--sha", required=True)
            sp.add_argument(
                "--checkout",
                default=None,
                help="no longer used: runs are found by commit, whatever their event",
            )
        else:
            sp.add_argument("--pr", required=True)
        if name == "tag":
            sp.add_argument(
                "--merge-only", action="store_true", help="return once merged; for a repo that does not tag on merge"
            )
        if name == "merge-command":
            sp.add_argument(
                "--checkout", required=True, help="a local checkout of the repo, to check the branch against its base"
            )
        if name == "ai-review":
            sp.add_argument(
                "--checkout", default=".", help="a local checkout of the repo, to see which reviewers it configures"
            )
            sp.add_argument(
                "--reviewer", action="append", default=[], help="only these reviewers (default: every configured one)"
            )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    _add_chain_verbs(sub.add_parser)
    _add_checkout_verbs(sub.add_parser)
    _add_github_verbs(sub.add_parser)
    return p


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        # one line, so it can be read back with jq or tail -1 even when uv adds its own lines
        print(json.dumps(a.fn(a)))  # noqa: T201 # the JSON on stdout is the interface
    except FailError as e:
        print(f"error: {e}", file=sys.stderr)  # noqa: T201 # errors go to stderr for the caller
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
