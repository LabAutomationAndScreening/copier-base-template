"""Move rendered files to where the calling template wants them, as declared in .config/copier-renames.json.

Run as a copier task after rendering and before copier_provenance.py, which reads the same file so the
manifest lists each moved file at the path it actually occupies.
"""

import argparse
import shutil
import sys
from pathlib import Path

# The task scripts run as plain files from the template checkout, where child templates symlink them into a
# different package path, so the sibling module is found through the script's own directory rather than
# through a package. pyrefly resolves imports from the repo root and cannot see that directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from copier_provenance import load_renames  # pyrefly: ignore[missing-import]
from copier_provenance import rename_applies  # pyrefly: ignore[missing-import]

# ruff: noqa: T201 # the task needs to print to stdout to show anything


def apply_renames(*, template_dir: Path, dst_dir: Path) -> None:
    for rename in load_renames(template_dir):
        source = dst_dir / rename["source"]
        if not source.is_file():
            continue
        if not rename_applies(dst_dir, rename):
            print(f"Skipped {rename['source']} to {rename['target']}: target directory does not exist")
            continue
        # A fresh render at the source replaces whatever an earlier update left at the target.
        _ = shutil.move(source, dst_dir / rename["target"])
        print(f"Moved {rename['source']} to {rename['target']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the template's declared post-render file moves")
    _ = parser.add_argument("src_template_dir", type=Path, help="Template source directory")
    _ = parser.add_argument("dst_dir", type=Path, help="Destination directory")
    args = parser.parse_args()
    apply_renames(template_dir=Path(args.src_template_dir), dst_dir=Path(args.dst_dir))


if __name__ == "__main__":
    main()
