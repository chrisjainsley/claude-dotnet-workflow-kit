// The kit's progress bar: the current branch's work item above the prompt, drawn from the pipeline
// state files `start`, `plan` and `next` write under ~/.claude/dotnet-workflow-kit/pipeline, and a
// Sessions pane listing every item in this repository. A branch no skill has touched yet gets a
// file of its own, marked `adopted`, so every session shows whether or not it used the kit. It also sets the run's /goal when the plan
// and then the review are approved. With Aspire it tracks which session owns each running AppHost
// through scripts/aspire_sessions.py, shows them, tells Claude, and refuses commands that would
// stop or clash with another session's.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Activity, AspireEntry, PipelineRow, StageStatus } from '../types'

const rows = atom({ plugin: 'dotnet-workflow-kit', key: 'rows' } as const, [])
const isHidden = atom({ plugin: 'dotnet-workflow-kit', key: 'isHidden' } as const, false)
const dismissed = atom({ plugin: 'dotnet-workflow-kit', key: 'dismissed' } as const, [])
const activity = atom({ plugin: 'dotnet-workflow-kit', key: 'activity' } as const, null)
// What the session still has running in the background when its turn ends, so the bar keeps
// moving while Claude waits on a shell, subagent or workflow to wake it.
const background = atom({ plugin: 'dotnet-workflow-kit', key: 'background' } as const, [])
// Goals already set, per item: survives reloads so a phase's goal is set once.
const goalsSet = atom({ plugin: 'dotnet-workflow-kit', key: 'goalsSet' } as const, {})
// Whether this session toasts when another item reaches a gate; off, since the app notifies too.
const notifyOthers = atom({ plugin: 'dotnet-workflow-kit', key: 'notifyOthers' } as const, false)
// Every Aspire AppHost running on this machine, with the session that owns it.
const aspire = atom({ plugin: 'dotnet-workflow-kit', key: 'aspire' } as const, [])

const PANE = 'sessions'

// The kit's own pipeline; a state file's `order` replaces it when a team adds stages.
const DEFAULT_ORDER = ['start', 'plan', 'implement', 'test', 'review', 'pull_request']
const DEFAULT_LABELS: Record<string, string> = {
  start: 'Start',
  plan: 'Plan',
  implement: 'Implement',
  test: 'Test',
  review: 'Review',
  pull_request: 'PR',
  pullRequest: 'PR',
}
const MAX_ROWS = 12
// Other items show in the Sessions pane only while someone touched them recently.
const RECENT_MS = 24 * 60 * 60 * 1000
const POLL_MS = 4000
// A closed item's row goes a day after it closed; scripts/close_items.py deletes its file then.
const REMOVE_MS = 24 * 60 * 60 * 1000
// Asking GitHub or Azure about each PR is a network call, so it runs far less often than the poll.
const CLOSE_MS = 10 * 60 * 1000
const CLOSED_LABELS: Record<string, string> = {
  merged: 'Merged',
  closed: 'PR closed',
  archived: 'Archived',
  deleted: 'Branch deleted',
  idle: 'Idle',
  manual: 'Done',
}
// An adopted item's file is rewritten at most this often while its session works, so it stays recent.
const TOUCH_MS = 10 * 60 * 1000
const ADOPTED_DETAIL = 'Not run through the kit yet: /next picks it up'
// A session that owns an AppHost rescans this often; any other session only every QUIET_MS.
const ASPIRE_MS = 15 * 1000
const QUIET_MS = 60 * 1000
// Commands worth asking scripts/aspire_sessions.py about: ones that stop processes or start an AppHost.
const ASPIRE_COMMAND =
  /\b(kill|pkill|killall|taskkill|stop-process|spps|fuser)\b|\bdotnet(\.exe)?\s+(run|watch)\b|\baspire(\.exe)?\s+(run|start)\b/i
// A start's AppHost builds before it listens, so the scans after one come at these delays.
const START_SCANS_MS = [5000, 20000, 45000, 90000]

const COLOR = { done: '#c4c0ff', active: '#8e86f8', waiting: '#f59e0b', todo: '#6b7280' }
// The Sessions pane's cards: a purple edge on the item being viewed, an amber one on an item
// waiting on you, with a faint tint of the same where the surface can draw one.
const CARD = {
  border: '#3a3836',
  currentBorder: '#5d52a3',
  currentTint: '#9d8cff14',
  currentText: '#c9bfff',
  waitingBorder: '#8a6a33',
  waitingTint: '#e9ae4f14',
  check: '#6fbf73',
}
// A card's stage segments: done stages muted, the active one bright, those ahead a dark track.
const SEGMENT = { done: '#5d52a3', active: '#9d8cff', waitingDone: '#8a6a33', waiting: '#e9ae4f', todo: '#3a3836' }

type Stage = {
  done?: boolean
  at?: string
  waiting?: boolean
  label?: string
  artifactUrl?: string
  decision?: string
  note?: string
}
type Closed = { reason: string; at: string }
type StateFile = {
  closed?: Closed
  adopted?: boolean
  worktree?: boolean | string
  repo?: string
  ticket?: string
  title?: string
  shortTitle?: string
  branch?: string
  current?: { stage?: string; detail?: string; blocked?: boolean }
  order?: (string | { id: string; label?: string })[]
  stages?: Record<string, Stage | undefined>
}

// One stage's done flag, reading the 0.5.0 keys for the built-in stages when the new ones are absent.
function stageDone(s: Record<string, Stage | undefined>, id: string): boolean {
  const d = (key: string) => s[key]?.done === true
  const has = (key: string) => s[key] !== undefined

  switch (id) {
    case 'start':
      return has('start') ? d('start') : d('startTicket')
    case 'implement':
      return has('implement') ? d('implement') : d('execute') && d('megaReview')
    case 'test':
      return has('test') ? d('test') : d('qa')
    case 'review':
      return d('review') || s.review?.decision === 'approve'
    case 'pull_request':
    case 'pullRequest':
      return has('pullRequest') ? d('pullRequest') : has('pull_request') ? d('pull_request') : d('handoff')
    default:
      return d(id)
  }
}

// A stage's entry in the file, under either spelling of the PR stage.
const stageEntry = (s: Record<string, Stage | undefined>, id: string) =>
  id === 'pull_request' || id === 'pullRequest' ? (s.pullRequest ?? s.pull_request) : s[id]

// The stages in order with their labels: the file's `order` when present, else the kit's six.
function stageList(data: StateFile): { id: string; label: string }[] {
  const order = data.order?.length ? data.order : DEFAULT_ORDER
  const stages = data.stages ?? {}

  return order.map(entry => {
    const id = typeof entry === 'string' ? entry : entry.id
    const given = typeof entry === 'string' ? undefined : entry.label
    const label = given || stages[id]?.label || DEFAULT_LABELS[id] || id.replace(/[-_]/g, ' ')

    return { id, label: label.charAt(0).toUpperCase() + label.slice(1) }
  })
}

