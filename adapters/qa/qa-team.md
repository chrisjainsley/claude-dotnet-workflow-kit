# QA team

## Who signs off

A dedicated QA team runs the scenarios and signs off. They decide when the work item
moves off the board's QA column; nothing in this pipeline changes the work item's
state on their behalf.

## What the QA report must contain

Environment and the test users exercised, so QA can repeat the exact steps. One
scenario per behaviour, tagged `Acceptance test` (a real automated run against a live
environment) or `Manual test` (a person's own steps), each with Pass, Fail or Blocked.
Every scenario carries an Evidence line (the observed value, a test-run count, a
transaction id). Anything but Pass carries a Classification: regression, pre-existing
bug, or environment issue. A summary table lists every scenario with its type,
environment and result. A Not covered section names what was not tested and why. Unit
and integration suites never appear here; they are not QA evidence.

Where a result was judged from an API response, a screen or a database row, that proof
sits under the Evidence line with a caption repeating the step it proves: the request
and response, the screenshot, or the query and its rows, credentials redacted.

## Hand-off

Add the profile's `qa.handoff_label` to the PR so the QA team picks it up, and the
`qa.deploy_label` if the change needs a deployed environment at `qa.environment` rather
than local. Once QA team members finish, moving the work item's board column is their
call, not this pipeline's.

## When no QA was run

Open the QA report section with **No QA run.** and list every acceptance criterion
under Not covered instead of inventing a scenario. Post that section exactly as
written; a QA team reading "No QA run" knows to run the scenarios themselves.
