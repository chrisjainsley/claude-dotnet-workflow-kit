# GitHub Issues

## Fetch a ticket

`gh issue view <number> --repo example-org/example-repo --json title,body,state,labels`
returns the title and body. Acceptance criteria and repro steps live in the body as
markdown; there is no dedicated field, so look for a checklist or a "Steps to
reproduce" heading inside `body`. Parent and linked items are tracked as references
inside the body (`Parent: #100`) or via GitHub's own tracked-by relationships, which the
CLI does not expose as structured fields, so read the body for the referenced numbers
and fetch each one the same way.

## Start work

Assign to the current user and add a label for the active state, since GitHub Issues
has no built-in workflow state:

```bash
gh issue edit <number> --repo example-org/example-repo --add-assignee "@me"
gh issue edit <number> --repo example-org/example-repo --add-label "in-progress"
```

Adjust the label name to whatever the project's board uses for "started".

## Context for the plan

Pull the parent issue and anything it tracks the same way:
`gh issue view <parent> --repo example-org/example-repo --json title,body,state`. List
sibling issues with `gh issue list --repo example-org/example-repo --label <shared-label>`.
Attachments are inline image links in the body; fetch one with a plain HTTP request
when the plan needs the screenshot.

## Fetch a feature

A feature is a parent issue. Its children are sub-issues:

```bash
gh api repos/example-org/example-repo/issues/<number>/sub_issues --jq '.[] | {number, title, state}'
```

On a host without sub-issues, the children are the issues the body lists as a task list
(`- [ ] #123`); fetch each one the same way.

## Create a child item

Create the story, then attach it to the feature as a sub-issue. The sub-issues API takes
the child's internal `id`, not its `number`:

```bash
gh issue create --repo example-org/example-repo --title "<story>" --body-file story.md
gh api -X POST repos/example-org/example-repo/issues/<parent number>/sub_issues   -F sub_issue_id="$(gh api repos/example-org/example-repo/issues/<child number> --jq .id)"
```

`gh issue create` prints the new issue's URL; its last segment is the number. When the
sub-issues call fails, add `Parent: #<parent number>` as the body's first line instead,
which "Fetch a ticket" already reads.

## Post the QA report

Post the QA report section as an issue comment, never by closing or reopening the
issue:

```bash
gh issue comment <number> --repo example-org/example-repo --body-file report.md
```

Keep the text plain ASCII, use `--` for dashes, and use no emoji. Do not reference a PR
number as a bare `#1234`: GitHub auto-links any `#number` to whatever issue or PR holds
that number in the repo, so a PR number can resolve to the wrong item. Do not include
an artifact link either. Never change the issue's state or milestone from this
comment; that is the QA owner's call.
