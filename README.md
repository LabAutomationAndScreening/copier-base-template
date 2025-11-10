[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)
[![Actions status](https://github.com/LabAutomationAndScreening/copier-base-template/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/LabAutomationAndScreening/copier-base-template/actions)
[![Open in Dev Containers](https://img.shields.io/static/v1?label=Dev%20Containers&message=Open&color=blue)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/LabAutomationAndScreening/copier-base-template)

# Instantiating a new repository using this template
1. Use the file `.devcontainer/devcontainer-to-instantiate-template.json` to create a devcontainer (or just use the default Codespace devcontainer)
1. Inside that devcontainer, run `python .devcontainer/install-ci-tooling.py` to install necessary tooling to instantiate the template (you can copy/paste the script from this repo...and you can paste it in the root of the repo if you want)
1. Delete all files currently in the repository. Optional...but makes it easiest to avoid git conflicts.
1. Run copier to instantiate the template: `copier copy --trust gh:LabAutomationAndScreening/copier-base-template.git .`
1. Run `python .devcontainer/manual-setup-deps.py --only-create-lock --allow-uv-to-install-python --skip-updating-devcontainer-hash` to generate the lock file(s)
1. Stage all files to prepare for commit (`git add .`)
1. Run `python3 .github/workflows/hash_git_files.py . --for-devcontainer-config-update` to update the hash for your devcontainer file
1. Commit the changes (optional). Ensure to stage the modified `.devcontainer/devcontainer.json` file: `git add .devcontainer/devcontainer.json`
1. Rebuild your new devcontainer

If you are running into issues with the SSH port, confirm the randomly chosen port is not in the excluded ranges on your computer. On Windows you can run this in an elevated command prompt to check `netsh interface ipv4 show excludedportrange protocol=tcp`
