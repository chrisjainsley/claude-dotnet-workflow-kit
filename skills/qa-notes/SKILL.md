---
name: qa-notes
description: Write QA testing notes for the QA team before hand-off, covering what changed, how to test it step by step per persona, test data and accounts needed, edge cases, what is out of scope, and any environment or feature-flag setup required. Use whenever the user says "qa notes", "test notes", "write test notes", or "notes for QA" once a change is ready to hand off.
---

# QA notes

These notes tell someone who did not write the code how to test it: what changed, what
to click or call in what order, which accounts and data to use, and where the edges of
the change are. They are written before testing happens, unlike the report skill, which
records what testing already found.

`SKILL_DIR` below means the base directory shown at the top of this skill. The plugin
root is two levels above it; adapters live at `<plugin root>/adapters/`.

## Profile

Resolve the profile first: `python "SKILL_DIR/../../scripts/profile.py"`. It decides:

- `qa.owner`: who these notes are for. `qa-team` posts them for someone else to act on;
  `self` and `none` mean the author is the one testing, so the notes are printed rather
  than handed off.
- `qa.evidence`: whether posting goes through the tracker adapter (`work-item`) or the
  scm adapter (`pr-comment`); with `none`, there is nowhere to post.
- `tracker` / `scm`: which adapter's posting steps to follow.
  Read `adapters/tracker/<tracker>.md` or `adapters/scm/<scm>.md`.

## Workflow

1. **Find the source material.** If an approved plan exists at
   `plans/<id>-<slug>/plan.md` (the kit's plan skill), derive the notes from its Specs
   section: the scenarios there are exactly the behaviours to test. With no plan, derive
   the notes from the diff instead, using `git diff <base>...HEAD`, and read the changed
   files well enough to describe user-facing behaviour, not implementation.
2. **Write the notes** covering:
   - **What changed**: a short bullet list in product terms, one line per user-facing
     behaviour. No class names, no file paths, no architecture.
   - **How to test it**: numbered steps per persona (for example "as an admin user",
     "as a freemium member"), each step an action and an expected result.
   - **Test data and accounts**: the concrete accounts, plans, or records needed to
     reach each scenario, named specifically enough to reuse them without guessing.
   - **Edge cases**: the boundary conditions the change introduces or touches (empty
     states, limits, concurrent actions, already-in-progress flows).
   - **Out of scope**: what looks related but was not changed, so QA does not spend
     time re-verifying it or filing it as a gap.
   - **Environment and feature flags**: which environment to test against and any flag
     that must be on (or off) for the change to be reachable.
3. **Ask before posting.** Show the notes in full and ask whether to add them. Do not
   post before a clear yes.
4. **Post per `qa.owner` and `qa.evidence`.** With `qa.owner: qa-team`: `qa.evidence:
   work-item` follows the tracker adapter's posting steps (the same markdown-comment
   mechanism the QA report uses, never a state change); `qa.evidence: pr-comment` posts
   through the scm adapter as a plain PR comment instead. With `qa.owner: self` or
   `qa.owner: none`, there is no one to hand off to: print the notes and say plainly
   that they were not posted anywhere, since the author is the one testing.
5. **Never change the work item's or PR's state.** Moving a board column or requesting
   review is a QA or reviewer decision, not this skill's.
6. **Confirm completion** with a link to wherever the notes landed, or, if nothing was
   posted, a one-line note of where the notes are (printed above, or saved to a file the
   user named).

## Traps

- Write for QA, not for developers: no class names, no mention of aggregates or grains,
  no architecture. If a sentence needs an implementation detail to make sense, rephrase
  it around the user-facing behaviour instead.
- Plain ASCII, `--` for dashes, no emoji, when posting to a tracker that garbles
  non-ASCII text.
- No bare PR numbers in the posted text; a tracker's auto-linking can resolve a number
  to the wrong item.
- A plan's Specs section is the source of truth when one exists; do not re-derive
  scenarios from the diff in that case, since the two can drift apart.
- Do not invent edge cases the change does not actually touch; "Out of scope" exists so
  QA does not have to guess which ones matter.

## Files

None. This skill has no scripts or templates of its own.
