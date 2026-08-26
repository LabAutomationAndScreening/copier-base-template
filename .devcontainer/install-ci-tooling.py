import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

UV_VERSION = "0.12.6"
PNPM_VERSION = "11.22.0"
COPIER_VERSION = "9.17.1"
COPIER_TEMPLATE_EXTENSIONS_VERSION = "0.3.3"
PRE_COMMIT_VERSION = "4.6.2"
TASK_VERSION = "3.53.1"
# Bounds every command that fetches over the network. Downloads here take a few seconds, so this is
# generous, while still failing inside the CI jobs' budget -- they cap at 8 minutes and share that
# with a mutex wait, so an unbounded fetch gets killed by the job timeout with no indication of which
# one hung. `TimeoutExpired` names the command instead.
DOWNLOAD_TIMEOUT_SECONDS = 90
# Where both uv's and Task's installers place binaries. Resolves from USERPROFILE on Windows, so it
# matches the runner's home directory without assuming its user name. Already on PATH on POSIX, but
# not on Windows, which is why uv is invoked through an absolute path there.
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


def pwsh_cmd(cmd: str) -> list[str]:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        raise FileNotFoundError("Neither 'pwsh' nor 'powershell' found on PATH")
    return [pwsh, "-NoProfile", "-NonInteractive", "-Command", cmd]


def install_task() -> None:
    """Install the pinned Task release into a bin directory that is already on PATH.

    POSIX only, unlike the equivalent in the template: this repo's CI never runs on Windows.

    Deliberately not `npm install -g @go-task/cli`: that writes to the global prefix of whichever
    node is on PATH, and in CI that is the pnpm-managed node installed by `pnpm/setup`, whose prefix
    bin directory is not the one on PATH. The package installs successfully and the linked
    executable is then unreachable, so `task` fails with exit status 127.

    Verification uses the absolute path rather than PATH, and the bin directory is appended to
    `GITHUB_PATH` so that later steps in the same CI job can invoke `task` by name.
    """
    LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
    # The installer resolves the pinned tag against the published checksums, so the archive is verified
    _ = subprocess.run(  # noqa: S602 # we need to set shell to true to use the pipe operator, and this is all our own input
        f"curl -fsSL --connect-timeout 20 --max-time 40 --retry 3 --retry-delay 5 --retry-connrefused --proto '=https' https://taskfile.dev/install.sh | sh -s -- -b {LOCAL_BIN_DIR} v{TASK_VERSION}",
        check=True,
        shell=True,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    _ = subprocess.run([str(LOCAL_BIN_DIR / "task"), "--version"], check=True)  # noqa: S603 # this is all our own input
    if "GITHUB_PATH" in os.environ:
        with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as github_path_file:
            _ = github_path_file.write(f"{LOCAL_BIN_DIR}\n")


def main():
    args = parser.parse_args(sys.argv[1:])
    is_windows = platform.system() == "Windows"
    uv_env = dict(os.environ)
    uv_env.update({"UV_PYTHON_PREFERENCE": "only-system", "UV_PYTHON": args.python_version})
    if is_windows:
        uv_path = str(LOCAL_BIN_DIR / "uv")
    else:
        uv_path = "uv"

    pnpm_install_sequence = ["npm -v", f"npm install -g pnpm@{PNPM_VERSION}", "pnpm -v"]
    for cmd in pnpm_install_sequence:
        _ = subprocess.run([cmd], shell=True, check=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)  # noqa: S602 # we need shell=True for npm commands, and this is all our own input
    if not args.no_python:
        if is_windows:
            uv_env.update({"PATH": rf"{LOCAL_BIN_DIR};{uv_env['PATH']}"})
            # invoke installer in a pwsh process
            _ = subprocess.run(  # noqa: S603 # this is all our own input
                pwsh_cmd(f"irm https://astral.sh/uv/{UV_VERSION}/install.ps1 | iex"),
                check=True,
                env=uv_env,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
        else:
            _ = subprocess.run(  # noqa: S602 # we need to set shell to true to use the pipe operator, and this is all our own input
                f"curl -fsSL --connect-timeout 20 --max-time 40 --retry 3 --retry-delay 5 --retry-connrefused --proto '=https' https://astral.sh/uv/{UV_VERSION}/install.sh | sh",
                check=True,
                shell=True,
                env=uv_env,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
            # TODO: add uv autocompletion to the shell https://docs.astral.sh/uv/getting-started/installation/#shell-autocompletion
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
        _ = subprocess.run(  # noqa: S603 # this is all our own input
            [
                uv_path,
                "tool",
                "list",
            ],
            check=True,
            env=uv_env,
        )
    install_task()


if __name__ == "__main__":
    main()
