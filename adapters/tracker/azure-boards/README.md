# Azure Boards

## Fetch a ticket

`az boards work-item show --id <id> --expand relations` returns the full item: title in
`System.Title`, description in `System.Description`, and acceptance criteria usually in
`Microsoft.VSTS.Common.AcceptanceCriteria`. For a bug, read
`Microsoft.VSTS.TCM.ReproSteps` instead of Description; that is where repro content
lives. The `--expand relations` array carries the parent
(`System.LinkTypes.Hierarchy-Reverse`) and children (`System.LinkTypes.Hierarchy-Forward`)
as URLs; extract the numeric id from each and fetch it the same way when the criteria
refer to it.

Configure the CLI once per session:
`az devops configure --defaults organization=https://dev.azure.com/example-org project="Example Project"`,
or set the profile's `tracker_project` and pass `--project` on each call instead.

## Start work

Assign to the current user and move the item into the team's active state:

```bash
az boards work-item update --id <id> --assigned-to you@example.com
az boards work-item update --id <id> --state Active
```

Both calls are safe to repeat; an already-assigned or already-active item returns
success unchanged.

## Context for the plan

For the plan's Context section, run the skill's
`scripts/fetch_context.py --org example-org --project "Example Project" --id <id>`, or
omit `--org`/`--project` and let it read the profile's `tracker_project` instead. It
writes `context/context.md` with the parent feature, sibling stories and any linked
design attachments, and downloads image attachments alongside it.

## Fetch a feature

A feature is a Feature or Epic work item. Its children are the
`System.LinkTypes.Hierarchy-Forward` relations that `--expand relations` returns, as in
"Fetch a ticket"; fetch each id the same way.

## Create a child item

Create the story with the process's story type (`User Story` in Agile, `Product Backlog
Item` in Scrum, `Issue` in Basic), then link it under the feature:

```bash
az boards work-item create --type "User Story" --title "<story>"   --description "<html>" --fields "Microsoft.VSTS.Common.AcceptanceCriteria=<html>"
az boards work-item relation add --id <child id> --relation-type parent --target-id <feature id>
```

The create call returns the new item as JSON; its `id` is the story's id. Description
and acceptance criteria are HTML fields: wrap the Gherkin in `<pre>` and keep it plain
ASCII.

## Post the QA report

Post the QA report section as a work item comment, never as a state change:

```bash
az rest --method post \
  --resource "499b84ac-1321-427f-aa17-267ca6975798" \
  --uri "https://dev.azure.com/example-org/Example%20Project/_apis/wit/workItems/<id>/comments?format=markdown&api-version=7.1-preview.4" \
  --body '{"text": "<markdown>"}'
```

`format=markdown` belongs in the query string, not the body; updating the item's
discussion field directly stores plain text as escaped HTML instead. Keep the text
plain ASCII, use `--` for dashes, and use no emoji, since Azure DevOps garbles
non-ASCII characters. Do not reference a PR number anywhere in the comment: a bare
`#1234` auto-links to a work item, never a pull request, so it renders as a wrong link.
Do not include an artifact link either; artifacts are private. Never change the item's
state from this comment; only a QA tester moves it.
