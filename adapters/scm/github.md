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

Right after creating it, unless the profile sets `pipeline.open_pr_in_browser` to `false`, and when running in Claude desktop (the built-in browser tools
`mcp__Claude_Browser__*` are available), open the PR's `url` in that browser with
`mcp__Claude_Browser__navigate` instead of leaving the link in chat. Skip it elsewhere.

Then, unless the profile sets `pipeline.auto_fix_pr` to `false`, and when running in Claude desktop (the `mcp__ccd_pr__*` tools are available), turn on CI auto-fix for the new PR. Call `mcp__ccd_pr__get_status` and, if it does not report the PR, `mcp__ccd_pr__bind_pr`. Then call `mcp__ccd_pr__set_monitor` with `auto_fix: true`, `address_comments: true` and the PR's url, so the session wakes on CI failures, merge conflicts and review comments. Load the tools through ToolSearch first if they are deferred. If the call is declined or the tools are missing, say so in one line and carry on.

The body describes this ticket's change only. Never name another pull request in it, not a
parent, sibling or follow-up, and not the shape of a stack. The host already renders a
stack's chain, and hand-written topology goes stale as layers merge and retarget. The same
holds for anything written to the tracker.

Commit messages carry no work item id and no `#123` reference, so the tracker shows the
pull request alone and no commits. Merge with an explicit message (`git merge -m "Merge
<base>"`), since the default embeds the branch name and its id, and drop the id from a
squash merge's default title, which is the pull request title.

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
