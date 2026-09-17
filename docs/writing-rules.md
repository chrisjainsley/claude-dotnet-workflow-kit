# Writing rules

Shared by `plan` and `review`. Both build a budgeted Artifact document,
and both enforce these rules with a cut pass before publishing.

## Budget philosophy

The document exists so the reviewer can approve or redirect in a five-minute read.
Everything serves that: a fixed section order that follows the dependency direction of
the code, a word budget enforced by a script, and a cut pass before publishing.
Unbudgeted documents run 5,000 to 9,000 prose words, state each decision three times and
list every file in a tree. Nobody reads that before approving. A standard document gets
about 1,100 to 1,400 prose words, code excluded. If it cannot fit, the scope is too big
or the document carries material the reader would never act on.

## Writing rules

- **Code beats prose about code.** A signature, a contract diff or a Gherkin scenario
  says more in fewer words than a paragraph describing it. Fenced code does not count
  against the budget for exactly this reason.
- **Each fact lives in one place.** A decision appears once. Rejected alternatives get
  one clause, never their own comparison. No closing recap.
- **No containers.** Paragraphs, bullets, tables and code are the whole vocabulary.
- **Anchor to verified names.** Real file paths and symbols, one per sentence at most,
  and only ones confirmed by search. Describe the rest in words.
- **The page stands alone.** No meeting dates, no "agreed with the FE team", no "unlike
  the earlier draft". A reader with no chat history must understand the page.
- **Do not restate the ticket.** The acceptance criteria are already on the work item;
  a testable translation is the useful addition.
- **Plain sentences.** Under 25 words, active voice, no em dashes, no bold-lead
  paragraphs, no "robust", "seamless", "leverage".
- **Do not invent work to fill a layer.** "No change." is a complete section.

## Review-specific rules

- **Numbers agree.** A tile that says 11/11 while a table shows ten rows is worse than
  no tile. When a tile counts underlying checks that group into fewer scenarios, say so
  in the tile note.
- **Report what happened, not what should have.** A scenario that was not run is Not
  covered, never Pass. A finding that was not fixed is open or accepted, never omitted.
  If tests failed, the Verdict says not ready and why.
- **Diffs carry a decision.** A hunk earns its place when the reviewer would decide
  differently after reading it. Renames, moved usings and generated snapshots are
  described in the file table, not shown.

## Cut pass briefs

Plan:

> Read this implementation plan as the engineer who will build it tomorrow. Delete
> every sentence whose removal would not change what you build, test, or ask about.
> Targets: rationale for a decision nobody would question, restated ticket text, a
> second statement of a fact already made, narration of what code visibly does,
> adjectives, and any sentence that explains the plan rather than the change. Return
> the plan with the deletions applied and a five-line list of what you cut and why.
> Do not add content, reorder sections, or soften anything.

Review:

> Read this review as the person who has to decide whether the PR goes to QA today.
> Delete every sentence whose removal would not change that decision or the QA team's
> ability to re-test. Targets: narration of what a diff visibly does, restated plan
> text, praise, a second statement of a fact, and any hunk that shows a rename or a
> mechanical edit. Return the review with the deletions applied and a five-line list
> of what you cut. Do not add content, reorder sections or soften a Fail.
