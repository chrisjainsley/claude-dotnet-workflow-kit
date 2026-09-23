# None

## Who signs off

Nobody. There is no QA step in this pipeline for the project; the change ships on the
strength of code review and automated tests alone.

## What the QA report must contain

The QA section still gets written, since it costs nothing and documents intent, but it
is scoped to what the author verified locally: environment, one scenario per behaviour
checked, tagged `Acceptance test` or `Manual test` with Pass, Fail or Blocked and an
Evidence line, plus a Not covered section for anything left unchecked. Unit and
integration suites are still never counted as QA evidence, even here.

Where a result was judged from an API response, a screen or a database row, that proof
sits under the Evidence line with a caption repeating the step it proves: the request
and response, the screenshot, or the query and its rows, credentials redacted.

## Hand-off

Nothing is posted anywhere and no label is added. The section lives only in the review
artifact, for whoever reads it next.

## When no QA was run

Open the section with **No QA run.** and list every acceptance criterion under Not
covered, the same as any other QA owner.
