export type Activity = { text: string; at: number }

export type StageStatus = 'done' | 'active' | 'waiting' | 'todo'

export type PipelineRow = {
  slug: string
  ticket: string
  title: string
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

declare module 'claude-code' {
  interface PluginState {
    'dotnet-workflow-kit': { rows: PipelineRow[]; isHidden: boolean; dismissed: string[]; activity: Activity | null; goalsSet: Record<string, string[]> }
  }
}
