#!/bin/bash

# If you are using a Windows host and you initially cloned the repository directly onto your hard drive, you may run into file permission issues when running copier updates. To avoid these, after initially building the devcontainer, run this from the repo root:
# cp .devcontainer/windows-host-helper.sh ../
# cd ..
# bash windows-host-helper.sh <git-url>

# If you're still having issues, make sure in Windows Developer Settings that you enabled Developer Mode, and also that you set your git config to have `core.autocrlf=false` and `core.symlinks=true` globally

set -e  # Exit immediately on error

if [ -z "$BASH_VERSION" ]; then
  echo "Error: This script must be run with bash (e.g., 'bash windows-host-helper.sh')." >&2
  exit 1
fi

# Check for the git URL argument
if [ -z "$1" ]; then
    echo "Usage: $0 <git-url>"
    exit 1
fi

gitUrl="$1"

# Extract repository name (removes .git suffix if present)
repoName=$(basename "$gitUrl" .git)

echo "Repo name extracted as '$repoName'"

# Remove any existing subfolder with the repository name and recreate it
# Save mount information before unmounting (only for specific mount types)
mountInfoFile=$(mktemp)
mount | grep -E "$repoName/(.*/)?(\.pnpm-store|node_modules|\.venv)" > "$mountInfoFile" || true
echo "Saved mount information to $mountInfoFile"

# Unmount only specific directories (.pnpm-store, node_modules, .venv)
echo "Checking for mounted directories..."
if [ -s "$mountInfoFile" ]; then
    while IFS= read -r line; do
        mountPath=$(echo "$line" | awk '{print $3}')
        echo "Unmounting $mountPath..."
        sudo umount "$mountPath" 2>/dev/null || sudo umount -l "$mountPath" 2>/dev/null || echo "Warning: Could not unmount $mountPath"
    done < "$mountInfoFile"
else
    echo "No specific mounts found to unmount."
fi

sudo rm -rf "./$repoName" || true # sometimes deleting the .venv folder fails
sudo rm -rf "./$repoName/*.md" # for some reason, sometimes md files are left behind
mkdir -p "./$repoName"

# Create a temporary directory for cloning
tmpdir=$(mktemp -d)

# Clone the repository into a subfolder inside the temporary directory.
# This creates "$tmpdir/$repoName" with the repository's contents.
git clone "$gitUrl" "$tmpdir/$repoName"

# Enable dotglob so that '*' includes hidden files
shopt -s dotglob

# Move all contents (including hidden files) from the cloned repo to the target folder
mv "$tmpdir/$repoName"/* "./$repoName/"

# Clean up: remove the temporary directory
rm -rf "$tmpdir"

# Remount directories using saved mount information
echo "Remounting previously mounted directories..."
while IFS= read -r line; do
    device=$(echo "$line" | awk '{print $1}')
    mountPath=$(echo "$line" | awk '{print $3}')
    fsType=$(echo "$line" | awk '{print $5}')

    if [ -d "$mountPath" ]; then
        echo "Remounting $mountPath from $device..."
        sudo mount -t "$fsType" "$device" "$mountPath" || echo "Warning: Failed to remount $mountPath"
    else
        echo "Creating and remounting $mountPath from $device..."
        mkdir -p "$mountPath"
        sudo mount -t "$fsType" "$device" "$mountPath" || echo "Warning: Failed to remount $mountPath"
    fi
done < "$mountInfoFile"

rm -f "$mountInfoFile"

echo "Repository '$repoName' has been updated."
