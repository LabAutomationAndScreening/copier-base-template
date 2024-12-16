# Instantiating a new repository using this template
1. Use the file `.devcontainer/devcontainer-to-instantiate-template.json` to create a devcontainer
2. Inside that devcontainer, run the `.devcontainer/install-ci-tooling.sh` script
3. Run copier to instantiate the template: `copier copy --vcs-ref main --trust gh:LabAutomationAndScreening/copier-base-template.git .`
4. Run `uv lock` to generate the lock file
5. Commit the changes
6. Rebuild your new devcontainer
