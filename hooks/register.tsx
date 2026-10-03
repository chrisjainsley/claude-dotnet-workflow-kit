// The kit's progress bar: one row per work item above the prompt, drawn from the pipeline
// state files `start`, `plan` and `next` write under ~/.claude/dotnet-workflow-kit/pipeline.
// It also sets the run's /goal when the plan and then the review are approved.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Activity, PipelineRow, StageStatus } from '../types'

const rows = atom({ plugin: 'dotnet-workflow-kit', key: 'rows' } as const, [])
const isHidden = atom({ plugin: 'dotnet-workflow-kit', key: 'isHidden' } as const, false)
const dismissed = atom({ plugin: 'dotnet-workflow-kit', key: 'dismissed' } as const, [])
const activity = atom({ plugin: 'dotnet-workflow-kit', key: 'activity' } as const, null)
// What the session still has running in the background when its turn ends, so the bar keeps
// moving while Claude waits on a shell, subagent or workflow to wake it.
const background = atom({ plugin: 'dotnet-workflow-kit', key: 'background' } as const, [])
// Goals already set, per item: survives reloads so a phase's goal is set once.
const goalsSet = atom({ plugin: 'dotnet-workflow-kit', key: 'goalsSet' } as const, {})

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
const MAX_ROWS = 3
// Other items show beside the current branch's only while someone touched them recently.
const RECENT_MS = 24 * 60 * 60 * 1000
const POLL_MS = 4000

const COLOR = { done: '#c4c0ff', active: '#8e86f8', waiting: '#f59e0b', todo: '#6b7280' }

