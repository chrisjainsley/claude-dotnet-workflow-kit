# Running a feature in a Claude project

A [Claude project](https://code.claude.com/docs/en/claude-projects) is one coordinating
conversation that starts a thread for each task and tracks them in its Overview pane.
The kit fits it this way:

1. One thread runs `/dotnet-workflow-kit:feature <id>`. It publishes the feature page
   and waits; the thread shows under **Waiting on you**.
2. You approve the feature page. The thread creates the story items and reports one
   `/next` brief per story back to the project conversation.
3. The coordinator starts a thread per brief, wave by wave. Each runs the whole
   pipeline with no plan gate and stops at its review checkpoint, under
   **Waiting on you**.
4. You approve each review in its thread. The thread marks its pull request ready; it
   shows under **Ready for review**, and you merge.

A story that depends on another starts once its parent's review is approved, branching
from the parent's branch, so the pull requests stack. `feature.stacking` in the profile
picks how: `base` sets the parent's branch as the PR base, `gh-stack` also links a linear
chain with [GitHub's stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/stacked-pull-requests),
and `off` waits for the parent to merge instead.

## Before you start

Projects are in public beta on Pro and Max plans, in claude.ai/code, the desktop app
and the mobile app. They are not available on Team or Enterprise plans yet, nor in the
terminal CLI. Each project belongs to one person.

Not yet verified with the kit; check each on a small feature first:

- **The plugin in cloud threads.** Cloud threads load plugins from **Project settings >
  Plugins**, never from a repository's `.claude/settings.json`. Add
  `dotnet-workflow-kit` there. If the marketplace plugin cannot be added, the skills do
  not reach cloud threads.
- **The Artifact tool in cloud threads.** Without it, the feature, plan and review
  pages are built as files and decisions are taken in the thread's chat, as with
  `artifacts: false`.
- **Tracker access.** A cloud thread uses your claude.ai connectors and its cloud
  environment, not your machine's `gh`, `az` or Jira credentials. Give the environment
  what the tracker adapter calls, through network secrets or the setup script.

- **`gh stack link` on a growing chain.** With `gh-stack`, each stacked story links the
  chain from the bottom when its PR opens, so the third story relinks the first two.
  Check on a three-story chain that this extends the stack rather than failing; when it
  fails, the run keeps the bases set by hand and says so.
- **GitHub sub-issues.** Creating a story under a parent issue uses the sub-issues API.
  When it fails, the story gets a `Parent:` line instead.

The kit's hooks, progress bar and `stage` tool run on your machine. In a cloud thread
`/next` writes its state file by hand and rebuilds it from the branch, the PR and the
item when a sandbox restarts from a fresh clone. See "In a Claude project thread" in
the next skill.

## Set up the project

1. Create the project on the repository. Commit `.claude/dotnet-workflow-kit.json` so
   every thread reads the same profile.
2. Add the plugin in **Project settings > Plugins**.
3. In **Project settings > Environment**, pick a cloud environment whose setup script
   installs the .NET SDK, Python 3.11 or later and the tracker's command-line tool.
4. Paste the instructions below into **Project settings > Memory > Project
   instructions**, adjusted to your team.

```text
This project delivers features with the dotnet-workflow-kit plugin.

- A new feature or PRD goes to one thread that runs /dotnet-workflow-kit:feature with
  the feature's id, file or description. Do not split features yourself.
- When that thread reports its briefs, start one thread per brief whose Start line says
  "now", with the brief as the thread's whole first message. Start each later brief
  when its Start line holds: "approved" once the parent story's thread has posted
  "complete /next: the pull request is ready for <item>.", "merged" once I have merged
  the parent's pull request.
- Never start a story whose parent is not ready, and never merge anything.
- Run at most three story threads at a time.
- Each thread opens its own pull request through the kit. Do not open one for it.
- Approvals happen in each thread, on its page or in its chat. Do not approve on my
  behalf from this conversation.
- If a thread stops on a blocker, tell me which thread and the blocker in one line.
```

## Running locally

When the profile's `qa.environment` is `local`, the Test stage starts the system the
way `stack.local_run` says. An Aspire AppHost needs Docker, which a cloud sandbox may
not have. A story whose Test cannot start the system stops on a blocker. Ask the
coordinator to run that story's thread on your computer instead (**Work locally** in the
**+** menu), where it uses your machine's tools, hooks and plugin, or point
`qa.environment` at a deployed environment.

## Cost

Every thread is a full session, and a new project runs threads on Opus at high effort.
A twelve-story feature is thirteen threads plus the coordinator, and a thread watching
its pull request wakes again on each CI failure or review comment. Set **Thread model**
and **Thread effort** in **Project settings > General** to suit, and keep the
concurrency line in the instructions. There is a limit of 200 new threads a day across
your projects.
