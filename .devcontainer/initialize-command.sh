# CodeSpaces build environments get cluttered and need to be pruned https://github.com/orgs/community/discussions/50403
# There was an error encountered during the codespace build using `docker system prune`, so switched to `docker image prune`: Error: The expected container does not exist.
set -ex

printenv
if [ -n "$CODESPACES" ] && [ "$CODESPACES" = "true" ]; then
    docker image prune --all --force
fi

# "Clone Repository in Container Volume" runs this inside a bootstrap container that has the cloned volume mounted at /workspaces.
# The compose bind mount of `..` then points at a path the Docker host doesn't have, so it gets retargeted onto /workspaces where VS Code's own volume mount replaces it.
workspace_mount_type=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/workspaces"}}{{.Type}}{{end}}{{end}}' "$HOSTNAME" 2>/dev/null || true)
if [ "$workspace_mount_type" = "volume" ]; then
    echo "WORKSPACE_MOUNT_TARGET=/workspaces" > .devcontainer/.env
else
    : > .devcontainer/.env
fi
