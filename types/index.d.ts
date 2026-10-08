export type Activity = { text: string; at: number }

export type RunningAgent = { id: string; description: string; at: number }

export type StageStatus = 'done' | 'active' | 'waiting' | 'todo'

export type PipelineRow = {
  slug: string
  ticket: string
  title: string
  branch: string
  isCurrentBranch: boolean
  labels: string[]
  isPlanApproved: boolean
  isReviewApproved: boolean
  isBlocked: boolean
  statuses: StageStatus[]
  doneCount: number
  activeIndex: number
  detail: string
}

// One running Aspire AppHost, as scripts/aspire_sessions.py reads the registry: the session
// that owns it, the worktree it runs from, the processes it started and the ports they hold.
export type AspireEntry = {
  pid: number
  project: string
  projectDir: string
  root: string
  repo: string
  branch: string
  label: string
  session: string
  dashboard: string
  ports: number[]
  launchPorts: number[]
  pids: number[]
  firstSeen: number
  seenAt: number
  isMine: boolean
  isStale: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'dotnet-workflow-kit': { rows: PipelineRow[]; isHidden: boolean; dismissed: string[]; activity: Activity | null; background: string[]; goalsSet: Record<string, string[]>; notifyOthers: boolean; aspire: AspireEntry[]; agents: RunningAgent[] }
  }
}
