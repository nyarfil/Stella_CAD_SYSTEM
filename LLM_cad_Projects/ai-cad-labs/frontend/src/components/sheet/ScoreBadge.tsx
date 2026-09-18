import { cn } from '@/lib/utils'
import type { DfmaCounts } from '@/lib/parsers/dfma'

interface ScoreBadgeProps {
  counts: DfmaCounts
  className?: string
}

/** passed/evaluated tally for a DFMA report, inked by worst outstanding outcome. */
export function ScoreBadge({ counts, className }: ScoreBadgeProps) {
  const tone =
    counts.failed > 0 ? 'text-fail-ink' : counts.uncertain > 0 ? 'text-warn-ink' : 'text-pass-ink'
  return (
    <span className={cn('font-mono text-xs tabular-nums text-ink-secondary', className)}>
      <span className={cn('font-semibold', tone)}>{counts.passed}</span>/{counts.evaluated} passed
      {counts.uncertain > 0 && <span className="text-warn-ink"> · {counts.uncertain} uncertain</span>}
    </span>
  )
}
