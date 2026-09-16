import type { DesignLogEntry } from '@/lib/parsers/designLog'
import { AgentChip } from '@/components/AgentChip'

/**
 * design_log.md as a drawing revision table: REV № · agent chip · description.
 * Chronological order, newest last (drawing convention).
 */
export function RevisionLog({ entries }: { entries: DesignLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <p
        className="rounded-md border border-dashed border-stroke-hairline px-3 py-2 text-sm text-ink-tertiary"
        data-testid="revision-log-empty"
      >
        No log entries yet — the orchestrator has not written design_log.md.
      </p>
    )
  }

  return (
    <div className="overflow-hidden rounded-md border border-stroke-object" data-testid="revision-log">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-stroke-strong">
            <th className="w-12 px-3 py-1.5 text-left text-2xs font-medium tracking-label text-ink-tertiary uppercase">
              Rev
            </th>
            <th className="w-40 px-3 py-1.5 text-left text-2xs font-medium tracking-label text-ink-tertiary uppercase">
              Agent
            </th>
            <th className="px-3 py-1.5 text-left text-2xs font-medium tracking-label text-ink-tertiary uppercase">
              Description
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.index}
              className="border-b border-stroke-hairline align-top last:border-0 hover:bg-wash-hover"
            >
              <td className="px-3 py-1.5 font-mono text-xs text-ink-tertiary tabular-nums">
                {String(entry.index + 1).padStart(3, '0')}
              </td>
              <td className="px-3 py-1.5">
                <AgentChip agent={entry.agent} />
              </td>
              <td className="px-3 py-1.5 whitespace-pre-line text-ink-secondary">{entry.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
