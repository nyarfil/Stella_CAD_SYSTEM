import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

type SheetView = 'top' | 'front' | 'right' | 'iso'
type SheetStyle = 'clean' | 'wireframe'
type Projection = 'third' | 'first'

const VIEW_LABEL: Record<SheetView, string> = {
  top: 'TOP',
  front: 'FRONT',
  right: 'RIGHT',
  iso: 'ISO',
}

/* Quadrant order, row-major. Third-angle: TOP|ISO over FRONT|RIGHT; first-angle swaps the rows. */
const LAYOUT: Record<Projection, SheetView[]> = {
  third: ['top', 'iso', 'front', 'right'],
  first: ['front', 'right', 'top', 'iso'],
}

const STYLES: { value: SheetStyle; label: string }[] = [
  { value: 'clean', label: 'clean' },
  { value: 'wireframe', label: 'wireframe' },
]
const PROJECTIONS: { value: Projection; label: string }[] = [
  { value: 'third', label: 'third-angle' },
  { value: 'first', label: 'first-angle' },
]

interface RenderSheetProps {
  project: string
  part: string
  className?: string
}

/**
 * Orthographic render sheet: 2×2 paper grid of part renders with style and
 * projection toggles. Renders live at
 * /projects-fs/<project>/assembly/<part>/renders/<view>_<style>.png;
 * a 404 turns that quadrant into a labeled empty cell.
 */
export function RenderSheet({ project, part, className }: RenderSheetProps) {
  const [style, setStyle] = useState<SheetStyle>('clean')
  const [projection, setProjection] = useState<Projection>('third')
  const [failed, setFailed] = useState<ReadonlySet<string>>(() => new Set())
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null)
  const openerRef = useRef<HTMLElement | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  const base = `/projects-fs/${encodeURIComponent(project)}/assembly/${encodeURIComponent(part)}/renders`
  const urlFor = (view: SheetView, s: SheetStyle = style) => `${base}/${view}_${s}.png`

  /* Lightbox traverses all 8 tiles (4 views × 2 styles) in sheet order — brief §3. */
  const tiles: { view: SheetView; style: SheetStyle }[] = STYLES.flatMap((s) =>
    LAYOUT[projection].map((view) => ({ view, style: s.value })),
  )
  const open = lightboxIdx !== null ? tiles[lightboxIdx] : null

  useEffect(() => {
    if (lightboxIdx === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setLightboxIdx(null)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        setLightboxIdx((i) => (i === null ? null : (i + 1) % tiles.length))
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setLightboxIdx((i) => (i === null ? null : (i + tiles.length - 1) % tiles.length))
      } else if (e.key === 'Tab') {
        // Trap focus within the dialog — the dialog container is the only focusable element
        e.preventDefault()
        dialogRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lightboxIdx, tiles.length])

  // Focus the dialog on open; return focus to the opener quadrant on close.
  // The opener is captured in the quadrant onClick (NOT here): capturing it in
  // this effect would overwrite it with the dialog on every arrow-nav idx
  // change, so focus could never return to the sheet.
  useEffect(() => {
    if (lightboxIdx !== null) {
      dialogRef.current?.focus()
    } else if (openerRef.current) {
      openerRef.current.focus()
      openerRef.current = null
    }
  }, [lightboxIdx])

  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-2xs uppercase tracking-label text-ink-tertiary">
          {projection === 'third' ? 'third-angle projection' : 'first-angle projection'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Segmented options={STYLES} value={style} onChange={setStyle} />
          <Segmented options={PROJECTIONS} value={projection} onChange={setProjection} />
        </div>
      </div>

      <div className="border border-sheet-frame bg-sheet shadow-sheet">
        <div className="grid grid-cols-2">
          {LAYOUT[projection].map((view, i) => {
            const url = urlFor(view)
            const missing = failed.has(url)
            return (
              <figure
                key={view}
                className={cn(
                  'flex flex-col',
                  i % 2 === 0 && 'border-r border-sheet-rule',
                  i < 2 && 'border-b border-sheet-rule',
                )}
              >
                {missing ? (
                  <div className="flex aspect-[4/3] items-center justify-center">
                    <span className="font-mono text-2xs uppercase tracking-label text-sheet-ink-soft opacity-70">
                      no render
                    </span>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => {
                      openerRef.current = e.currentTarget
                      setLightboxIdx(tiles.findIndex((t) => t.view === view && t.style === style))
                    }}
                    className="aspect-[4/3] cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset"
                    title={`${VIEW_LABEL[view]} — open full size`}
                  >
                    <img
                      src={url}
                      alt={`${part} — ${VIEW_LABEL[view]} (${style})`}
                      loading="lazy"
                      className="h-full w-full object-contain p-2"
                      onError={() =>
                        setFailed((prev) => {
                          const next = new Set(prev)
                          next.add(url)
                          return next
                        })
                      }
                    />
                  </button>
                )}
                <figcaption className="border-t border-sheet-rule py-1 text-center font-mono text-2xs uppercase tracking-label text-sheet-ink-soft">
                  {VIEW_LABEL[view]}
                </figcaption>
              </figure>
            )
          })}
        </div>
      </div>

      {open && (
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-label={`${part} render — ${VIEW_LABEL[open.view]} ${open.style}, ${(lightboxIdx ?? 0) + 1} of ${tiles.length}`}
          tabIndex={-1}
          className="fixed inset-0 z-50 flex cursor-zoom-out flex-col items-center justify-center gap-3 bg-black/80 p-8 focus-visible:outline-none"
          onClick={() => setLightboxIdx(null)}
          data-testid="render-lightbox"
        >
          <img
            src={urlFor(open.view, open.style)}
            alt={`${part} — ${VIEW_LABEL[open.view]} (${open.style})`}
            className="max-h-[85vh] max-w-full bg-sheet shadow-float"
            onClick={(e) => e.stopPropagation()}
          />
          <div
            className="flex flex-wrap items-center justify-center gap-4 font-mono text-2xs uppercase tracking-label text-white/70"
            onClick={(e) => e.stopPropagation()}
          >
            <span>
              {VIEW_LABEL[open.view]} · {open.style}
            </span>
            <span aria-hidden>← / → traverse · esc close</span>
            <span className="tabular-nums" data-testid="lightbox-counter">
              {(lightboxIdx ?? 0) + 1}/{tiles.length}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div role="group" className="flex overflow-hidden rounded-sm border border-stroke-object">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            'px-2 py-0.5 font-mono text-2xs uppercase tracking-label transition-colors',
            o.value === value
              ? 'bg-surface-inset text-foreground'
              : 'text-ink-tertiary hover:text-ink-secondary',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
