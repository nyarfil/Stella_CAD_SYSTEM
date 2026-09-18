import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface TitleBlockField {
  label: string
  value: ReactNode
}

/**
 * The ONE title block per sheet: a heavy-framed strip of
 * labeled cells — title, data fields, verdict stamps, actions.
 */
export function TitleBlock({
  eyebrow = 'PROJECT',
  title,
  fields = [],
  stamps,
  actions,
  className,
}: {
  eyebrow?: string
  title: string
  fields?: TitleBlockField[]
  stamps?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div
      data-testid="title-block"
      className={cn(
        'flex flex-wrap items-stretch divide-x divide-stroke-hairline rounded-sheet border-2 border-stroke-heavy bg-card',
        className,
      )}
    >
      <div className="min-w-0 flex-1 basis-56 px-4 py-3">
        <span className="block text-2xs tracking-label text-ink-tertiary uppercase">{eyebrow}</span>
        <h2 className="truncate font-mono text-lg font-semibold" title={title}>
          {title}
        </h2>
      </div>
      {fields.map((field) => (
        <div key={field.label} className="px-4 py-3">
          <span className="block text-2xs tracking-label text-ink-tertiary uppercase">{field.label}</span>
          <span className="font-mono text-sm text-ink-secondary tabular-nums">{field.value}</span>
        </div>
      ))}
      {stamps ? <div className="flex flex-wrap items-center gap-1.5 px-4 py-3">{stamps}</div> : null}
      {actions ? <div className="ml-auto flex items-center px-3 py-3">{actions}</div> : null}
    </div>
  )
}
