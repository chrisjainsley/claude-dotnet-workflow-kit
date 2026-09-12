# Jira

## Fetch a ticket

Jira exposes issues over its REST v3 API. Set `JIRA_BASE_URL`, `JIRA_EMAIL` and
`JIRA_API_TOKEN` (an API token, not a password) as environment variables, then:

```bash
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
  "$JIRA_BASE_URL/rest/api/3/issue/<KEY>?fields=summary,description,issuelinks,parent,subtasks" \
  -H "Accept: application/json"
```

`summary` and `description` (Atlassian Document Format) hold the title and body; for a
bug, the repro steps are usually inside `description` under a "Steps to reproduce"
heading, since Jira has no separate field for it by default. `parent` gives the parent
issue key; `subtasks` and `issuelinks` give children and related issues. Fetch each key
the same way.

## Start work

Assign to the current user and transition to the team's active status:

```bash
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -X PUT \
  "$JIRA_BASE_URL/rest/api/3/issue/<KEY>/assignee" \
  -H "Content-Type: application/json" -d '{"accountId": "<your-account-id>"}'

curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" "$JIRA_BASE_URL/rest/api/3/issue/<KEY>/transitions"
```

The second call lists the available transition ids; POST the one named for the
team's active state to the same endpoint with `{"transition": {"id": "<id>"}}`.

## Context for the plan

Fetch the parent with `.../issue/<parent-key>`, siblings with a JQL search
(`.../search?jql=parent=<parent-key>`), and attachments from the `fields.attachment`
array on the issue response, each with its own download URL.

## Post the QA report

Post the QA report as a comment, in Atlassian Document Format, never as a transition:

```bash
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -X POST \
  "$JIRA_BASE_URL/rest/api/3/issue/<KEY>/comment" \
  -H "Content-Type: application/json" \
  -d '{"body": {"type": "doc", "version": 1, "content": [...]}}'
```

Keep the text plain ASCII, use `--` for dashes, and use no emoji. Do not reference a
PR number as a bare number anywhere; Jira's smart links can expand a plain reference
against the wrong project. Do not include an artifact link either. Never call the
transitions endpoint from this step; only a QA tester moves the issue.
