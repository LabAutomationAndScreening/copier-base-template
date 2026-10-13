#!/bin/bash
set -ex

python .devcontainer/install-ci-tooling.py

git config --global --add --bool push.autoSetupRemote true
git config --local core.symlinks true

sh .devcontainer/create-aws-profile.sh

# The Biome VS Code extension starts a session per workspace folder and warns when folders nest. The root folder's
# session already covers the nested ones, so Biome is switched off in their (gitignored) folder settings.
root_folder_path="."
for workspace_file in *.code-workspace; do
    if [ ! -f "$workspace_file" ]; then
        continue
    fi
    folders=$(sed -n 's/^[[:space:]]*"path":[[:space:]]*"\([^"]*\)".*/\1/p' "$workspace_file")
    if ! echo "$folders" | grep -qxF "$root_folder_path"; then
        continue
    fi
    printf '%s\n' "$folders" | while IFS= read -r folder; do
        if [ "$folder" != "$root_folder_path" ] && [ -d "$folder" ] && [ ! -e "$folder/.vscode/settings.json" ]; then
            mkdir -p "$folder/.vscode"
            echo '{ "biome.enabled": false }' >"$folder/.vscode/settings.json"
        fi
    done
done
