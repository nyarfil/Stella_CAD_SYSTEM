import { Link } from 'react-router-dom'

/**
 * Not-found panel in the drafting-instrument register (QA §5 item 9) — a calm,
 * styled empty state instead of a bare sentence. Reused for missing parts,
 * missing projects, and unmatched routes.
 */
export function NotFound({
  title,
  detail,
  home = '/',
  homeLabel = 'project register',
  testid = 'not-found',
}: {
  title: string
  detail?: string
  home?: string
  homeLabel?: string
  testid?: string
}) {
  return (
    <div className="flex h-full items-center justify-center p-8" data-testid={testid}>
      <div className="max-w-md rounded-md border border-dashed border-stroke-strong bg-card p-6 text-center">
        <p className="font-mono text-2xs uppercase tracking-label text-ink-tertiary">not found</p>
        <h1 className="mt-2 text-lg font-semibold text-foreground">{title}</h1>
        {detail && <p className="mt-1 text-sm text-ink-secondary">{detail}</p>}
        <Link
          to={home}
          className="mt-4 inline-block rounded-sm border border-stroke-object px-3 py-1 font-mono text-2xs uppercase tracking-label text-ink-secondary transition-colors hover:border-stroke-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          → {homeLabel}
        </Link>
      </div>
    </div>
  )
}
