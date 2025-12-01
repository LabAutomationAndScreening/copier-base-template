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

# Save mount information (device, mount point, and filesystem type)
mountInfoFile=$(mktemp)
mount | grep -E "$repoName/(.*/)?(\.pnpm-store|node_modules|\.venv)" | awk '{print $1 "|" $3 "|" $5}' > "$mountInfoFile" || true
echo "Saved mount information:"
cat "$mountInfoFile"

# Unmount specific directories (.pnpm-store, node_modules, .venv)
echo "Unmounting directories..."
if [ -s "$mountInfoFile" ]; then
    while IFS='|' read -r device mountPath fsType; do
        if [ -n "$mountPath" ] && [ -d "$mountPath" ]; then
            echo "Unmounting $mountPath..."
            sudo umount "$mountPath" 2>/dev/null || sudo umount -l "$mountPath" 2>/dev/null || echo "Warning: Could not unmount $mountPath"
        fi
    done < "$mountInfoFile"
else
    echo "No mounts found to unmount."
fi

sudo rm -rf "./$repoName" || true
sudo rm -rf "./$repoName/*.md"
mkdir -p "./$repoName"

# Create a temporary directory for cloning
tmpdir=$(mktemp -d)

# Clone the repository
git clone "$gitUrl" "$tmpdir/$repoName"

# Enable dotglob so that '*' includes hidden files
shopt -s dotglob

# Move all contents (including hidden files) from the cloned repo to the target folder
mv "$tmpdir/$repoName"/* "./$repoName/"

# Clean up: remove the temporary directory
rm -rf "$tmpdir"

# Remount directories using saved mount information
echo "Remounting directories..."
while IFS='|' read -r device mountPath fsType; do
    if [ -n "$mountPath" ] && [ -n "$device" ]; then
        echo "Recreating directory $mountPath..."
        mkdir -p "$mountPath"

        echo "Remounting $device to $mountPath..."
        sudo mount -t "$fsType" "$device" "$mountPath" && echo "Successfully remounted $mountPath" || echo "Warning: Failed to remount $mountPath"

        # Verify the mount worked correctly
        if mount | grep -q "$mountPath"; then
            echo "✓ Mount verified for $mountPath"
            # Check if it has the wrong content (system folders instead of actual content)
            if [ -d "$mountPath/data" ] && [ -d "$mountPath/isocache" ] && [ -d "$mountPath/lost+found" ]; then
                echo "⚠ WARNING: $mountPath contains system folders (data/isocache/lost+found) - wrong volume mounted!"
                echo "   Device: $device"
                echo "   This volume may need to be deleted and recreated."
            fi
        else
            echo "✗ Mount verification failed for $mountPath"
        fi
    fi
done < "$mountInfoFile"

rm -f "$mountInfoFile"

echo ""
echo "Repository '$repoName' has been updated."
