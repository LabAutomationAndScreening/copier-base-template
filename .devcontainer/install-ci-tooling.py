import argparse
import os
import subprocess
import sys
from pathlib import Path

UV_VERSION = "0.12.15"
PNPM_VERSION = "12.4.2"
COPIER_VERSION = "9.18.2"
COPIER_TEMPLATE_EXTENSIONS_VERSION = "0.3.3"
PRE_COMMIT_VERSION = "4.6.2"
TASK_VERSION = "3.53.1"
DOWNLOAD_TIMEOUT_SECONDS = 90
# Where uv places both itself and the executables of the tools it installs; already on PATH.
LOCAL_BIN_DIR = Path.home() / ".local" / "bin"
parser = argparse.ArgumentParser(description="Install CI tooling for the repo")
_ = parser.add_argument(
    "--no-python",
    default=False,
    action="store_true",
    help="Do not process any environments using python package managers",
)
_ = parser.add_argument(
    "--python-version",
    default=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    type=str,
    help="What version to install.",
)


def install_uv(uv_env: dict[str, str]) -> None:
    """Install the pinned uv release into `LOCAL_BIN_DIR`.

    POSIX only, like the rest of this script: this repo's CI never runs on Windows, unlike the
    copy of this file in the template.

    Runs regardless of `--no-python`, because uv is also how Task is installed, and every job needs
    the task runner even when it has no Python environments to set up.
    """
    _ = subprocess.run(  # noqa: S602 # we need to set shell to true to use the pipe operator, and this is all our own input
        f"curl -fsSL --connect-timeout 20 --max-time 40 --retry 3 --retry-delay 5 --retry-connrefused --proto '=https' https://astral.sh/uv/{UV_VERSION}/install.sh | sh",
        check=True,
        shell=True,
        env=uv_env,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    # TODO: add uv autocompletion to the shell https://docs.astral.sh/uv/getting-started/installation/#shell-autocompletion


def install_task(uv_path: str, uv_env: dict[str, str]) -> None:
    """Install the pinned Task release into `LOCAL_BIN_DIR` as a uv tool.

    `go-task-bin` repackages the upstream release archives as one wheel per platform, so a single uv
    invocation covers every OS and architecture this repo and the template build on. Task publishes
    nothing to PyPI itself, so this is knowingly a third-party distribution: the version is pinned
    and uv records the wheel hash in the tool receipt it writes.

    Deliberately not `npm install -g @go-task/cli`: that writes to the global prefix of whichever
    node is on PATH, and in CI that is the pnpm-managed node installed by `pnpm/setup`, whose prefix
    bin directory is not the one on PATH. The package installs successfully and the linked
    executable is then unreachable, so `task` fails with exit status 127.

    Verification goes through the absolute path because this process resolved PATH before the
    install; `GITHUB_PATH` is appended so later steps in the same CI job can invoke `task` by name.
    """
    _ = subprocess.run(  # noqa: S603 # this is all our own input
        [uv_path, "tool", "install", f"go-task-bin=={TASK_VERSION}"],
        check=True,
        env=uv_env,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    _ = subprocess.run([str(LOCAL_BIN_DIR / "task"), "--version"], check=True)  # noqa: S603 # this is all our own input
    if "GITHUB_PATH" in os.environ:
        with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as github_path_file:
            _ = github_path_file.write(f"{LOCAL_BIN_DIR}\n")


def main():
    args = parser.parse_args(sys.argv[1:])
    uv_env = dict(os.environ)
    uv_env.update({"UV_PYTHON_PREFERENCE": "only-system", "UV_PYTHON": args.python_version})
    uv_path = "uv"
    pnpm_install_sequence = ["npm -v", f"npm install -g pnpm@{PNPM_VERSION}", "pnpm -v"]
    for cmd in pnpm_install_sequence:
        _ = subprocess.run([cmd], shell=True, check=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)  # noqa: S602 # we need shell=True for npm commands, and this is all our own input
    install_uv(uv_env)
    if not args.no_python:
        _ = subprocess.run(  # noqa: S603 # this is all our own input
            [
                uv_path,
                "tool",
                "install",
                f"copier=={COPIER_VERSION}",
                "--with",
                f"copier-template-extensions=={COPIER_TEMPLATE_EXTENSIONS_VERSION}",
            ],
            check=True,
            env=uv_env,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
        _ = subprocess.run(  # noqa: S603 # this is all our own input
            [
                uv_path,
                "tool",
                "install",
                f"pre-commit=={PRE_COMMIT_VERSION}",
            ],
            check=True,
            env=uv_env,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    install_task(uv_path, uv_env)
    _ = subprocess.run(  # noqa: S603 # this is all our own input
        [
            uv_path,
            "tool",
            "list",
        ],
        check=True,
        env=uv_env,
    )


if __name__ == "__main__":
    main()
