# design-doc-publish

## Deploy

A change under scripts/, skills/, references/ or SKILL.md reaches a
session only through the installed plugin, so its PR moves the version
in .claude-plugin/plugin.json and marketplace.json. After the merge:

1. claude plugin marketplace update design-doc-publish
2. claude plugin update design-doc-publish@design-doc-publish
3. installed_plugins.json shows the new version at the merge commit.
4. The installed publish_doc.py --dry-run on a scratch page exits 0.
5. Running sessions need a restart or /reload-plugins.

The harness container (harness/, index/, Dockerfile, compose*.yaml)
deploys separately. Its steps are not written here yet.
