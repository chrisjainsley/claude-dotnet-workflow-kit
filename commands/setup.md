---
description: Tailor the .NET workflow kit to this team. Asks about architecture, testing, QA, tracker, source control and stack, recommends dotnet-claude-kit when an answer needs one of its skills, and writes .claude/dotnet-workflow-kit.json. Run once per project, again whenever the workflow changes.
argument-hint: [--scope user] [--profile <answers.json>]
---

Set up the kit's profile for the current project. The profile is the one file every kit
skill reads; see the README's profile reference for each field.

1. **Detect first.** Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --detect` and
   read the JSON: remote host, whether `az` and `gh` exist, installed plugins, whether
   dotnet-claude-kit, codex and a Roslyn MCP server are present, and which frontend the
   files suggest (`.razor`, a `package.json` framework, `.cshtml`, plain scripts). Use
   these as defaults.
   If `$ARGUMENTS` names a `--profile` file, skip the questions and go to step 4 with it.

2. **Ask in groups with the question tool**, at most four questions per call, four
   options each. Put the detected or default value first and mark it recommended.
   - Group 1, how you build: architecture (clean, vertical, ddd-clean, modular-monolith);
     TDD (strict, encouraged, none); unit framework (xunit, nunit, mstest); acceptance
     tests (reqnroll, specflow, none).
   - Group 2, how you test and run: integration style (webapplicationfactory,
     testcontainers, none); data access (ef-core, dapper, cosmos, other); API style
     (minimal-api, controllers, graphql, grpc); frontend (none, blazor, razor, react,
     angular, vue, javascript), with the detected value first. Anything but none lets
     a plan carry a Designs section and draw screens when a ticket has none.
   - Group 3, how work flows: tracker (azure-boards, github-issues, jira, none); source
     control (github, azure-repos); who does QA (qa-team, self, none); where QA evidence
     goes (work-item, pr-comment, none). Evidence `work-item` needs a tracker; if the
     answers conflict, ask again.
   - Group 4, details as free text via Other: first name for the prose, tracker project,
     base branch, branch pattern (must contain `{slug}`), branch kind prefixes for
     features and bugs, tracker state names for active and QA hand-off (blank keeps the
     adapter default), QA hand-off label, deploy
     label, QA environment name, local run (aspire, docker, plain), messaging
     (masstransit, wolverine, service-bus, none),
     error handling (result, exceptions), and the optional pipeline commands `/next` runs
     for Execute, Resolve comments and QA (blank means the built-in fallback).
   - Group 5, reviewers: a multi-select of extra reviewer-sweep reviewers (kit,
     security-scan, convention-learner, code-review-workflow). Say that
     code-review-workflow needs a Roslyn MCP server and whether one was detected. The two
     built-ins, bug-hunt and conventions, are always on.
   - Ask whether the Claude Artifact tool is available on the surface they use. When it
     is not, the plan and review pages open as local HTML and answers come through chat.

3. **Write the answers** to a temp JSON file shaped like the profile (nested `testing`,
   `qa`, `stack`; `reviewers` as a list; `artifacts` as a boolean). Partial is fine.

4. **Run setup** from the project root:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --profile <answers.json> --no-install
   ```
   Read its output. When it says dotnet-claude-kit provides skills the answers rely on
   and the plugin is missing, recommend it and ask the user whether to install. On yes,
   rerun with `--yes` and without `--no-install`; it adds the marketplace and installs
   the plugin, which loads on the next Claude Code start. On no, the profile records
   the gap and the reviewer sweep reports those reviewers as skipped.

5. **Confirm** by printing the written path and a short table of the profile. Suggest
   committing the project file so the team shares one workflow. If no `CLAUDE.md`
   exists in the project and dotnet-claude-kit is installed, suggest `/dotnet-init`
   before the first plan.

Never write the profile by hand; the script validates the enums and the invariants.
