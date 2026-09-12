# Running without the Artifact tool

Setting `"artifacts": false` in the profile tells both document skills that the Claude
Artifact tool is not available on the surface you are using. Nothing else about the
workflow changes: the same plan and review pages are built, just delivered as local
files instead of a published, interactive page.

## What still happens

`visual-plan` and `visual-review` build the exact same `plan.html` and
`review.html` either way. The section content, the word budgets, the mermaid diagram
in the review, the per-file diff links, all of that comes from the same markdown and
the same build scripts regardless of `artifacts`. The only thing that changes is the
last step: instead of calling the Artifact tool, the skill tells you the path to the
file it just wrote, for example `plans/AB-1234-add-refund-flow/plan.html`, and you
open it yourself.

## Open it in a browser

Open the `.html` file directly from disk. Every section renders: Context, Requirement,
Specs and the rest of the plan; Verdict, Changes, Findings and the rest of the review.
The page looks the same as the published version because it is the same template.

## What cannot send

Three interactive pieces on these pages depend on the Artifact tool's shared database
to store what you do on them, so without it they render but cannot save anything:

- The plan's **open-questions form**. You can see each question, its context and its
  options, and you can click around, but nothing you select is written anywhere the
  skill can read back.
- The review's **rollout checklist**. The ticks render, but toggling one does not
  persist; reloading the page resets it.
- The review's **decision form**. You can see the approve and request-changes options
  and the per-finding fix or accept radios, but submitting them has nowhere to go.

## Answer in chat instead

Because the form cannot send, give your answers back to the session directly:

- **Open questions**: reply with the question number and your choice, for example
  "1: back to the lots it came from" or "2: none, take the recommended options for the
  rest." The skill folds each answer into `plan.md` as a settled decision the same way
  it would have from the stored form, then rebuilds and reopens the file.
- **The decision**: reply with `approve` or `changes`. For `changes`, say what to do
  with each open finding: `fix` if it should be fixed on the branch before this goes
  back to QA, or `accept` with a one-line reason if it is a known and acceptable gap.
  The skill applies exactly what the form would have recorded, then rebuilds and
  reopens `review.html`.

There is no rollout equivalent in chat; without the Artifact tool the rollout
checklist is a read-only reference for whoever runs the deploy, and ticking it off is
tracked outside the kit.

## Switching it back on

Set `"artifacts": true` in `.claude/dotnet-workflow-kit.json`, or answer "yes" to the
Artifact-tool question the next time you run `/dotnet-workflow-kit:setup` or
`python scripts/setup.py`. The next plan or review the skills publish will use the
Artifact tool, with the open-questions form, rollout ticks and decision form all able
to save again.
