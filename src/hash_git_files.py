"""Used typically to calculate if all the files in the context of building a Docker image have changed or not."""

import argparse
import subprocess
import sys
import zlib
from pathlib import Path


def get_tracked_files(repo_path: Path) -> list[str]:
    """Return a list of files tracked by Git in the given repository folder, using the 'git ls-files' command."""
    try:
        result = subprocess.run(  # noqa: S603 # there's no concern about executing untrusted input, only we will call this script
            ["git", "-C", str(repo_path), "ls-files"],  # noqa: S607 # yes, this is not using a complete executable path, but it's just git and git should always be present in PATH
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.splitlines()

    except subprocess.CalledProcessError:
        print("Error: The directory does not appear to be a Git repository or Git is not installed.", file=sys.stderr)  # noqa: T201 # this just runs as a simple script, so using print instead of log
        sys.exit(1)


def compute_adler32(repo_path: Path, files: list[str]) -> int:
    """Compute an overall Adler-32 checksum of the provided files.

    The checksum incorporates both the file names and their contents. Files are processed in sorted order to ensure consistent ordering.
    """
    checksum = 1  # Adler-32 default starting value

    for file in sorted(files):
        file_path = repo_path / file  # Use pathlib to combine paths
        # Update the checksum with the file name (encoded as bytes)
        checksum = zlib.adler32(file.encode("utf-8"), checksum)
        try:
            with file_path.open("rb") as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    checksum = zlib.adler32(chunk, checksum)
        except Exception as e:
            print(f"Error reading file {file}: {e}", file=sys.stderr)  # noqa: T201 # this just runs as a simple script, so using print instead of log
            raise

    return checksum


def main():
    parser = argparse.ArgumentParser(
        description="Compute an Adler-32 checksum of all Git-tracked files in the specified folder."
    )
    _ = parser.add_argument("folder", type=Path, help="Path to the Git repository folder")
    _ = parser.add_argument("--debug", action="store_true", help="Print all discovered Git-tracked files")
    args = parser.parse_args()

    repo_path = args.folder
    if not repo_path.is_dir():
        print(f"Error: {repo_path} is not a valid directory.", file=sys.stderr)  # noqa: T201 # this just runs as a simple script, so using print instead of log
        sys.exit(1)

    # Retrieve the list of Git-tracked files.
    files = get_tracked_files(repo_path)

    # If the debug flag is specified, print out all discovered files.
    if args.debug:
        print("Tracked files discovered:")  # noqa: T201 # this just runs as a simple script, so using print instead of log
        for file in files:
            print(file)  # noqa: T201 # this just runs as a simple script, so using print instead of log

    # Compute and print the overall Adler-32 checksum.
    overall_checksum = compute_adler32(repo_path, files)
    # Format the checksum as an 8-digit hexadecimal value.
    print(f"{overall_checksum:08x}")  # noqa: T201 # need to print this so that the value can be picked up via STDOUT when calling this in a CI pipeline or as a subprocess


if __name__ == "__main__":
    main()
