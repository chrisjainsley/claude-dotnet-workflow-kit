// The Aspire parts of the mod as the engine runs them, over a fake host: a refused command is
// denied before it runs, the scanner is asked only about commands that stop processes or start
// an AppHost, and what it reports reaches the band, the Sessions pane and the prompt. Who owns
// what, and what is refused, is scripts/aspire_sessions.py's, tested by test_aspire_sessions.py.
import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import type { AspireEntry } from '../types'

const PLUGIN = 'dotnet-workflow-kit'
const HOME = '/home/dev'
const WORK = '/work/wallet'
const PIPELINE = `${HOME}/.claude/dotnet-workflow-kit/pipeline`
const REGISTRY = `${HOME}/.claude/dotnet-workflow-kit/aspire`
const BRANCH = 'feat/391-wallet-top-up'

const entry = (pid: number, isMine: boolean, port: number): AspireEntry => ({
  pid,
  project: isMine ? 'Wallet.AppHost' : 'Payments.AppHost',
  projectDir: isMine ? `${WORK}/src/Wallet.AppHost` : '/work/payments/src/Payments.AppHost',
  root: isMine ? WORK : '/work/payments',
  repo: `${WORK}/.git`,
  branch: isMine ? BRANCH : 'feat/402-payment-retries',
  label: isMine ? '#391 Wallet top-up' : '#402 Payment retries',
  session: isMine ? 'me' : 'them',
  dashboard: `https://localhost:${port}`,
  ports: [port, port - 9900],
  launchPorts: [port],
  pids: [pid],
  firstSeen: 0,
  seenAt: 0,
  isMine,
  isStale: false,
})
const HOSTS = [entry(41872, true, 17001), entry(39104, false, 17002)]

type Scanner = { entries: AspireEntry[]; deny?: string }

// A machine with one checkout on BRANCH, its pipeline file, another session's AppHost in the
// registry, and a scanner that answers `scanner`.
function host(on: On, scanner: Scanner) {
  const files: Record<string, string> = {
    [`${WORK}/.git/HEAD`]: `ref: refs/heads/${BRANCH}\n`,
    [`${PIPELINE}/391.json`]: JSON.stringify({ ticket: '391', title: 'Wallet top-up', branch: BRANCH, stages: { start: { done: true } } }),
  }
  const dirs = new Set([`${WORK}/.git`, PIPELINE, REGISTRY])
  const runs: string[][] = []
  mock.clock(on, { now: 1_800_000_000_000 })
  // Each call on `$` is answered as its event's result, `{ value }`.
  on('env.get', (_, e) => ({ value: e.name === 'HOME' ? HOME : undefined }))
  on('session.cwd', () => ({ value: WORK }))
  on('session.id', () => ({ value: 'me' }))
  on('fs.exists', (_, e) => ({ value: dirs.has(e.path) || e.path in files }))
  on('fs.stat', (_, e) => ({
    value: { kind: dirs.has(e.path) ? 'dir' : 'file', size: 0, mtimeMs: 1_800_000_000_000, isLink: false },
  }))
  on('fs.read', (_, e) => {
    const text = files[e.path]
    if (text === undefined) throw new Error(`no file ${e.path}`)
    return { value: text }
  })
  const listing = (name: string) => [{ name, kind: 'file' as const, size: 1, mtimeMs: 1_800_000_000_000, isLink: false }]
  on('fs.list', (_, e) => ({ value: e.path === PIPELINE ? listing('391.json') : e.path === REGISTRY ? listing('39104.json') : [] }))
  on('fs.write', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('process.run', (_, e) => {
    runs.push([...e.argv])
    const isScanner = e.argv.some(arg => arg.endsWith('aspire_sessions.py'))
    const stdout = isScanner ? JSON.stringify(scanner) : ''
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('tool.call', () => ({ result: { stdout: 'ran', stderr: '', interrupted: false } }) as never)

  return runs
}

const scannerRuns = (runs: string[][]) => runs.filter(argv => argv.some(arg => arg.endsWith('aspire_sessions.py')))

test('a command the scanner refuses is denied before it runs', async ($, on) => {
  const runs = host(on, { entries: HOSTS, deny: 'Blocked by dotnet-workflow-kit: this would also stop AppHosts' })
  const result = await $.tool.call({ tool: 'Bash', command: 'pkill -f dotnet' })
  expect('deny' in result && result.deny).toContain('Blocked by dotnet-workflow-kit')
  const argv = scannerRuns(runs)[0] ?? []
  expect(argv.slice(2, 3)).toEqual(['check'])
  expect(argv[argv.indexOf('--command') + 1]).toBe('pkill -f dotnet')
  expect(argv[argv.indexOf('--session') + 1]).toBe('me')
})

test('a command that stops nothing and starts nothing never asks the scanner', async ($, on) => {
  const runs = host(on, { entries: HOSTS, deny: 'never' })
  const result = await $.tool.call({ tool: 'Bash', command: 'git status' })
  expect(result.isError).toBeUndefined()
  expect(scannerRuns(runs)).toEqual([])
})

test('what the scanner reports reaches the band, the Sessions pane and the prompt', async ($, on) => {
  host(on, { entries: HOSTS })
  on('prompt.compose', () => ({ sections: [{ id: 'base', text: 'base', scope: 'shared' as const }] }))
  on('classic.Stop', () => ({}))
  // A turn's end reads the pipeline file, so the band has this branch's row to draw.
  await $.classic.Stop({ stop_hook_active: false } as never)
  // A start is let through, and its check's entries are this session's view of the machine.
  const result = await $.tool.call({ tool: 'Bash', command: 'dotnet run --project src/Wallet.AppHost' })
  expect('deny' in result).toBe(false)

  const { sections } = await $.prompt.compose({ model: 'm', promptModel: 'm', surfaces: [], tools: [], outputStyle: null, traits: [] })
  const aspire = sections.at(-1)
  expect(aspire?.id).toBe('dotnet-workflow-kit:aspire')
  expect(aspire?.text).toContain('- Wallet.AppHost · pid 41872 · dashboard https://localhost:17001')
  expect(aspire?.text).toContain('Payments.AppHost · pid 39104 · dashboard https://localhost:17002 · ports 7102 17002 · #402 Payment retries')

  for (const surface of ['terminal', 'desktop'] as const) {
    const band = await $.ui.mount({
      plugin: PLUGIN,
      surface,
      component: 'AbovePrompt',
      props: { hasSurvey: false, isWorking: false, maxRows: 4, bodyColumns: 140, scroll: { offset: 0, bodyRows: 40 }, view: {} },
    })
    expect(await band.find({ type: 'Text', text: 'Aspire :17001' })).toBeDefined()
    await band.unmount()

    const pane = await $.ui.mount({
      plugin: PLUGIN,
      surface,
      component: 'Pane',
      requestId: 'sessions',
      props: { title: 'Sessions', isFocused: true } as never,
    })
    expect((await pane.findAll({ type: 'Link', text: 'Dashboard ↗' })).length).toBe(1)
    expect(await pane.find({ type: 'Text', text: 'APPHOSTS ON THIS MACHINE · 2' })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: ' · #402 Payment retries' })).toBeDefined()
    await pane.unmount()
  }
})
