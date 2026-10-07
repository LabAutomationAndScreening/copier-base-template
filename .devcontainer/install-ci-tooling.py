import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

UV_VERSION = "0.12.23"
PNPM_VERSION = "12.9.1"
COPIER_VERSION = "==9.18.2"
COPIER_TEMPLATE_EXTENSIONS_VERSION = "==0.3.3"
PRE_COMMIT_VERSION = "==4.6.2"
# identify decides which files each pre-commit hook runs on, so a floating version silently changes what CI checks
IDENTIFY_VERSION = "==2.6.20"
PREK_VERSION = "==0.5.5"
TASK_VERSION = "==3.53.1"
DOWNLOAD_TIMEOUT_SECONDS = 90
# CI runners regularly see transient network failures (connection resets, DNS blips, registry 5xx), so every step that
# touches the network is retried with exponential backoff before the job is failed.
NETWORK_ATTEMPTS = 4
FIRST_RETRY_DELAY_SECONDS = 5
# --fail turns an HTTP error into a non-zero exit instead of saving the error page as the download
CURL_DOWNLOAD_ARGS = [
    "--fail",
    "--silent",
    "--show-error",
    "--location",
    "--proto",
    "=https",
    "--connect-timeout",
    "20",
    "--max-time",
    "60",
]
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


def run_with_retries(
    cmd: list[str],
    *,
    description: str,
    env: dict[str, str] | None = None,
    shell: bool = False,
    timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
) -> None:
    """Run a network-dependent command, retrying with exponential backoff on failure or timeout.

    The final attempt is run outside the retry handling so that its exception propagates unchanged, carrying the
    command and exit status of the failure that ended the job.
    """
    delay = FIRST_RETRY_DELAY_SECONDS
    for attempt in range(1, NETWORK_ATTEMPTS):
        try:
            run_process_tree(cmd, env=env, shell=shell, timeout=timeout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            print(  # noqa: T201 # we want the script to print to console for easy viewing
                f"{description} failed on attempt {attempt} of {NETWORK_ATTEMPTS} ({error}); retrying in {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
        else:
            return
    print(f"{description}: final attempt {NETWORK_ATTEMPTS} of {NETWORK_ATTEMPTS}", file=sys.stderr)  # noqa: T201 # we want the script to print to console for easy viewing
    run_process_tree(cmd, env=env, shell=shell, timeout=timeout)


def run_process_tree(cmd: list[str], *, env: dict[str, str] | None, shell: bool, timeout: int) -> None:
    """Run a command like `subprocess.run(check=True, timeout=...)`, but kill its whole process tree on timeout.

    `subprocess.run` kills only its direct child, so a timed-out `sh -c 'npm ...'` or `sh uv-installer.sh` leaves the
    npm or curl underneath it running, racing the retry that follows. Starting the command in its own session makes it
    the leader of a process group that can be killed as a unit.
    """
    with subprocess.Popen(cmd, env=env, shell=shell, start_new_session=True) as process:  # noqa: S603 # this is all our own input
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            _ = process.wait()
            raise
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def install_uv(uv_path: str, uv_env: dict[str, str]) -> None:
    """Install the pinned uv release into `LOCAL_BIN_DIR`.

    POSIX only, like the rest of this script: this repo's CI never runs on Windows, unlike the
    copy of this file in the template.

    Runs regardless of `--no-python`, because uv is also how Task is installed, and every job needs
    the task runner even when it has no Python environments to set up.
    """
    # Downloaded to a file rather than piped into sh: a pipeline takes sh's exit status, so a download that dies
    # partway hands sh an empty or truncated script that still exits 0 without installing anything.
    with tempfile.TemporaryDirectory() as tmp_dir:
        installer_path = Path(tmp_dir) / "uv-installer.sh"
        run_with_retries(
            [
                "curl",
                *CURL_DOWNLOAD_ARGS,
                "--output",
                str(installer_path),
                f"https://astral.sh/uv/{UV_VERSION}/install.sh",
            ],
            description="Downloading the uv installer",
            env=uv_env,
        )
        # the installer downloads the uv binary itself, so it needs retrying too
        run_with_retries(["sh", str(installer_path)], description="Running the uv installer", env=uv_env)
    # TODO: add uv autocompletion to the shell https://docs.astral.sh/uv/getting-started/installation/#shell-autocompletion
    if shutil.which(uv_path, path=uv_env["PATH"]) is None:
        raise FileNotFoundError(f"The uv installer reported success but {uv_path} is not on PATH ({uv_env['PATH']})")
    _ = subprocess.run([uv_path, "--version"], check=True, env=uv_env)  # noqa: S603 # this is all our own input


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
    run_with_retries(
        [uv_path, "tool", "install", f"go-task-bin{TASK_VERSION}"],
        description="Installing Task",
        env=uv_env,
    )
    _ = subprocess.run([str(LOCAL_BIN_DIR / "task"), "--version"], check=True)  # noqa: S603 # this is all our own input
    if "GITHUB_PATH" in os.environ:
        with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as github_path_file:
            _ = github_path_file.write(f"{LOCAL_BIN_DIR}\n")


def main():
    args = parser.parse_args(sys.argv[1:])
    uv_env = dict(os.environ)
    uv_env.update(
        {
            "UV_PYTHON_PREFERENCE": "only-system",
            "UV_PYTHON": args.python_version,
            # uv's own per-request retries (default 3) absorb most registry blips before run_with_retries has to
            "UV_HTTP_RETRIES": "5",
        }
    )
    uv_path = "uv"
    node_env = dict(os.environ)
    # npm's own per-request retries, so a registry blip is absorbed before run_with_retries reruns the whole command
    node_env.update(
        {
            "npm_config_fetch_retries": "5",
            "npm_config_fetch_retry_mintimeout": "10000",
            "npm_config_fetch_retry_maxtimeout": "60000",
        }
    )
    pnpm_install_sequence = ["npm -v", f"npm install -g pnpm@{PNPM_VERSION}", "pnpm -v"]
    for cmd in pnpm_install_sequence:
        run_with_retries([cmd], description=f"Running '{cmd}'", env=node_env, shell=True)  # noqa: S604 # we need shell=True for npm commands, and this is all our own input
    install_uv(uv_path, uv_env)
    if not args.no_python:
        run_with_retries(
            [
                uv_path,
                "tool",
                "install",
                f"copier{COPIER_VERSION}",
                "--with",
                f"copier-template-extensions{COPIER_TEMPLATE_EXTENSIONS_VERSION}",
            ],
            description="Installing copier",
            env=uv_env,
        )
        run_with_retries(
            [
                uv_path,
                "tool",
                "install",
                f"pre-commit{PRE_COMMIT_VERSION}",
                "--with",
                f"identify{IDENTIFY_VERSION}",
            ],
            description="Installing pre-commit",
            env=uv_env,
        )
        run_with_retries(
            [
                uv_path,
                "tool",
                "install",
                f"prek{PREK_VERSION}",
            ],
            description="Installing prek",
            env=uv_env,
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
