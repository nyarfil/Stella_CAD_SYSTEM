import { Link } from 'react-router-dom'
import type { LegendEntry } from '@/lib/parsers/renders'

/**
 * Color legend from color_legend.txt as chips: literal legend token bar on a
 * paper chip (tokens.css: bg-legend-* are fixed renderer inks — never themed).
 * Unknown color names fall back to the parsed exact rgb() stroke string.
 * Chips link to part sheets path-relatively so the route prefix stays slice A's.
 */

const LEGEND_BAR: Record<string, string> = {
  red: 'bg-legend-red',
  blue: 'bg-legend-blue',
  green: 'bg-legend-green',
  orange: 'bg-legend-orange',
  purple: 'bg-legend-purple',
  teal: 'bg-legend-teal',
  brown: 'bg-legend-brown',
  magenta: 'bg-legend-magenta',
}

/**
 * Resolve a legend token to a real part directory. The assembly legend names
 * placed INSTANCES (e.g. "hinge_block_R", "hinge_block_L"), but a part sheet
 * exists only for the part dir ("hinge_block"). Exact match wins; otherwise
 * strip one trailing "_<suffix>" instance tag and retry; null = no sheet.
 */
function resolvePart(name: string, known: Set<string>): string | null {
  if (known.has(name)) return name
  const base = name.replace(/_[^_]+$/, '')
  if (base !== name && known.has(base)) return base
  return null
}

export function LegendChips({
  legend,
  partNames = [],
}: {
  legend: LegendEntry[]
  partNames?: string[]
}) {
  if (legend.length === 0) {
    return (
      <p className="text-sm text-ink-tertiary" data-testid="legend-empty">
        No color legend yet — assembly renders pending.
      </p>
    )
  }
  const known = new Set(partNames)
  const chipClass =
    'flex items-center gap-2 rounded-sm border border-stroke-hairline bg-legend-paper px-2 py-1.5'
  return (
    <ul className="flex flex-col gap-1.5" data-testid="legend-table">
      {legend.map(({ part, color, rgb }) => {
        const barClass = LEGEND_BAR[color.toLowerCase()]
        const target = resolvePart(part, known)
        const inner = (
          <>
            <span
              aria-hidden
              className={`h-3.5 w-1.5 shrink-0 rounded-[1px] ${rgb ? '' : (barClass ?? '')}`}
              style={rgb ? { background: rgb } : undefined}
            />
            <span className="truncate font-mono text-xs text-sheet-ink">{part}</span>
            <span className="ml-auto text-2xs tracking-label uppercase text-sheet-ink-soft">
              {color}
            </span>
          </>
        )
        return (
          <li key={part}>
            {target ? (
              <Link
                relative="path"
                to={`../parts/${encodeURIComponent(target)}`}
                title={rgb ?? color}
                data-testid={`legend-entry-${part}`}
                className={`${chipClass} hover:border-stroke-strong focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none`}
              >
                {inner}
              </Link>
            ) : (
              <div title={rgb ?? color} data-testid={`legend-entry-${part}`} className={chipClass}>
                {inner}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
