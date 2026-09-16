import { cn } from '@/lib/utils'

type StampTone = 'pass' | 'fail' | 'neutral'

/* Verdict → status ink (system.md): PASSED=pass, FAILED=fail, PENDING=neutral. */
function toneFor(verdict: string | null | undefined): StampTone {
  const v = (verdict ?? '').toLowerCase()
  if (v.includes('pass')) return 'pass'
  if (v.includes('fail')) return 'fail'
  return 'neutral'
}

const INK: Record<StampTone, string> = {
  pass: 'border-pass-line bg-pass-fill text-pass-ink',
  fail: 'border-fail-line bg-fail-fill text-fail-ink',
  neutral: 'border-stroke-strong text-ink-secondary',
}

interface VerdictStampProps {
  verdict: string | null | undefined
  className?: string
}

/** Ink-stamp verdict block — heavier sibling of StatusChip for panel headers. */
export function VerdictStamp({ verdict, className }: VerdictStampProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center border-2 px-2 py-0.5 font-mono text-2xs font-semibold uppercase tracking-label',
        INK[toneFor(verdict)],
        className,
      )}
    >
      {verdict ? verdict.toUpperCase() : 'PENDING'}
    </span>
  )
}
