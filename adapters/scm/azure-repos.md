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
