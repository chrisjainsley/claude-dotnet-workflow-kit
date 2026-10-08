// The stage tool and the subagent bookkeeping in hooks/register.tsx, run against the engine by
// `claude plugin test .`. The files, the repository and the clock are all in memory.
import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const HOME = 'C:/home'
const REPO = 'C:/repo'
const DIR = `${HOME}/.claude/dotnet-workflow-kit/pipeline`
const TOOL = 'mcp__dotnet-workflow-kit__stage'

type Files = Map<string, string>

// A repository checked out on `branch`, and the files it starts with.
function world(on: On, branch: string, start: Record<string, string> = {}): Files {
  const files: Files = new Map(Object.entries({ [`${REPO}/.git/HEAD`]: `ref: refs/heads/${branch}\n`, ...start }))
  const isDir = (path: string) => [...files.keys()].some(f => f.startsWith(`${path}/`))
  // The engine hands paths over in the platform's own form; the files here are keyed with slashes.
  const at = (e: { path: string }) => e.path.replace(/\\/g, '/')
  mock.clock(on, { now: Date.parse('2026-10-08T12:00:00Z') })
  mock.env(on, { USERPROFILE: HOME })
  on('session.cwd', async () => ({ value: REPO }))
  on('fs.exists', async ($, e) => ({ value: files.has(at(e)) || isDir(at(e)) }))
  on('fs.read', async ($, e) => {
    const text = files.get(at(e))
    if (text === undefined) throw new Error(`no such file: ${e.path}`)

    return { value: text }
  })
  on('fs.write', async ($, e) => {
    files.set(at(e), e.text)

    return { value: undefined }
  })
  on('fs.stat', async ($, e) => ({ value: { kind: isDir(at(e)) ? 'dir' : 'file', size: 0, mtimeMs: 0, isLink: false } }) as never)
  on('fs.list', async ($, e) => ({
    value: [...files.keys()]
      .filter(f => f.startsWith(`${at(e)}/`) && !f.slice(at(e).length + 1).includes('/'))
      .map(f => ({ name: f.slice(at(e).length + 1), kind: 'file', size: 0, mtimeMs: Date.parse('2026-10-08T11:00:00Z'), isLink: false })),
  }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  on('ui.toast', async () => ({ value: undefined }) as never)
  on('tool.call', async () => ({ result: 'done' }) as never)
  on('ui.render', async () => ({ type: 'Box', props: {}, children: [] }) as never)

  return files
}

const json = (files: Files, name: string) => JSON.parse(files.get(`${DIR}/${name}`) ?? 'null')
const stage = ($: unknown, input: object) =>
  ($ as { tool: { call: (e: object) => Promise<{ result: string }> } }).tool.call({ tool: TOOL, ...input })

test('a stage merges into the adopted file and drops adopted', async ($, on) => {
  const files = world(on, 'feat/12-add-thing', {
    [`${DIR}/feat-12-add-thing.json`]: JSON.stringify({
      adopted: true,
      branch: 'feat/12-add-thing',
      stages: { start: { done: true, at: '2026-10-08T10:00:00Z' } },
    }),
  })
  const { result } = await stage($, { stage: 'plan', fields: { artifactUrl: 'https://x', done: false } })

  const data = json(files, 'feat-12-add-thing.json')
  expect(data.adopted).toBeUndefined()
  expect(data.stages.plan).toEqual({ artifactUrl: 'https://x', done: false })
  expect(data.stages.start.done).toBe(true)
  expect(result).toMatch(/Plan 2\/6/)
})

test('with no file for the branch, the ticket keys a new one and done gets an at', async ($, on) => {
  const files = world(on, 'feat/12-add-thing')
  await stage($, { stage: 'start', fields: { done: true }, item: { ticket: '12', title: 'Add thing', shortTitle: 'Add thing' } })

  const data = json(files, '12.json')
  expect(data.branch).toBe('feat/12-add-thing')
  expect(data.title).toBe('Add thing')
  expect(data.stages.start).toEqual({ done: true, at: '2026-10-08T12:00:00Z' })
})

test('with no file and no ticket, the branch keys the new file', async ($, on) => {
  const files = world(on, 'claude/tidy-up')
  await stage($, { current: { stage: 'plan', detail: 'Planning' } })

  expect(json(files, 'claude-tidy-up.json').current).toEqual({ stage: 'plan', detail: 'Planning' })
})

test('the base branch is refused and nothing is written', async ($, on) => {
  const files = world(on, 'main')
  const { result } = await stage($, { stage: 'start', fields: { done: true } })

  expect(result).toMatch(/base branch main/)
  expect([...files.keys()].some(f => f.startsWith(DIR))).toBe(false)
})

test("a subagent's tool calls leave the activity, and the band counts it", async ($, on) => {
  world(on, 'feat/12-add-thing', {
    [`${DIR}/12.json`]: JSON.stringify({ branch: 'feat/12-add-thing', stages: { start: { done: true } } }),
  })
  on('agent.spawn', async () => ({ model: 'claude-haiku-4-5', agentId: 'a1' }) as never)
  on('turn.complete', async () => ({ text: '' }) as never)
  const engine = $ as never as {
    tool: { call: (e: object) => Promise<unknown> }
    agent: { spawn: (e: object) => Promise<unknown> }
    turn: { complete: (e: object) => Promise<unknown> }
    ui: { mount: (e: object) => Promise<{ find: (q: object) => Promise<{ text: string } | undefined>; unmount: () => Promise<void> }> }
  }
  const band = async () => {
    const ui = await engine.ui.mount({
      plugin: 'dotnet-workflow-kit',
      surface: 'desktop',
      component: 'AbovePrompt',
      props: { isWorking: true, hasSurvey: false, bodyColumns: 160 },
    })
    const found = await ui.find({ type: 'Text', text: /Agent: / })
    await ui.unmount()

    return found?.text
  }

  await engine.tool.call({ tool: 'Agent', description: 'Bug-hunt review', prompt: 'p', subagent_type: 'Explore' })
  await engine.agent.spawn({ tool_use_id: 't1', prompt: 'p', description: 'Bug-hunt review', subagentType: 'Explore' })
  await engine.tool.call({ tool: 'Read', file_path: `${REPO}/Order.cs`, agentId: 'a1' })
  expect(await band()).toBe('Agent: Bug-hunt review · 1 agent running')

  await engine.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 'x', agentId: 'a1', reason: 'answer' })
  expect(await band()).toBe('Agent: Bug-hunt review')
})