// feat/391-jev-agent-router -> "jev agent router"; claude/foo-bar-7d2e6c -> "foo bar".
function titleFromBranch(branch: string): string {
  return branch
    .replace(/^.*\//, '')
    .replace(/^#?\d+[a-z]?-/, '')
    .replace(/-[0-9a-f]{6}$/, '')
    .replace(/-/g, ' ')
}

// "391" -> "#391"; "PROJ-12" stays; placeholders such as "none" or "untracked" show nothing.
function ticketId(ticket: string | undefined): string {
  const id = (ticket ?? '').trim()
  if (!id || /^(none|untracked)$/i.test(id)) return ''

  return /^\d+$/.test(id) ? `#${id}` : id
}

// A row's title in at most four words and 28 characters: the story at a glance, not its full name.
function shortTitle(title: string): string {
  const words = title.trim().split(/\s+/).slice(0, 4).join(' ')

  return words.length > 28 ? `${words.slice(0, 27).trimEnd()}…` : words
}

function toRow(slug: string, data: StateFile, branch: string): PipelineRow {
  const stages = data.stages ?? {}
  const list = stageList(data)
  // A stage a skill has written to means every stage before it is behind the item, even when a
  // skill skipped marking them (a plan written without Start ticked is still at Plan).
  // `/next` seeds stages it has not reached with blank placeholders, so only real progress counts.
  const isReached = (id: string) => {
    const s = stageEntry(stages, id)
    return data.current?.stage === id || !!(s && (s.done || s.waiting || s.at || s.artifactUrl || s.decision))
  }
  const reached = list.reduce((last, stage, i) => (isReached(stage.id) ? i : last), -1)
  // A closed item counts every stage as done, whatever the stage flags say.
  const flags = list.map((stage, i) => !!data.closed || i < reached || stageDone(stages, stage.id))
  const activeIndex = flags.indexOf(false)
  const active = activeIndex === -1 ? undefined : list[activeIndex].id
  const activeStage = active ? stageEntry(stages, active) : undefined
  const isPlanGate = active === 'plan' && !!activeStage?.artifactUrl
  const isCheckpoint = active === 'review' && !!activeStage?.artifactUrl && !activeStage?.decision
  const isCustomGate = activeStage?.waiting === true
  const isGate = isPlanGate || isCheckpoint || isCustomGate

  const statuses: StageStatus[] = flags.map((done, i): StageStatus => {
    if (done) return 'done'
    if (i !== activeIndex) return 'todo'

    return isGate ? 'waiting' : 'active'
  })

  const detail = data.closed
    ? (CLOSED_LABELS[data.closed.reason] ?? 'Done')
    : isPlanGate
    ? 'Waiting on you: answer or approve the plan'
    : isCheckpoint
      ? 'Waiting on you: review checkpoint'
      : isCustomGate
        ? `Waiting on you${activeStage?.note ? `: ${activeStage.note}` : ''}`
        : (data.current?.detail ?? activeStage?.note ?? '')

  return {
    slug,
    ticket: ticketId(data.ticket),
    title: data.shortTitle || shortTitle(data.title || titleFromBranch(data.branch ?? '')),
    branch: data.branch ?? '',
    isCurrentBranch: !!branch && data.branch === branch,
    labels: list.map(stage => stage.label),
    isPlanApproved: stageDone(stages, 'plan'),
    isReviewApproved: stages.review?.decision === 'approve',
    isBlocked: data.current?.blocked === true,
    statuses,
    doneCount: flags.filter(Boolean).length,
    activeIndex,
    detail,
  }
}

const basename = (path: unknown) => String(path ?? '').replace(/^.*[\\/]/, '')
const clip = (text: string, max = 60) => (text.length > max ? `${text.slice(0, max - 1)}…` : text)

// A slug-style ticket ("todo-by-id") already says what the title says; show it once.
const same = (a: string, b: string) =>
  a.toLowerCase().replace(/[^a-z0-9]/g, '') === b.toLowerCase().replace(/[^a-z0-9]/g, '')
const rowName = (row: PipelineRow) =>
  (row.ticket && same(row.ticket, row.title) ? row.ticket : [row.ticket, row.title].filter(Boolean).join(' ')) ||
  row.slug
// The ticket and title apart, for the pane's cards; a slug-style ticket stands in for the title.
const nameParts = (row: PipelineRow) =>
  row.ticket && same(row.ticket, row.title)
    ? { ticket: '', title: row.ticket }
    : { ticket: row.ticket, title: row.title || row.slug }
const pct = (row: PipelineRow) => Math.round((row.doneCount / row.labels.length) * 100)
const isComplete = (row: PipelineRow) => row.activeIndex === -1
const isWaiting = (row: PipelineRow) => !isComplete(row) && row.statuses[row.activeIndex] === 'waiting'
const stageLabel = (row: PipelineRow) =>
  isComplete(row) ? 'Complete' : `${row.labels[row.activeIndex]} ${row.activeIndex + 1}/${row.labels.length}`
const dotColor = (row: PipelineRow) =>
  isComplete(row) ? COLOR.done : isWaiting(row) ? COLOR.waiting : COLOR.active

// What a tool call says Claude is doing, in a few words; undefined for calls not worth showing.
function describe(e: Record<string, unknown>): string | undefined {
  const tool = String(e.tool ?? '')
  const said = typeof e.description === 'string' && e.description ? e.description : undefined

  switch (tool) {
    case 'Skill':
      return `Running /${String(e.skill ?? '').replace(/^.*:/, '')}`
    case 'Agent':
      return said ? `Agent: ${said}` : 'Running a subagent'
    case 'Bash':
    case 'PowerShell':
      return said
    case 'Edit':
    case 'Write':
    case 'NotebookEdit':
      return `Editing ${basename(e.file_path ?? e.notebook_path)}`
    case 'Read':
      return `Reading ${basename(e.file_path)}`
    case 'Grep':
    case 'Glob':
      return `Searching for ${clip(String(e.pattern ?? ''), 30)}`
    case 'WebFetch':
    case 'WebSearch':
      return 'Researching on the web'
    case 'Artifact':
      return e.action === 'read' ? 'Reading a page' : 'Publishing a page'
    default:
      return tool.startsWith('mcp__') ? `Calling ${tool.split('__').pop()}` : undefined
  }
}

// One goal per phase, each met at that phase's own gate: the review checkpoint, then a ready PR.
const GOALS = {
  review: '/next has reached the review checkpoint',
  complete: 'complete /next: the pull request is ready',
} as const

// Phases seen on the previous refresh; a goal fires only on a change seen while watching.
let lastPhases: Record<string, { plan: boolean; review: boolean }> | null = null
// When this module loaded; an item first seen whose file was written later is a change seen live.
let watchingSince = 0

async function setGoals($: EngineInterface, rows: PipelineRow[], mtimes: Record<string, number>) {
  const current = rows.find(row => row.isCurrentBranch)
  const before = lastPhases
  lastPhases = Object.fromEntries(
    rows.map(row => [row.slug, { plan: row.isPlanApproved, review: row.isReviewApproved }]),
  )
  if (!current || !before) return

  const fresh = (mtimes[current.slug] ?? 0) > watchingSince
  const was = before[current.slug] ?? (fresh ? { plan: false, review: false } : undefined)
  if (!was) return
  const phase =
    current.isReviewApproved && !was.review
      ? 'complete'
      : current.isPlanApproved && !was.plan
        ? 'review'
        : undefined
  // A pipeline already finished has nothing left for the completion goal to drive.
  if (!phase || (phase === 'complete' && current.activeIndex === -1)) return

  const already = (await read($, goalsSet))[current.slug] ?? []
  if (already.includes(phase)) return
  await update($, goalsSet, all => ({ ...all, [current.slug]: [...already, phase] }))

  // command.run is refused inside a hook the turn waits on, so it runs off a timer instead.
  $.clock.after(50, () => {
    $.command
      .run({ command: 'goal', args: GOALS[phase] })
      .then(() => $.ui.toast(`Goal set: ${GOALS[phase]}`))
      .catch(err => $.ui.log(`dotnet-workflow-kit: could not set the goal: ${String(err)}`))
  })
}

let lastJson = ''
let isRefreshing = false
// Parsed state files by name, reused while the file's mtime is unchanged.
const cache = new Map<string, { mtime: number; data: StateFile | null }>()
let lastDone: Record<string, boolean[]> | null = null
let lastWaiting: Record<string, boolean> | null = null

async function homeDir($: EngineInterface) {
  const home = (await $.env.get('USERPROFILE')) || (await $.env.get('HOME')) || ''

  return home.replace(/\\/g, '/')
}

type Repo = { branch: string; commonDir: string; root: string; isWorktree: boolean }

// The session's repository: its checked-out branch and the git dir that holds its refs
// (a worktree's own git dir points at the shared one through `commondir`).
async function currentRepo($: EngineInterface): Promise<Repo | undefined> {
  try {
    let dir = ((await $.session.cwd()) as string).replace(/\\/g, '/')
    for (let i = 0; i < 12 && dir; i++) {
      const dotGit = `${dir}/.git`
      if (await $.fs.exists(dotGit)) {
        const stat = await $.fs.stat(dotGit)
        let gitDir = dotGit
        if (stat.kind === 'file') {
          const pointer = ((await $.fs.read(dotGit)) as string).trim()
          gitDir = pointer.replace(/^gitdir:\s*/, '').replace(/\\/g, '/')
          if (!/^([a-zA-Z]:)?\//.test(gitDir)) gitDir = `${dir}/${gitDir}`
        }
        const head = ((await $.fs.read(`${gitDir}/HEAD`)) as string).trim()
        let commonDir = gitDir
        if (await $.fs.exists(`${gitDir}/commondir`)) {
          const common = ((await $.fs.read(`${gitDir}/commondir`)) as string).trim().replace(/\\/g, '/')
          commonDir = /^([a-zA-Z]:)?\//.test(common) ? common : `${gitDir}/${common}`
        }

        return {
          branch: head.startsWith('ref: refs/heads/') ? head.slice(16) : '',
          commonDir,
          root: dir,
          isWorktree: stat.kind === 'file',
        }
      }
      const parent = dir.replace(/\/[^/]+$/, '')
      if (parent === dir) break
      dir = parent
    }
  } catch {
    // Not a repository: no rows, since no item can be tied to it.
  }

  return undefined
}

// Whether the branch exists in this repository, loose or packed; items from other repos fail it.
async function hasBranch($: EngineInterface, repo: Repo, branch: string, packed: string): Promise<boolean> {
  if (!branch) return false
  if (packed.includes(` refs/heads/${branch}\n`)) return true

  return $.fs.exists(`${repo.commonDir}/refs/heads/${branch}`)
}

async function refresh($: EngineInterface) {
  if (isRefreshing) return
  isRefreshing = true
  try {
    const dir = `${await homeDir($)}/.claude/dotnet-workflow-kit/pipeline`
    const [entries, repo, now] = await Promise.all([
      $.fs.exists(dir).then(has => (has ? $.fs.list(dir) : [])),
      currentRepo($),
      $.clock.now(),
    ])
    const branch = repo?.branch ?? ''
    const packed = repo && (await $.fs.exists(`${repo.commonDir}/packed-refs`))
      ? `${await $.fs.read(`${repo.commonDir}/packed-refs`)}\n`
      : ''

    const found: { row: PipelineRow; mtime: number; branch: string }[] = []
    // Every branch some file names, closed or not, so a branch is adopted only when none does.
    const named = new Set<string>()
    for (const entry of entries) {
      const name = entry.name as string
      if (entry.kind !== 'file' || !name.endsWith('.json') || name.includes('-checks')) continue
      try {
        let hit = cache.get(name)
        if (!hit || hit.mtime !== entry.mtimeMs) {
          hit = { mtime: entry.mtimeMs, data: JSON.parse(await $.fs.read(`${dir}/${name}`)) as StateFile }
          cache.set(name, hit)
        }
        const data = hit.data
        if (data?.branch) named.add(data.branch)
        if (!data?.stages || Object.keys(data.stages).length === 0) continue
        if (data.closed && now - Date.parse(data.closed.at) > REMOVE_MS) continue
        const row = toRow(name.slice(0, -5), data, branch)
        const isRecent = now - entry.mtimeMs < RECENT_MS
        // Other items show only when recent and on a branch of this same repository.
        const isHere =
          row.isCurrentBranch || (isRecent && !!repo && (await hasBranch($, repo, data.branch ?? '', packed)))
        if (isHere) found.push({ row, mtime: entry.mtimeMs, branch: data.branch ?? '' })
      } catch {
        // A half-written or foreign file: skip it this round.
      }
    }

    if (repo && !named.has(repo.branch) && (await adopt($, dir, repo))) return

    // The cap below must never push a live item out for a finished one, so unfinished rows sort
    // ahead of complete ones; the viewing session's own row always stays first.
    found.sort(
      (a, b) =>
        Number(b.row.isCurrentBranch) - Number(a.row.isCurrentBranch) ||
        Number(isComplete(a.row)) - Number(isComplete(b.row)) ||
        b.mtime - a.mtime,
    )
    // Two files for one branch (keyed differently by two writers) are one item: keep the newest.
    const seen = new Set<string>()
    const unique = found.filter(f => !f.branch || (!seen.has(f.branch) && !!seen.add(f.branch)))
    const next = unique.slice(0, MAX_ROWS).map(f => f.row)

    // Every session runs this module, so each toasts only its own item's stages; another item's
    // gate toasts only when the person turned that on in the Sessions pane.
    const shouldNotifyOthers = await read($, notifyOthers)
    const done: Record<string, boolean[]> = {}
    const waiting: Record<string, boolean> = {}
    for (const row of next) {
      done[row.slug] = row.statuses.map(s => s === 'done')
      waiting[row.slug] = isWaiting(row)
      const before = lastDone?.[row.slug]
      if (row.isCurrentBranch && before) {
        row.statuses.forEach((s, i) => {
          if (s === 'done' && !before[i]) $.ui.toast(`${row.ticket || row.title}: ${row.labels[i]} done`)
        })
      }
      const isNewGate = !!lastWaiting && waiting[row.slug] && !lastWaiting[row.slug]
      if (!row.isCurrentBranch && shouldNotifyOthers && isNewGate) {
        $.ui.toast(`${rowName(row)}: ${row.detail || 'waiting on you'}`)
      }
    }
    lastDone = done
    lastWaiting = waiting

    await setGoals($, next, Object.fromEntries(found.map(f => [f.row.slug, f.mtime])))

    const json = JSON.stringify(next)
    if (json !== lastJson) {
      lastJson = json
      await update($, rows, () => next)
    }
  } catch (err) {
    $.ui.log(`dotnet-workflow-kit: ${String(err)}`)
  } finally {
    isRefreshing = false
  }
}

// The branches a team works from, per repository root; their sessions are not work items.
const bases = new Map<string, string[]>()

async function baseBranches($: EngineInterface, repo: Repo): Promise<string[]> {
  const known = bases.get(repo.root)
  if (known) return known
  const found = ['main', 'master']
  for (const path of [`${repo.root}/.claude/dotnet-workflow-kit.json`, `${await homeDir($)}/.claude/dotnet-workflow-kit.json`]) {
    try {
      if (!(await $.fs.exists(path))) continue
      const base = (JSON.parse(await $.fs.read(path)) as { base_branch?: unknown }).base_branch
      if (typeof base === 'string' && base) found.push(base)
      break
    } catch {
      // An unreadable profile leaves the defaults.
    }
  }
  bases.set(repo.root, found)

  return found
}

// feat/391-foo -> feat-391-foo: the file name `/next` keys a branch with no ticket id by. A
// "-checks" in it becomes "_checks", since refresh skips files named like a stage's checks.
const branchSlug = (branch: string) =>
  branch
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-checks/g, '_checks')

// Writes a state file for a branch no skill has written one for, with Start done; the skills
// take it over on their first run. Resolves to whether a file was written.
async function adopt($: EngineInterface, dir: string, repo: Repo): Promise<boolean> {
  if (!repo.branch || (await baseBranches($, repo)).includes(repo.branch)) return false
  const slug = branchSlug(repo.branch)
  const path = `${dir}/${slug}.json`
  // A file already there is one refresh could not read yet, such as a skill's half-written one.
  if (!slug || (await $.fs.exists(path))) return false
  const at = new Date(await $.clock.now()).toISOString().replace(/\.\d{3}Z$/, 'Z')
  const data: StateFile = {
    adopted: true,
    branch: repo.branch,
    repo: repo.commonDir,
    ...(repo.isWorktree ? { worktree: repo.root } : {}),
    current: { detail: ADOPTED_DETAIL },
    stages: { start: { done: true, at } },
  }
  await $.fs.write(path, `${JSON.stringify(data, null, 2)}
`)
  // The next refresh reads the new file; refresh is idle again by the time this timer fires.
  $.clock.after(50, () => void refresh($))

  return true
}

// Rewrites the current branch's adopted file when it is older than TOUCH_MS, so other sessions
// keep listing it and the closing script does not count a working branch as idle.
async function touchAdopted($: EngineInterface) {
  const current = (await read($, rows)).find(row => row.isCurrentBranch)
  if (!current) return
  const path = `${await homeDir($)}/.claude/dotnet-workflow-kit/pipeline/${current.slug}.json`
  try {
    const [stat, now] = await Promise.all([$.fs.stat(path), $.clock.now()])
    if (now - stat.mtimeMs < TOUCH_MS) return
    const data = JSON.parse(await $.fs.read(path)) as StateFile
    if (data.adopted !== true || data.closed) return
    await $.fs.write(path, `${JSON.stringify(data, null, 2)}
`)
  } catch {
    // Gone or half written: the next turn tries again.
  }
}

let isClosing = false

// Runs scripts/close_items.py for this repository: closes merged, closed and archived items
// and deletes those closed over a day ago. A missing Python or a failed run only logs.
async function closeItems($: EngineInterface) {
  if (isClosing) return
  isClosing = true
  try {
    const repo = await currentRepo($)
    if (!repo) return
    const script = `${$.plugin.root.replace(/\\/g, '/')}/scripts/close_items.py`
    const dir = `${await homeDir($)}/.claude/dotnet-workflow-kit/pipeline`
    for (const python of ['python', 'python3']) {
      try {
        const result = await $.process.run([python, script, '--repo', repo.commonDir, '--dir', dir], { timeoutMs: 300000 })
        if (result.exitCode !== 0) $.ui.log(`dotnet-workflow-kit: close_items: ${result.stderr.trim()}`)
        for (const line of result.stdout.split('\n').filter(Boolean)) $.ui.toast(line)
        break
      } catch {
        // This name is not on PATH; try the next.
      }
    }
    await refresh($)
  } finally {
    isClosing = false
  }
}

// `/progress done`: closes the current branch's item by hand, for work that ends without a PR.
async function closeCurrent($: EngineInterface): Promise<string> {
  const current = (await read($, rows)).find(row => row.isCurrentBranch)
  if (!current) return 'No pipeline item for this branch.'
  const path = `${await homeDir($)}/.claude/dotnet-workflow-kit/pipeline/${current.slug}.json`
  let data: StateFile
  try {
    data = JSON.parse(await $.fs.read(path)) as StateFile
  } catch {
    return `Could not read ${current.slug}.json; nothing was changed.`
  }
  if (!data.closed) {
    data.closed = { reason: 'manual', at: new Date(await $.clock.now()).toISOString().replace(/\.\d{3}Z$/, 'Z') }
    await $.fs.write(path, `${JSON.stringify(data, null, 2)}\n`)
  }
  await refresh($)

  return `${current.ticket || current.title} is done; its row goes in a day.`
}

// --- Aspire ---------------------------------------------------------------------------------

let isScanning = false
let lastQuietScan = 0
// Whether this session ran a command that started an AppHost; until then a quiet machine is scanned slowly.
let hasStarted = false
let runsAspire: boolean | undefined
let lastAspire: AspireEntry[] | null = null
let pythonName: string | undefined

const aspireDir = async ($: EngineInterface) => `${await homeDir($)}/.claude/dotnet-workflow-kit/aspire`
const ownerName = (entry: AspireEntry) => entry.label || entry.branch || 'another session'
const portsOf = (entry: AspireEntry) => [...new Set([...entry.ports, ...entry.launchPorts])].sort((a, b) => a - b)
const portList = (entry: AspireEntry) => portsOf(entry).map(port => `:${port}`).join(' ')
const dashboardPort = (entry: AspireEntry) => /:(\d+)/.exec(entry.dashboard.replace(/^[a-z]+:\/\//i, ''))?.[1]

// Whether the profile says the system runs through Aspire: the project's profile, else the personal one.
async function profileRunsAspire($: EngineInterface): Promise<boolean> {
  if (runsAspire !== undefined) return runsAspire
  runsAspire = false
  const repo = await currentRepo($)
  const paths = [...(repo ? [`${repo.root}/.claude/dotnet-workflow-kit.json`] : []), `${await homeDir($)}/.claude/dotnet-workflow-kit.json`]
  for (const path of paths) {
    try {
      if (!(await $.fs.exists(path))) continue
      const profile = JSON.parse(await $.fs.read(path)) as { stack?: { local_run?: unknown } }
      runsAspire = profile.stack?.local_run === 'aspire'
      break
    } catch {
      // An unreadable profile leaves Aspire off.
    }
  }

  return runsAspire
}

// Whether any session has an AppHost in the registry, live or not yet cleared away.
async function isListed($: EngineInterface): Promise<boolean> {
  const dir = await aspireDir($)
  if (!(await $.fs.exists(dir))) return false

  return (await $.fs.list(dir)).some(entry => entry.kind === 'file' && String(entry.name).endsWith('.json'))
}

type AspireResult = { entries: AspireEntry[]; deny?: string; starts?: string }

// Runs scripts/aspire_sessions.py as this session: its id, worktree, branch and item name.
async function runAspire($: EngineInterface, action: 'scan' | 'check', extra: string[] = []): Promise<AspireResult | undefined> {
  const repo = await currentRepo($)
  const current = (await read($, rows)).find(row => row.isCurrentBranch)
  const script = `${$.plugin.root.replace(/\\/g, '/')}/scripts/aspire_sessions.py`
  const args = [
    script, action,
    '--dir', await aspireDir($),
    '--session', await $.session.id(),
    '--root', repo?.root ?? '',
    '--repo', repo?.commonDir ?? '',
    '--branch', repo?.branch ?? '',
    '--label', current ? rowName(current) : (repo?.branch ?? ''),
    ...extra,
  ]
  for (const python of pythonName ? [pythonName] : ['python', 'python3']) {
    try {
      const result = await $.process.run([python, ...args], { timeoutMs: 60000 })
      if (result.exitCode !== 0) {
        // A name that ran the script and failed is the right Python; a stub that is not goes on to the next.
        if (pythonName || result.stderr.includes('aspire_sessions')) {
          $.ui.log(`dotnet-workflow-kit: aspire_sessions: ${result.stderr.trim()}`)
          return undefined
        }
        continue
      }
      pythonName = python

      return JSON.parse(result.stdout) as AspireResult
    } catch {
      // This name is not on PATH, or printed no JSON; try the next.
    }
  }

  return undefined
}

// Stores a scan's entries, with a toast when another session's AppHost goes and when this one's starts.
async function applyAspire($: EngineInterface, entries: AspireEntry[]) {
  const before = lastAspire
  lastAspire = entries
  if (before) {
    const live = new Set(entries.map(entry => entry.pid))
    for (const gone of before.filter(entry => !entry.isMine && !live.has(entry.pid))) {
      const free = portList(gone)
      $.ui.toast(`${ownerName(gone)} stopped ${gone.project}${free ? ` · ${free} free` : ''}`)
    }
    const had = new Set(before.filter(entry => entry.isMine).map(entry => entry.pid))
    for (const fresh of entries.filter(entry => entry.isMine && !had.has(entry.pid))) {
      $.ui.toast(`${fresh.project} is this session's${fresh.dashboard ? `: dashboard ${fresh.dashboard}` : ''}`)
    }
  }
  // seenAt moves on every scan; only a change worth drawing updates the atom.
  const key = (list: AspireEntry[]) => JSON.stringify(list.map(({ seenAt, ...rest }) => rest))
  if (key(entries) !== key(await read($, aspire))) await update($, aspire, () => entries)
}

async function scanAspire($: EngineInterface) {
  if (isScanning) return
  isScanning = true
  try {
    // An owner rescans often, so its entries never look abandoned; any other session looks now and
    // then, since a check scans afresh before judging a command anyway.
    const isOwner = hasStarted || (await read($, aspire)).some(entry => entry.isMine)
    if (!isOwner) {
      // Nothing listed and no profile running Aspire: nothing to show or protect.
      if (!(await isListed($)) && !(await profileRunsAspire($))) {
        if ((await read($, aspire)).length > 0) await applyAspire($, [])
        return
      }
      const now = await $.clock.now()
      if (now - lastQuietScan < QUIET_MS) return
      lastQuietScan = now
    }
    const result = await runAspire($, 'scan')
    if (result) await applyAspire($, result.entries)
  } catch (err) {
    $.ui.log(`dotnet-workflow-kit: aspire: ${String(err)}`)
  } finally {
    isScanning = false
  }
}

// Why a command must not run, as scripts/aspire_sessions.py judges it; undefined lets it through.
async function checkAspire($: EngineInterface, command: string): Promise<string | undefined> {
  const mayStart = /\b(run|watch|start)\b/i.test(command)
  if (!mayStart && !(await isListed($))) return undefined
  const result = await runAspire($, 'check', ['--cwd', await $.session.cwd(), '--command', command])
  if (!result) return undefined
  await applyAspire($, result.entries)
  if (result.starts) {
    hasStarted = true
    for (const ms of START_SCANS_MS) $.clock.after(ms, () => void scanAspire($))
  }

  return result.deny
}

// What Claude is told about the AppHosts on this machine; empty when none run.
function aspirePrompt(entries: AspireEntry[]): string {
  const mine = entries.filter(entry => entry.isMine)
  const others = entries.filter(entry => !entry.isMine && !entry.isStale)
  if (mine.length === 0 && others.length === 0) return ''
  const line = (entry: AspireEntry) =>
    `- ${entry.project} · pid ${entry.pid}${entry.dashboard ? ` · dashboard ${entry.dashboard}` : ''}` +
    `${portsOf(entry).length ? ` · ports ${portsOf(entry).join(' ')}` : ''}`

  return [
    '# Aspire on this machine',
    'The dotnet-workflow-kit tracks which Claude session owns each running Aspire AppHost.',
    'Yours:',
    ...(mine.length ? mine.map(line) : ['- none running']),
    ...(others.length
      ? [
          "Other sessions':",
          ...others.map(entry => `${line(entry)} · ${ownerName(entry)}`),
          "Never stop, restart or reuse another session's AppHost or its ports: commands that would are refused. " +
            'Start yours on ports nobody else holds. To have one stopped, ask the person or message its session.',
        ]
      : []),
  ].join('\n')
}

// The Sessions pane's "Ask its session to stop it": a message to the session that owns the AppHost.
async function askToStop($: EngineInterface, entry: AspireEntry) {
  try {
    const sent = await $.session.send({
      to: { sessionId: entry.session },
      text:
        `The person asked, from another session's Sessions pane, for ${entry.project} (pid ${entry.pid}) to be ` +
        'stopped so its ports are free. Stop it if your work allows, and say so.',
    })
    $.ui.toast(sent.isDelivered ? `Asked ${ownerName(entry)} to stop ${entry.project}` : `Could not reach that session: ${sent.reason}`)
  } catch (err) {
    $.ui.toast(`Could not reach that session: ${String(err)}`)
  }
}

// A session that ends leaves its AppHosts' entries marked as gone, for a session in the same worktree to take.
async function endAspire($: EngineInterface) {
  const dir = await aspireDir($)
  for (const entry of (await read($, aspire)).filter(one => one.isMine)) {
    try {
      const path = `${dir}/${entry.pid}.json`
      const data = JSON.parse(await $.fs.read(path)) as AspireEntry
      if (data.session === entry.session) await $.fs.write(path, `${JSON.stringify({ ...data, seenAt: 0 }, null, 2)}\n`)
    } catch {
      // Gone already.
    }
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    watchingSince = await $.clock.now()
    await $.command.register({
      name: 'progress',
      description: 'Show or hide the workflow progress bar; "done" closes this branch\'s item',
    })
    await $.command.register({
      name: 'sessions',
      description: 'Show or hide the pane listing every work item in this repository',
    })
    await refresh($)
    $.clock.every(POLL_MS, () => void refresh($))
    $.clock.after(1000, () => void closeItems($))
    $.clock.every(CLOSE_MS, () => void closeItems($))
    // The first prompt is composed right after this, so the AppHosts are looked up first, briefly.
    await Promise.race([scanAspire($), $.clock.sleep(3000)])
    $.clock.every(ASPIRE_MS, () => void scanAspire($))

    return next(e)
  })

  on('session.end', async ($, e, next) => {
    await endAspire($)

    return next(e)
  })

  // The AppHosts on this machine and whose they are, last in the prompt, while any run.
  on('prompt.compose', async ($, e, next) => {
    const result = await next(e)
    const text = aspirePrompt(await read($, aspire))
    if (!text) return result

    return { sections: [...result.sections, { id: 'dotnet-workflow-kit:aspire', text, scope: 'session' as const }] }
  })

  on('command.run', { command: 'progress' }, async ($, e) => {
    if (e.args.trim() === 'done') return { text: await closeCurrent($) }
    const hidden = await update($, isHidden, h => !h)
    await refresh($)

    return { text: hidden ? 'Workflow progress bar hidden.' : 'Workflow progress bar shown.' }
  })

  on('command.run', { command: 'sessions' }, async $ => {
    const isOpen = await toggleSessions($)

    return { text: isOpen ? 'Sessions pane opened.' : 'Sessions pane closed.' }
  })

  on('tool.call', async ($, e, next) => {
    const input = e as unknown as Record<string, unknown>
    const text = describe(input)
    if (text) {
      const now = await $.clock.now()
      await update($, activity, (): Activity => ({ text: clip(text), at: now }))
    }
    // A shell command that stops processes or starts an AppHost is judged against the other sessions' first.
    const command =
      (input.tool === 'Bash' || input.tool === 'PowerShell') && typeof input.command === 'string' ? input.command : ''
    const isAspire = !!command && ASPIRE_COMMAND.test(command)
    if (isAspire) {
      // A failed check never holds the command up; the deny is a guard, not a gate.
      const deny = await checkAspire($, command).catch(err => void $.ui.log(`dotnet-workflow-kit: aspire: ${String(err)}`))
      if (deny) return { deny }
    }
    const result = await next(e)
    void refresh($)
    if (isAspire) $.clock.after(2000, () => void scanAspire($))

    return result
  })

  // While /next is blocked, a goal re-prompt would only repeat the blocker; skip the goal's
  // Stop hook so the goal stays set but quiet until the person answers.
  on('classic.Stop', async ($, e, next) => {
    const pending = (e.background_tasks ?? []).filter(t => t.status === 'running' || t.status === 'pending')
    await update($, background, () => pending.map(t => clip(t.description || t.command || t.type)))
    await refresh($)
    const current = (await read($, rows)).find(row => row.isCurrentBranch)
    if (current?.isBlocked) return {}

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) await update($, activity, () => null)
    await refresh($)
    await touchAdopted($)

    return next(e)
  })

  // The band shows only this session's item; a chip counts the others and opens the Sessions pane.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const hiddenSlugs = await read($, dismissed)
    const all = (await read($, rows)).filter(one => !hiddenSlugs.includes(one.slug))
    const row = all.find(one => one.isCurrentBranch)
    const others = all.filter(one => !one.isCurrentBranch && !isComplete(one))
    const othersWaiting = others.filter(isWaiting).length
    if (e.props.hasSurvey || (!row && others.length === 0) || (await read($, isHidden))) {
      return next(e)
    }

    // The row shows live tool activity while Claude works, otherwise the file's detail.
    const live = await read($, activity)
    const tasks = e.props.isWorking ? [] : await read($, background)
    const isBusy = e.props.isWorking || tasks.length > 0
    const doing = (one: PipelineRow) =>
      isWaiting(one)
        ? one.detail
        : e.props.isWorking && live
          ? live.text
          : tasks.length > 0
            ? `Waiting on ${tasks.length === 1 ? tasks[0] : `${tasks.length} background tasks`}`
            : one.detail
    const chipLabel =
      others.length === 0 ? '' : othersWaiting > 0 ? `+${others.length} · ${othersWaiting} needs you` : `+${others.length}`
    const openPane = () => void toggleSessions($)
    // This session's own AppHost, by its dashboard port.
    const host = (await read($, aspire)).find(one => one.isMine)
    const hostPort = host ? dashboardPort(host) ?? host.ports[0] : undefined
    const hostLabel = host ? `Aspire${hostPort ? ` :${hostPort}` : ''}` : ''

    if (e.surface === 'terminal') {
      const { Box, Text, Button } = $.ui.resolve(e)
      const cols = e.props.bodyColumns
      const chip = chipLabel ? (
        <Box flexShrink={0} gap={1}>
          {othersWaiting > 0 ? <Text color={COLOR.waiting}>●</Text> : null}
          <Button key="sessions-chip" label={chipLabel} plain dimColor={othersWaiting === 0} onPress={openPane} />
        </Box>
      ) : null
      if (!row) {
        return (
          <Box width={cols} justifyContent="flex-end">
            {chip}
          </Box>
        )
      }

      const nameWidth = Math.max(10, Math.min(28, Math.floor(cols * 0.22)))
      const stageWidth = stageLabel(row).length
      const chipWidth = chipLabel ? chipLabel.length + 4 : 0
      const doingMin = cols >= 90 ? 24 : 0
      // A narrow terminal keeps the AppHost's mark and drops its label.
      const isHostLabelled = cols >= 90
      const hostWidth = host ? (isHostLabelled ? hostLabel.length + 3 : 2) : 0
      // dot, name, bar, stage, percent, AppHost, chip and their one-cell gaps, then the activity text.
      const room = cols - 2 - nameWidth - stageWidth - 4 - 5 - hostWidth - chipWidth - doingMin
      const segment = Math.max(1, Math.min(6, Math.floor(room / row.labels.length)))

      return (
        <Box gap={1} width={cols}>
          <Box flexShrink={0}>
            <Text color={dotColor(row)}>●</Text>
          </Box>
          <Box width={nameWidth} flexShrink={0}>
            <Text wrap="truncate-end" bold>
              {rowName(row)}
            </Text>
          </Box>
          <Box width={segment * row.labels.length} flexShrink={0}>
            <Text wrap="truncate-end">
              {row.statuses.map(s => (
                <Text color={s === 'todo' ? COLOR.todo : COLOR[s]} dimColor={s === 'todo'}>
                  {(s === 'todo' ? '░' : s === 'done' ? '█' : '▓').repeat(segment)}
                </Text>
              ))}
            </Text>
          </Box>
          <Box width={stageWidth} flexShrink={0}>
            <Text color={dotColor(row)} wrap="truncate-end">
              {stageLabel(row)}
            </Text>
          </Box>
          <Box width={4} flexShrink={0}>
            <Text dimColor>{String(pct(row)).padStart(3)}%</Text>
          </Box>
          {host ? (
            <Box flexShrink={0} gap={1}>
              <Text color={CARD.check}>◆</Text>
              {isHostLabelled ? <Text dimColor>{hostLabel}</Text> : null}
            </Box>
          ) : null}
          {doingMin > 0 && doing(row) ? (
            <Box flexGrow={1} flexShrink={1} minWidth={0}>
              <Text dimColor wrap="truncate-end">
                {doing(row)}
              </Text>
            </Box>
          ) : null}
          {chip}
        </Box>
      )
    }

    const { Box, Text, Svg, Button } = $.ui.resolve(e)
    const chip = chipLabel ? (
      <Box flexDirection="row" alignItems="center" gap={1} flexShrink={0}>
        {othersWaiting > 0 ? <Text color={COLOR.waiting}>●</Text> : null}
        <Button key="sessions-chip" label={`${chipLabel} ›`} plain dimColor={othersWaiting === 0} onPress={openPane} />
      </Box>
    ) : null
    if (!row) {
      return (
        <Box flexDirection="row" justifyContent="flex-end">
          {chip}
        </Box>
      )
    }

    // Never wraps: the name column and the bar share what the fixed cluster on the right leaves,
    // and the bar's drawing scales down to its slot rather than spilling over the name.
    return (
      <Box flexDirection="row" flexWrap="nowrap" alignItems="center" gap={2}>
        <Box flexShrink={0}>
          <Text color={dotColor(row)}>●</Text>
        </Box>
        <Box flexDirection="column" flexGrow={1} flexShrink={1} width="35%" minWidth={0}>
          <Text wrap="truncate-end">{rowName(row)}</Text>
          {doing(row) ? (
            <Text dimColor wrap="truncate-end">
              {doing(row)}
            </Text>
          ) : null}
        </Box>
        <Box flexShrink={1} width={BAR_WIDTH} minWidth={0} overflow="hidden">
          <Svg
            source={barSvg(row, isBusy)}
            alt={`${rowName(row)}: ${stageLabel(row)}, ${pct(row)}% complete${doing(row) ? `, ${doing(row)}` : ''}`}
          />
        </Box>
        <Box flexDirection="row" flexWrap="nowrap" alignItems="center" gap={2} flexShrink={0}>
          <Text dimColor>{pct(row)}%</Text>
          {host ? (
            <Box flexDirection="row" alignItems="center" gap={1} flexShrink={0}>
              <Text color={CARD.check}>●</Text>
              <Text dimColor>{hostLabel}</Text>
            </Box>
          ) : null}
          {chip}
          {isComplete(row) ? (
            <Button
              key={`dismiss-${row.slug}`}
              label="✕"
              plain
              dimColor
              onPress={() => update($, dismissed, slugs => [...slugs, row.slug])}
            />
          ) : null}
        </Box>
      </Box>
    )
  })

  // Every item in this repository, grouped by what it needs from the person: open items as cards
  // with their stages, finished ones as a single line each.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const elements = $.ui.resolve(e)
    const { Box, Text, Button, Link } = elements
    const Svg = 'Svg' in elements ? elements.Svg : undefined
    const isTerminal = e.surface === 'terminal'
    const hiddenSlugs = await read($, dismissed)
    const list = (await read($, rows)).filter(row => !hiddenSlugs.includes(row.slug))
    const shouldNotify = await read($, notifyOthers)
    const needsYou = list.filter(isWaiting)
    const running = list.filter(row => !isComplete(row) && !isWaiting(row))
    const done = list.filter(isComplete)
    const dismiss = (slugs: string[]) => update($, dismissed, all => [...new Set([...all, ...slugs])])
    const hosts = await read($, aspire)
    const nowS = (await $.clock.now()) / 1000
    const since = (entry: AspireEntry) => {
      const minutes = Math.max(0, Math.round((nowS - entry.firstSeen) / 60))

      return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`
    }

    // One AppHost on a card: whether it runs, for how long, its dashboard and the ports it holds.
    const hostBlock = (entry: AspireEntry) => (
      <Box key={`aspire-${entry.pid}`} flexDirection="column">
        <Box flexDirection="row" gap={1} alignItems="center">
          <Text color={entry.isStale ? COLOR.todo : CARD.check}>●</Text>
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text wrap="truncate-end">
              <Text bold>{entry.project}</Text>
              <Text dimColor>{` · ${entry.isStale ? 'its session has ended' : `running ${since(entry)}`} · pid ${entry.pid}`}</Text>
            </Text>
          </Box>
          {entry.dashboard ? <Link key={`dashboard-${entry.pid}`} href={entry.dashboard} label="Dashboard ↗" /> : null}
        </Box>
        {portsOf(entry).length ? (
          <Text dimColor wrap="truncate-end">
            {portList(entry)}
          </Text>
        ) : null}
        {!entry.isMine && !entry.isStale ? (
          <Box flexDirection="row">
            <Button key={`stop-${entry.pid}`} label="Ask its session to stop it" onPress={() => askToStop($, entry)} />
          </Box>
        ) : null}
      </Box>
    )

    const heading = (title: string, count: number, color?: string) => (
      <Text bold color={color} dimColor={!color}>
        {title.toUpperCase()} · {count}
      </Text>
    )

    const stages = (row: PipelineRow) => {
      const alt = `${stageLabel(row)}, ${pct(row)}% complete`
      if (Svg) return <Svg source={segmentsSvg(row)} alt={alt} height={SEGMENT_HEIGHT} />

      return (
        <Text wrap="truncate-end">
          {row.statuses.map((s, i) => (
            <Text key={`${row.slug}-${i}`} color={segmentColor(row, s)}>
              {s === 'todo' ? '▱▱▱ ' : '▰▰▰ '}
            </Text>
          ))}
        </Text>
      )
    }

    const card = (row: PipelineRow) => {
      const waiting = isWaiting(row)
      const name = nameParts(row)
      const border = waiting ? CARD.waitingBorder : row.isCurrentBranch ? CARD.currentBorder : CARD.border
      const tint = isTerminal ? undefined : waiting ? CARD.waitingTint : row.isCurrentBranch ? CARD.currentTint : undefined

      return (
        <Box
          key={`card-${row.slug}`}
          flexDirection="column"
          gap={isTerminal ? 0 : 1}
          paddingX={1}
          paddingY={isTerminal ? 0 : 1}
          borderStyle="round"
          borderColor={border}
          backgroundColor={tint}
        >
          <Box flexDirection="row" gap={1} alignItems="center">
            {name.ticket ? <Text dimColor>{name.ticket}</Text> : null}
            <Box flexGrow={1} flexShrink={1} minWidth={0}>
              <Text bold wrap="truncate-end">
                {name.title}
              </Text>
            </Box>
            {row.isCurrentBranch ? <Text color={CARD.currentText}>Viewing</Text> : null}
          </Box>
          {stages(row)}
          {hosts
            .filter(one => one.branch === row.branch && one.isMine === row.isCurrentBranch)
            .map(hostBlock)}
          <Box flexDirection="row" gap={1} alignItems="center">
            <Box flexGrow={1} flexShrink={1} minWidth={0}>
              <Text wrap="truncate-end">
                <Text color={waiting ? COLOR.waiting : CARD.currentText}>{stageLabel(row)}</Text>
                {row.detail ? <Text dimColor>{` · ${row.detail.replace(/^Waiting on you: /, '')}`}</Text> : null}
              </Text>
            </Box>
            {row.isCurrentBranch ? null : (
              <Button
                key={`show-${row.slug}`}
                label="Show"
                variant={waiting ? 'primary' : undefined}
                onPress={() =>
                  $.ui.toast(`${rowName(row)} is on ${row.branch || 'another branch'}: open its session from the list`)
                }
              />
            )}
          </Box>
        </Box>
      )
    }

    const doneLine = (row: PipelineRow) => {
      const name = nameParts(row)

      return (
        <Box key={`done-${row.slug}`} flexDirection="row" gap={1} alignItems="center" paddingX={1}>
          <Text color={CARD.check}>✓</Text>
          {name.ticket ? <Text dimColor>{name.ticket}</Text> : null}
          <Box flexGrow={1} flexShrink={1} minWidth={0}>
            <Text dimColor wrap="truncate-end">
              {name.title}
            </Text>
          </Box>
          <Text dimColor>{row.detail || 'Done'}</Text>
          <Button key={`dismiss-${row.slug}`} label="✕" plain dimColor onPress={() => dismiss([row.slug])} />
        </Box>
      )
    }

    return (
      <Box flexDirection="column" gap={1}>
        {list.length === 0 ? <Text dimColor>No work items in this repository yet. /start begins one.</Text> : null}
        {needsYou.length > 0 ? (
          <Box key="needs-you" flexDirection="column" gap={1}>
            {heading('Needs you', needsYou.length, COLOR.waiting)}
            {needsYou.map(card)}
          </Box>
        ) : null}
        {running.length > 0 ? (
          <Box key="running" flexDirection="column" gap={1}>
            {heading('Running', running.length)}
            {running.map(card)}
          </Box>
        ) : null}
        {done.length > 0 ? (
          <Box key="done" flexDirection="column" gap={isTerminal ? 0 : 1}>
            <Box flexDirection="row" justifyContent="space-between" alignItems="center">
              {heading('Done', done.length)}
              <Button
                key="dismiss-all"
                label="Dismiss all"
                plain
                dimColor
                onPress={() => dismiss(done.map(row => row.slug))}
              />
            </Box>
            {done.map(doneLine)}
          </Box>
        ) : null}
        {hosts.length > 0 ? (
          <Box key="apphosts" flexDirection="column" gap={isTerminal ? 0 : 1}>
            {heading('AppHosts on this machine', hosts.length)}
            {hosts.map(entry => (
              <Box key={`host-${entry.pid}`} flexDirection="row" gap={1} alignItems="center" paddingX={1}>
                <Text color={entry.isStale ? COLOR.todo : CARD.check}>●</Text>
                <Box flexGrow={1} flexShrink={1} minWidth={0}>
                  <Text wrap="truncate-end">
                    <Text>{entry.project}</Text>
                    <Text color={entry.isMine ? CARD.currentText : undefined} dimColor={!entry.isMine}>
                      {` · ${entry.isMine ? 'you' : entry.isStale ? 'session ended' : ownerName(entry)}`}
                    </Text>
                  </Text>
                </Box>
                <Text dimColor>{portList(entry)}</Text>
              </Box>
            ))}
          </Box>
        ) : null}
        <Box marginTop={1}>
          <Button
            key="notify-others"
            label={`Notify me when another session needs me: ${shouldNotify ? 'On' : 'Off'}`}
            plain
            dimColor
            onPress={() => update($, notifyOthers, isOn => !isOn)}
          />
        </Box>
      </Box>
    )
  })
}

// Opens the Sessions pane, or closes it when it is already up; resolves to whether it is now open.
async function toggleSessions($: EngineInterface): Promise<boolean> {
  if ((await $.ui.panes()).some(pane => pane.id === PANE)) {
    await $.ui.close({ id: PANE })

    return false
  }
  await $.ui.open({ id: PANE, title: 'Sessions' })

  return true
}

function segmentColor(row: PipelineRow, status: StageStatus): string {
  if (status === 'done') return isWaiting(row) ? SEGMENT.waitingDone : SEGMENT.done

  return SEGMENT[status]
}

const SEGMENT_WIDTH = 360
const SEGMENT_HEIGHT = 4

// A card's stages as thin rounded segments with a small gap between each.
function segmentsSvg(row: PipelineRow): string {
  const gap = 3
  const total = row.statuses.length
  const w = (SEGMENT_WIDTH - gap * (total - 1)) / total
  const bars = row.statuses.map(
    (s, i) =>
      `<rect x="${(i * (w + gap)).toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${SEGMENT_HEIGHT}" rx="2" fill="${segmentColor(row, s)}"/>`,
  )

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${SEGMENT_WIDTH}" height="${SEGMENT_HEIGHT}" ` +
    `viewBox="0 0 ${SEGMENT_WIDTH} ${SEGMENT_HEIGHT}" preserveAspectRatio="none">${bars.join('')}</svg>`
  )
}

