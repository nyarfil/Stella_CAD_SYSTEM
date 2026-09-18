import { useState } from 'react'
import type { RenderSet, RenderStyle, RenderView } from '@/lib/parsers/renders'

/**
 * Colored-assembly drawing sheet — the RenderSheet 2×2 paradigm applied to
 * assembly renders (slice B owns the part-sheet original; this stays local to
 * slice C per the concurrent-build boundary). Third-angle adjacency per brief
 * §3: TOP above FRONT, RIGHT beside FRONT, ISO in the spare corner. Missing
 * renders keep the sheet frame with AWAITING RENDER quadrants.
 */

const QUADRANTS: { view: RenderView; cell: string }[] = [
  { view: 'top', cell: 'border-b border-r border-sheet-rule' },
  { view: 'iso', cell: 'border-b border-sheet-rule' },
  { view: 'front', cell: 'border-r border-sheet-rule' },
  { view: 'right', cell: '' },
]

const STYLES: RenderStyle[] = ['clean', 'wireframe']

export function AssemblySheet({ project, renders }: { project: string; renders: RenderSet }) {
  const [style, setStyle] = useState<RenderStyle>('clean')
  const byView = new Map(renders.filter((r) => r.style === style).map((r) => [r.view, r]))

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div role="group" aria-label="View style" className="flex gap-1 self-end">
        {STYLES.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={style === s}
            data-state={style === s ? 'selected' : 'idle'}
            data-testid={`style-toggle-${s}`}
            disabled={renders.length === 0}
            onClick={() => setStyle(s)}
            className={`rounded-sm border px-2.5 py-1 text-2xs tracking-label uppercase transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50 ${
              style === s
                ? 'border-stroke-strong bg-secondary text-foreground'
                : 'border-stroke-object text-ink-tertiary hover:bg-wash-hover hover:text-foreground'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      <div
        data-testid="assembly-sheet"
        data-state={renders.length > 0 ? 'rendered' : 'pending'}
        className="overflow-hidden rounded-sheet border border-sheet-frame bg-sheet shadow-sheet"
      >
        <div className="flex items-baseline justify-between gap-3 border-b border-sheet-frame px-4 py-2">
          <div className="flex items-baseline gap-2">
            <span className="text-2xs tracking-label uppercase text-sheet-ink-soft">Assembly</span>
            <span className="font-mono text-xs text-sheet-ink">{project}</span>
          </div>
          <span className="text-2xs tracking-label uppercase text-sheet-ink-soft">
            {style} · colored · 4 views
          </span>
        </div>
        <div className="grid grid-cols-2">
          {QUADRANTS.map(({ view, cell }) => {
            const render = byView.get(view)
            return (
              <figure key={view} className={`relative m-0 aspect-[4/3] ${cell}`}>
                <figcaption className="absolute top-2 left-3 z-10 text-2xs tracking-label uppercase text-sheet-ink-soft">
                  {view}
                </figcaption>
                {render ? (
                  <img
                    src={render.url}
                    alt={`Assembly ${view} view, ${style}, colored per legend`}
                    loading="lazy"
                    draggable={false}
                    className="absolute inset-0 h-full w-full object-contain p-3"
                  />
                ) : (
                  <div
                    data-testid={`empty-quadrant-${view}`}
                    className="absolute inset-3 flex items-center justify-center rounded-sm border border-dashed border-sheet-rule"
                  >
                    <span className="text-2xs tracking-label uppercase text-sheet-ink-soft">
                      awaiting render
                    </span>
                  </div>
                )}
              </figure>
            )
          })}
        </div>
      </div>
    </div>
  )
}
