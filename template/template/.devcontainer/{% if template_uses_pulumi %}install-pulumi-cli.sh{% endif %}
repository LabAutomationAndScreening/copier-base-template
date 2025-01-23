#!/usr/bin/env sh

# Check if a file argument is provided
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <uv-lock-file>"
  exit 1
fi

UV_LOCK_FILE="$1"

# Check if the file exists
if [ ! -f "$UV_LOCK_FILE" ]; then
  echo "Error: File '$UV_LOCK_FILE' does not exist."
  exit 1
fi

MATCH=$(grep -o 'pulumi-(\d+\.\d+\.\d+)-py3' "$UV_LOCK_FILE" | awk -F '-' '{print $2}' | xargs)
# Check if there is exactly one match
if [ "$(echo "$MATCH" | wc -l)" -ne 1 ]; then
  echo "Error: Expected exactly one match, found $(echo "$MATCH" | wc -l)"
  exit 1
fi

# Check the current Pulumi version
if ~/.pulumi/bin/pulumi version > /dev/null 2>&1; then
  INSTALLED_VERSION=$(~/.pulumi/bin/pulumi version | sed 's/^v//' | xargs)
  echo "Pulumi is already installed. Current version: v$INSTALLED_VERSION"
  if [ "$INSTALLED_VERSION" = "$MATCH" ]; then
    echo "Pulumi version $MATCH is already installed. Skipping installation."
    exit 0
  else
    echo "Pulumi version mismatch. Expected $MATCH, found $INSTALLED_VERSION. Proceeding with installation."
  fi
else
  echo "Pulumi is not installed or not available in the expected location. Proceeding with installation."
fi

echo "Installing Pulumi version $MATCH..."
curl -fsSL https://get.pulumi.com | sh -s -- --version "$MATCH"
~/.pulumi/bin/pulumi version