type Stage = {
  done?: boolean
  waiting?: boolean
  label?: string
  artifactUrl?: string
  decision?: string
  note?: string
}
type StateFile = {
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
  const flags = list.map(stage => stageDone(stages, stage.id))
  const activeIndex = flags.indexOf(false)
  const active = activeIndex === -1 ? undefined : list[activeIndex].id
  const activeStage = active ? stages[active === 'pull_request' ? 'pullRequest' : active] : undefined
  const isPlanGate = active === 'plan' && !!activeStage?.artifactUrl
  const isCheckpoint = active === 'review' && !!activeStage?.artifactUrl && !activeStage?.decision
  const isCustomGate = activeStage?.waiting === true
  const isWaiting = isPlanGate || isCheckpoint || isCustomGate

  const statuses: StageStatus[] = flags.map((done, i): StageStatus => {
    if (done) return 'done'
    if (i !== activeIndex) return 'todo'

    return isWaiting ? 'waiting' : 'active'
  })

  const detail = isPlanGate
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

async function homeDir($: EngineInterface) {
  const home = (await $.env.get('USERPROFILE')) || (await $.env.get('HOME')) || ''

  return home.replace(/\\/g, '/')
}

type Repo = { branch: string; commonDir: string }

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

        return { branch: head.startsWith('ref: refs/heads/') ? head.slice(16) : '', commonDir }
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
    if (!(await $.fs.exists(dir))) return
    const [entries, repo, now] = await Promise.all([$.fs.list(dir), currentRepo($), $.clock.now()])
    const branch = repo?.branch ?? ''
    const packed = repo && (await $.fs.exists(`${repo.commonDir}/packed-refs`))
      ? `${await $.fs.read(`${repo.commonDir}/packed-refs`)}\n`
      : ''

    const found: { row: PipelineRow; mtime: number; branch: string }[] = []
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
        if (!data?.stages || Object.keys(data.stages).length === 0) continue
        const row = toRow(name.slice(0, -5), data, branch)
        const isFinished = row.activeIndex === -1
        const isRecent = now - entry.mtimeMs < RECENT_MS
        // Other items show only when recent, unfinished and on a branch of this same repository.
        const isHere =
          row.isCurrentBranch ||
          (!isFinished && isRecent && !!repo && (await hasBranch($, repo, data.branch ?? '', packed)))
        if (isHere) found.push({ row, mtime: entry.mtimeMs, branch: data.branch ?? '' })
      } catch {
        // A half-written or foreign file: skip it this round.
      }
    }

    found.sort(
      (a, b) => Number(b.row.isCurrentBranch) - Number(a.row.isCurrentBranch) || b.mtime - a.mtime,
    )
    // Two files for one branch (keyed differently by two writers) are one item: keep the newest.
    const seen = new Set<string>()
    const unique = found.filter(f => !f.branch || (!seen.has(f.branch) && !!seen.add(f.branch)))
    const next = unique.slice(0, MAX_ROWS).map(f => f.row)

    const done: Record<string, boolean[]> = {}
    for (const row of next) {
      done[row.slug] = row.statuses.map(s => s === 'done')
      const before = lastDone?.[row.slug]
      if (!before) continue
      row.statuses.forEach((s, i) => {
        if (s === 'done' && !before[i]) $.ui.toast(`${row.ticket || row.title}: ${row.labels[i]} done`)
      })
    }
    lastDone = done

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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    watchingSince = await $.clock.now()
    await $.command.register({
      name: 'progress',
      description: 'Show or hide the workflow progress bar',
    })
    await refresh($)
    $.clock.every(POLL_MS, () => void refresh($))

    return next(e)
  })

  on('command.run', { command: 'progress' }, async $ => {
    const hidden = await update($, isHidden, h => !h)
    await refresh($)

    return { text: hidden ? 'Workflow progress bar hidden.' : 'Workflow progress bar shown.' }
  })

  on('tool.call', async ($, e, next) => {
    const text = describe(e as unknown as Record<string, unknown>)
    if (text) {
      const now = await $.clock.now()
      await update($, activity, (): Activity => ({ text: clip(text), at: now }))
    }
    const result = await next(e)
    void refresh($)

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

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const hiddenSlugs = await read($, dismissed)
    const list = (await read($, rows)).filter(row => !hiddenSlugs.includes(row.slug))
    if (e.props.hasSurvey || list.length === 0 || (await read($, isHidden))) {
      return next(e)
    }

    // A slug-style ticket ("todo-by-id") already says what the title says; show it once.
    const same = (a: string, b: string) => a.toLowerCase().replace(/[^a-z0-9]/g, '') === b.toLowerCase().replace(/[^a-z0-9]/g, '')
    const name = (row: PipelineRow) =>
      (row.ticket && same(row.ticket, row.title) ? row.ticket : [row.ticket, row.title].filter(Boolean).join(' ')) || row.slug
    const pct = (row: PipelineRow) => Math.round((row.doneCount / row.labels.length) * 100)
    const stageLabel = (row: PipelineRow) =>
      row.activeIndex === -1
        ? 'Complete'
        : `${row.labels[row.activeIndex]} ${row.activeIndex + 1}/${row.labels.length}`
    // The current branch's row shows live tool activity while Claude works, otherwise the file's detail.
    const live = await read($, activity)
    const tasks = e.props.isWorking ? [] : await read($, background)
    const isBusy = e.props.isWorking || tasks.length > 0
    const doing = (row: PipelineRow) =>
      !row.isCurrentBranch || row.statuses[row.activeIndex] === 'waiting'
        ? row.detail
        : e.props.isWorking && live
          ? live.text
          : tasks.length > 0
            ? `Waiting on ${tasks.length === 1 ? tasks[0] : `${tasks.length} background tasks`}`
            : row.detail
    const dotColor = (row: PipelineRow) =>
      row.activeIndex === -1
        ? COLOR.done
        : row.statuses[row.activeIndex] === 'waiting'
          ? COLOR.waiting
          : COLOR.active

    if (e.surface === 'terminal') {
      const { Box, Text } = $.ui.resolve(e)
      const cols = e.props.bodyColumns
      const stages = Math.max(...list.map(row => row.labels.length))
      const nameWidth = Math.max(10, Math.min(28, Math.floor(cols * 0.22)))
      const stageWidth = Math.max(...list.map(row => stageLabel(row).length))
      const doingMin = cols >= 90 ? 24 : 0
      // dot, name, bar, stage, percent and four one-cell gaps, then the activity text.
      const room = cols - 2 - nameWidth - stageWidth - 4 - 4 - doingMin
      const segment = Math.max(1, Math.min(6, Math.floor(room / stages)))

      return (
        <Box flexDirection="column">
          {list.map(row => (
            <Box key={row.slug} gap={1} width={cols}>
              <Box flexShrink={0}>
                <Text color={dotColor(row)}>●</Text>
              </Box>
              <Box width={nameWidth} flexShrink={0}>
                <Text wrap="truncate-end" bold={row.isCurrentBranch}>
                  {name(row)}
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
              {doingMin > 0 && doing(row) ? (
                <Box flexGrow={1} flexShrink={1} minWidth={0}>
                  <Text dimColor wrap="truncate-end">
                    {doing(row)}
                  </Text>
                </Box>
              ) : null}
            </Box>
          ))}
        </Box>
      )
    }

    const { Box, Text, Svg, Button } = $.ui.resolve(e)

    return (
      <Box flexDirection="column" gap={1}>
        {list.map(row => (
          <Box key={row.slug} flexDirection="row" alignItems="center" gap={2}>
            <Text color={dotColor(row)}>●</Text>
            <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
              <Text wrap="truncate-end">{name(row)}</Text>
              {doing(row) ? (
                <Text dimColor wrap="truncate-end">
                  {doing(row)}
                </Text>
              ) : null}
            </Box>
            <Box flexShrink={1} minWidth={0}>
              <Svg
                source={barSvg(row, isBusy)}
                alt={`${name(row)}: ${stageLabel(row)}, ${pct(row)}% complete${doing(row) ? `, ${doing(row)}` : ''}`}
                width={BAR_WIDTH}
                height={BAR_HEIGHT}
              />
            </Box>
            <Box flexShrink={0}>
              <Text dimColor>{pct(row)}%</Text>
            </Box>
            <Button
              key={`dismiss-${row.slug}`}
              label="✕"
              plain
              dimColor
              onPress={() => update($, dismissed, slugs => [...slugs, row.slug])}
            />
          </Box>
        ))}
      </Box>
    )
  })
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
  const isComplete = row.activeIndex === -1
  const isWaiting = !isComplete && row.statuses[row.activeIndex] === 'waiting'
  // Motion only while Claude is working on a stage, never at a gate or once finished.
  const isAnimated = isWorking && !isComplete && !isWaiting

  const stage = isComplete ? 'Done' : row.labels[row.activeIndex]
  const count = isComplete ? `${total}/${total}` : `${row.activeIndex + 1}/${total}`
  const pillW = Math.round(stage.length * 7.4 + count.length * 6.6 + 30)
  const head = (row.doneCount / total) * W
  const pillX = Math.min(W - pillW, Math.max(0, head - pillW * 0.4))
  const fillEnd = isComplete ? W : pillX + pillW / 2

  const pillFill = isWaiting ? '#f2b04c' : '#8e86f8'
  const pillText = isWaiting ? '#2b1d05' : '#ffffff'
  const dots = isWaiting ? ['#f2b04c', '#f7cd86', '#8a7a62'] : ['#8e86f8', '#c4c0ff', '#6e6a8c']

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
