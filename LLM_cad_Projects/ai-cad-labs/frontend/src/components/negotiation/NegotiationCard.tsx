import { Card, CardContent, CardHeader, CardTitle, CardAction } from '@/components/ui/card'
import type { Conflict } from '@/lib/parsers/conflicts'

/**
 * CONFLICT-NNN rendered as design-review minutes (brief §3 Assembly):
 * stamped OPEN/RESOLVED header, labeled minutes fields, Resolution as the
 * typographic payoff. Status is mirrored to data-state for the QA fleet.
 */

const STAMP: Record<Conflict['status'], string> = {
  open: 'border-fail-line bg-fail-fill text-fail-ink',
  resolved: 'border-pass-line bg-pass-fill text-pass-ink',
}

function MinutesField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-32 shrink-0 pt-px text-2xs tracking-label uppercase text-ink-tertiary">
        {label}
      </dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  )
}

export function NegotiationCard({ conflict }: { conflict: Conflict }) {
  const { id, status, parts, issue, proposal, recommendation, resolution } = conflict
  return (
    <Card data-testid={`negotiation-card-${id}`} data-state={status}>
      <CardHeader className="border-b border-stroke-hairline [.border-b]:pb-3">
        <CardTitle className="font-mono text-sm tracking-wide">{id}</CardTitle>
        <CardAction>
          <span
            data-testid={`negotiation-status-${id}`}
            data-state={status}
            className={`inline-block rounded-sm border px-2 py-0.5 text-2xs font-medium tracking-label uppercase ${STAMP[status]}`}
          >
            {status === 'resolved' ? 'Resolved' : 'Open'}
          </span>
        </CardAction>
      </CardHeader>
      <CardContent>
        <dl className="flex flex-col gap-3">
          {parts.length > 0 && (
            <MinutesField label="Parts">
              <div className="flex flex-wrap gap-1.5">
                {parts.map((part) => (
                  <span
                    key={part}
                    className="rounded-sm bg-secondary px-1.5 py-0.5 font-mono text-xs text-secondary-foreground"
                  >
                    {part}
                  </span>
                ))}
              </div>
            </MinutesField>
          )}
          {issue && (
            <MinutesField label="Issue">
              <p className="text-sm leading-6 text-ink-secondary">{issue}</p>
            </MinutesField>
          )}
          {proposal && (
            <MinutesField label="Proposal">
              <p className="text-sm leading-6 text-ink-secondary">{proposal}</p>
            </MinutesField>
          )}
          {recommendation && (
            <MinutesField label="Recommendation">
              <p className="text-sm leading-6 text-foreground">{recommendation}</p>
            </MinutesField>
          )}
        </dl>
        {resolution && (
          <div
            data-testid={`negotiation-resolution-${id}`}
            className="mt-4 rounded-sm border-l-2 border-pass-line bg-pass-fill px-3 py-2.5"
          >
            <div className="text-2xs tracking-label uppercase text-pass-ink">Resolution</div>
            <p className="mt-1 text-sm leading-6 font-medium text-foreground">{resolution}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
