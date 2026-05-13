import argparse
import subprocess


def ensure_tag_not_present(tag: str, remote: str) -> None:
    try:
        _ = subprocess.run(  # noqa: S603 # this is trusted input, it's our own arguments being passed in
            ["git", "ls-remote", "--exit-code", "--tags", remote, f"refs/tags/{tag}"],  # noqa: S607 # if `git` isn't in PATH already, then there are bigger problems to solve
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        raise Exception(f"Error: tag '{tag}' exists on remote '{remote}'")  # noqa: TRY002 # not worth a custom exception
    except subprocess.CalledProcessError:
        # tag not present, continue
        return


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Confirm that git tag v<version> is not present on a remote, or create and push the tag.")
    )
    _ = parser.add_argument(
        "--version",
        required=True,
        help="Version string (e.g. 1.0.6); the tag will be v<version>",
    )
    _ = parser.add_argument(
        "--confirm-tag-not-present",
        action="store_true",
        help="Check that git tag v<version> is NOT present on the remote. If the tag exists, exit with an error.",
    )
    _ = parser.add_argument(
        "--push-tag-to-remote",
        action="store_true",
        help="Create git tag v<version> locally and push it to the remote. Internally confirms the tag is not already present.",
    )
    _ = parser.add_argument(
        "--remote",
        default="origin",
        help="Name of git remote to query/push (default: origin)",
    )
    args = parser.parse_args()

    tag = args.version if args.version.startswith("v") else f"v{args.version}"

    if args.push_tag_to_remote:
        ensure_tag_not_present(tag, args.remote)
        _ = subprocess.run(["git", "tag", tag], check=True)  # noqa: S603,S607 # this is trusted input, it's our own pyproject.toml file. and if `git` isn't in PATH, then there are larger problems anyway
        _ = subprocess.run(["git", "push", args.remote, tag], check=True)  # noqa: S603,S607 # this is trusted input, it's our own pyproject.toml file. and if `git` isn't in PATH, then there are larger problems anyway
        return

    if args.confirm_tag_not_present:
        ensure_tag_not_present(tag, args.remote)


if __name__ == "__main__":
    main()