function escapeXml(text: string) {
  return text.replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`)
}

const BAR_WIDTH = 400
const BAR_HEIGHT = 24

// A small seeded generator, so a row's dither pattern stays put between redraws.
function seeded(text: string) {
  let h = 2166136261
  for (const c of text) h = Math.imul(h ^ c.charCodeAt(0), 16777619)

  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)

    return ((h >>>= 0) % 10000) / 10000
  }
}

// The desktop bar: a dark rounded track, a pixel-dither fill up to the current stage,
// a pill naming that stage at the fill's head, and tick marks at the stage boundaries ahead.
function barSvg(row: PipelineRow, isWorking: boolean): string {
  const W = BAR_WIDTH
  const H = BAR_HEIGHT
  const r = H / 2
  const total = row.labels.length
  const isFinished = isComplete(row)
  const isGate = isWaiting(row)
  // Motion only while Claude is working on a stage, never at a gate or once finished.
  const isAnimated = isWorking && !isFinished && !isGate

  const stage = isFinished ? 'Done' : row.labels[row.activeIndex]
  const count = isFinished ? `${total}/${total}` : `${row.activeIndex + 1}/${total}`
  const pillW = Math.round(stage.length * 7.4 + count.length * 6.6 + 30)
  const head = (row.doneCount / total) * W
  const pillX = Math.min(W - pillW, Math.max(0, head - pillW * 0.4))
  const fillEnd = isFinished ? W : pillX + pillW / 2

  const pillFill = isGate ? '#f2b04c' : '#8e86f8'
  const pillText = isGate ? '#2b1d05' : '#ffffff'
  const dots = isGate ? ['#f2b04c', '#f7cd86', '#8a7a62'] : ['#8e86f8', '#c4c0ff', '#6e6a8c']

  const parts: string[] = []
  const random = seeded(row.slug)
  const cell = 3
  for (let x = 0; x < fillEnd; x += cell) {
    const t = x / Math.max(fillEnd, 1)
    for (let y = 0; y < H; y += cell) {
      if (random() > 0.3 + 0.6 * t * t) continue
      const colour = dots[Math.floor(random() * dots.length)]
      const opacity = (0.25 + random() * 0.6 * (0.4 + t)).toFixed(2)
      const twinkles = isAnimated && t > 0.55 && random() < 0.35
      if (twinkles) {
        const delay = (random() * 1.4).toFixed(2)
        parts.push(
          `<rect x="${x}" y="${y}" width="2.2" height="2.2" fill="${colour}" fill-opacity="${opacity}">` +
            `<animate attributeName="fill-opacity" values="${opacity};0.95;0.1;${opacity}" dur="1.4s" begin="-${delay}s" repeatCount="indefinite"/></rect>`,
        )
      } else {
        parts.push(`<rect x="${x}" y="${y}" width="2.2" height="2.2" fill="${colour}" fill-opacity="${opacity}"/>`)
      }
    }
  }

  for (let i = 1; i < total; i++) {
    const x = (i / total) * W
    if (x < pillX + pillW + 6) continue
    parts.push(`<rect x="${(x - 0.75).toFixed(1)}" y="${r - 5}" width="1.5" height="10" rx="0.75" fill="#ffffff" fill-opacity="0.28"/>`)
  }

  if (isAnimated && fillEnd > 0) {
    parts.push(
      `<rect x="-48" y="0" width="48" height="${H}" fill="url(#sweep)">` +
        `<animate attributeName="x" from="-48" to="${fillEnd.toFixed(1)}" dur="2.2s" repeatCount="indefinite"/></rect>`,
    )
  }

  const font = `font-family="system-ui,-apple-system,'Segoe UI',sans-serif" font-size="12"`
  const pill =
    `<rect x="${pillX.toFixed(1)}" y="0" width="${pillW}" height="${H}" rx="${r}" fill="${pillFill}"/>` +
    `<text x="${(pillX + 14).toFixed(1)}" y="${r + 4.2}" ${font} fill="${pillText}">` +
    `<tspan font-weight="700">${escapeXml(stage)}</tspan>` +
    `<tspan dx="6" fill-opacity="0.85">${count}</tspan></text>`

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
    `<defs><clipPath id="track"><rect width="${W}" height="${H}" rx="${r}"/></clipPath>` +
    `<linearGradient id="sweep" x1="0" x2="1" y1="0" y2="0">` +
    `<stop offset="0" stop-color="${pillFill}" stop-opacity="0"/>` +
    `<stop offset="0.5" stop-color="${pillFill}" stop-opacity="0.45"/>` +
    `<stop offset="1" stop-color="${pillFill}" stop-opacity="0"/></linearGradient></defs>` +
    `<rect width="${W}" height="${H}" rx="${r}" fill="#ffffff" fill-opacity="0.07"/>` +
    `<g clip-path="url(#track)">${parts.join('')}</g>` +
    pill +
    `</svg>`
  )
}
