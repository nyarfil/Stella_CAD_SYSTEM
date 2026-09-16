import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export type StatusTone = 'pass' | 'fail' | 'warn' | 'note' | 'neutral'
export type Presence = 'present' | 'pending' | 'absent'

/* Ink-stamp chips (system.md): status ink families for verdicts, never filled pills. */
const STAMP: Record<StatusTone, string> = {
  pass: 'border-pass-line bg-pass-fill text-pass-ink',
  fail: 'border-fail-line bg-fail-fill text-fail-ink',
  warn: 'border-warn-line bg-warn-fill text-warn-ink',
  note: 'border-note-line bg-note-fill text-note-ink',
  neutral: 'border-stroke-strong text-ink-secondary',
}

/* Presence tags: ink levels + hairline solid/dashed/dotted — no status color. */
const TAG: Record<Presence, string> = {
  present: 'border-solid border-stroke-strong text-ink-secondary',
  pending: 'border-dashed border-stroke-hairline text-ink-tertiary',
  absent: 'border-dotted border-stroke-hairline text-ink-faint',
}

interface StatusChipProps extends ComponentProps<'span'> {
  /** stamp = verdict/severity (status inks); tag = artifact presence (ink levels). */
  variant?: 'stamp' | 'tag'
  tone?: StatusTone
  presence?: Presence
}

export function StatusChip({
  variant = 'stamp',
  tone = 'neutral',
  presence = 'present',
  className,
  children,
  ...props
}: StatusChipProps) {
  return (
    <span
      data-state={variant === 'stamp' ? tone : presence}
      className={cn(
        'inline-flex w-fit items-center gap-1 rounded-sheet border px-1.5 py-px text-2xs font-medium tracking-label uppercase whitespace-nowrap',
        variant === 'stamp' ? STAMP[tone] : TAG[presence],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  )
}
