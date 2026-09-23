# Self

## Who signs off

The author runs the scenarios themselves and signs off; there is no separate QA team
step. The review page's QA section is the record of what was verified before the
change goes further.

## What the QA report must contain

Environment and the test users exercised, so the steps can be repeated later. One
scenario per behaviour, tagged `Acceptance test` or `Manual test`, each with Pass, Fail
or Blocked and an Evidence line. Anything but Pass carries a Classification:
regression, pre-existing bug, or environment issue. A summary table and a Not covered
section still apply; verifying it yourself is not a reason to skip naming what was not
checked. Unit and integration suites never count as QA evidence here either.

Where a result was judged from an API response, a screen or a database row, that proof
sits under the Evidence line with a caption repeating the step it proves: the request
and response, the screenshot, or the query and its rows, credentials redacted.

## Hand-off

There is no separate QA team to label or deploy for. The review artifact's QA section
is the hand-off: whoever reads it next, a reviewer or a teammate, sees exactly what the
author ran and where it passed or fell short.

## When no QA was run

Open the section with **No QA run.** and list every acceptance criterion under Not
covered. Do not write a scenario that was not actually exercised just because the
author could have run it.
