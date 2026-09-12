# GitHub

## Find the PR and base

```bash
gh pr view --json number,url,baseRefName,headRefName,state,isDraft,reviewDecision,mergeable
gh pr checks
```

`baseRefName` is the branch to diff against; fall back to the profile's `base_branch`
when no PR exists yet. `headRefName` is the current branch's remote name, and
`gh pr checks` lists each CI check with its status.

## Draft PR and labels

Create the PR as a draft so reviewers and any consolidator leave it alone until it is
ready:

```bash
gh pr create --base <base_branch> --draft --title "<title>" --body-file body.md
```

Add the profile's `qa.handoff_label` and `qa.deploy_label` when either is set, since
they are what moves the change to QA and to a deployed environment:

```bash
gh pr edit <number> --add-label "<qa.handoff_label>"
gh pr edit <number> --add-label "<qa.deploy_label>"
```

Mark it ready only once QA has signed off: `gh pr ready <number>`.

## Review threads

```bash
gh api graphql -f query='query{repository(owner:"example-org",name:"example-repo"){pullRequest(number:<n>){reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{body}}}}}}}'
```

Reply on a thread with the `addPullRequestReviewThreadReply` mutation through
`gh api graphql`, or from the PR page directly. Resolve a thread with the
`resolveReviewThread` mutation once the point is addressed; do not resolve a thread you
have not actually responded to.

## Diff range for the review builder

For an open PR, diff the base against the branch tip: `origin/<base>...HEAD`. For a PR
that has already merged, diff the squash commit against its parent: `<sha>^..<sha>`,
where `<sha>` is the merge commit's sha from `gh pr view --json mergeCommit`.