test("another repository's or a closed item's file for the branch is left alone", async ($, on) => {
  const other = JSON.stringify({ branch: 'feat/12-add-thing', repo: 'C:/elsewhere/.git', stages: { start: { done: true } } })
  const closed = JSON.stringify({ branch: 'feat/12-add-thing', closed: { reason: 'merged', at: '2026-10-01T00:00:00Z' }, stages: {} })
  const files = world(on, 'feat/12-add-thing', { [`${DIR}/feat-12-add-thing.json`]: other, [`${DIR}/old.json`]: closed })
  await stage($, { stage: 'start', fields: { done: true } })

  expect(files.get(`${DIR}/feat-12-add-thing.json`)).toBe(other)
  expect(files.get(`${DIR}/old.json`)).toBe(closed)
  expect(json(files, 'feat-12-add-thing-2.json').stages.start.done).toBe(true)
})

test('two stage calls at once both land', async ($, on) => {
  const files = world(on, 'feat/12-add-thing')
  await Promise.all([
    stage($, { stage: 'plan', fields: { artifactUrl: 'https://x' } }),
    stage($, { current: { detail: 'Planning' } }),
  ])

  const data = json(files, 'feat-12-add-thing.json')
  expect(data.stages.plan.artifactUrl).toBe('https://x')
  expect(data.current.detail).toBe('Planning')
})

test("in a worktree, the item's file is found by the main repository's git dir", async ($, on) => {
  const files = world(on, 'feat/12-add-thing', {
    [`${DIR}/12.json`]: JSON.stringify({ branch: 'feat/12-add-thing', repo: 'C:/main/.git', stages: { start: { done: true } } }),
  })
  files.delete(`${REPO}/.git/HEAD`)
  files.set(`${REPO}/.git`, 'gitdir: C:/main/.git/worktrees/wt\n')
  files.set('C:/main/.git/worktrees/wt/HEAD', 'ref: refs/heads/feat/12-add-thing\n')
  files.set('C:/main/.git/worktrees/wt/commondir', '../..\n')
  await stage($, { stage: 'plan', fields: { done: false } })

  expect(json(files, '12.json').stages.plan).toEqual({ done: false })
  expect([...files.keys()].filter(f => f.startsWith(DIR))).toEqual([`${DIR}/12.json`])
})
