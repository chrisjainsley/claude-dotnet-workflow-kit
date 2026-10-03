# Azure Repos

## Find the PR and base

```bash
az repos pr list --repository example-repo --source-branch <branch> --status active \
  --query "[0].{id:pullRequestId,url:url,base:targetRefName,head:sourceRefName,status:status}"
az repos pr show --id <id>
```

`targetRefName`, stripped of `refs/heads/`, is the base to diff against; fall back to
the profile's `base_branch` when no PR exists yet. Build status and required checks
come from `az repos pr policy list --id <id>`.

## Draft PR and labels

Create the PR as a draft so reviewers leave it alone until it is ready:

```bash
az repos pr create --repository example-repo --source-branch <branch> \
  --target-branch <base_branch> --draft true --title "<title>" --description "<body>"
```

Right after creating it, unless the profile sets `pipeline.open_pr_in_browser` to `false`, and when running in Claude desktop (the built-in browser tools
`mcp__Claude_Browser__*` are available), open the PR's web page in that browser with
`mcp__Claude_Browser__navigate` instead of leaving the link in chat. Skip it elsewhere.

Then, unless the profile sets `pipeline.auto_fix_pr` to `false`, and when running in Claude desktop (the `mcp__ccd_pr__*` tools are available), turn on CI auto-fix for the new PR. Call `mcp__ccd_pr__get_status` and, if it does not report the PR, `mcp__ccd_pr__bind_pr`. Then call `mcp__ccd_pr__set_monitor` with `auto_fix: true`, `address_comments: true` and the PR's url, so the session wakes on CI failures, merge conflicts and review comments. Load the tools through ToolSearch first if they are deferred. If the call is declined or the tools are missing, say so in one line and carry on.

The body describes this ticket's change only. Never name another pull request in it, not a
parent, sibling or follow-up, and not the shape of a stack. Hand-written topology goes stale
as soon as a layer merges and the rest retarget, and where the host renders the chain itself
the prose is duplicate. The same holds for anything written to the tracker.

Commit messages carry no work item id and no `#123` reference, so the tracker shows the
pull request alone and no commits. Merge with an explicit message (`git merge -m "Merge
<base>"`), since the default embeds the branch name and its id.

Azure Repos labels are called tags; add the profile's `qa.handoff_label` and
`qa.deploy_label` when either is set:

```bash
az repos pr update --id <id> --labels "<qa.handoff_label>"
az repos pr update --id <id> --labels "<qa.deploy_label>"
```

Mark it ready once QA has signed off: `az repos pr update --id <id> --draft false`.

## Review threads

```bash
az repos pr thread list --id <id>
```

Reply inside a thread with
`az repos pr thread comment create --id <id> --thread-id <thread-id> --content "<text>"`.
Resolve it with `az repos pr thread update --id <id> --thread-id <thread-id> --status closed`
once the point is addressed; do not close a thread you have not actually responded to.

## Diff range for the review builder

For an open PR, diff the base against the branch tip: `origin/<base>...HEAD`. For a PR
that has already completed, diff the merge commit against its parent: `<sha>^..<sha>`,
where `<sha>` is the completed pull request's merge commit sha from
`az repos pr show --id <id> --query lastMergeCommit.commitId`.
