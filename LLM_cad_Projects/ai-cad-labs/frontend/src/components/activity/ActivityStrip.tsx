import { useEffect, useMemo, useRef, useState } from 'react'
import { AgentChip } from '@/components/AgentChip'
import { cn } from '@/lib/utils'

/**
 * Live agent-activity waterfall.
 * Polls /api/activity/:project (4s, only while the run is live) and renders
 * agent lanes × time as a Gantt: approx spans dashed (drafting honesty),
 * point events as dots, pulsing "now" marker on the active lane. When the
 * run ends the strip freezes into a static run-summary waterfall. Fetch
 * failure with no data degrades to a quiet "activity unavailable" note.
 */

/* ── /api/activity/:project contract (mirrors plugins/projects-api.ts) ──── */

interface ActivityEvent {
  seq: number
  ts: string | null
  agent: string
  part: string | null
  kind: 'attempt' | 'artifact' | 'log'
  label: string
  outcome: 'success' | 'failed' | null
}

interface ActivitySpan {
  startTs: string | null
  endTs: string
  part: string | null
  approx: boolean
  label: string
}

interface ActivityLane {
  agent: string
  spans: ActivitySpan[]
}

interface ActivityData {
  generatedAt: string
  isActive: boolean
  activeAgent: string | null
  events: ActivityEvent[]
  lanes: ActivityLane[]
}

/* ── agent hues (literal class names so Tailwind sees them; AgentChip idiom) ── */

interface Hue {
  dot: string
  line: string
  tintStrong: string
  tintFaint: string
}

const AGENT_HUE: Record<string, Hue> = {
  orchestrator: {
    dot: 'bg-agent-orchestrator',
    line: 'border-agent-orchestrator',
    tintStrong: 'bg-agent-orchestrator/25',
    tintFaint: 'bg-agent-orchestrator/10',
  },
  planner: {
    dot: 'bg-agent-planner',
    line: 'border-agent-planner',
    tintStrong: 'bg-agent-planner/25',
    tintFaint: 'bg-agent-planner/10',
  },
  'cad-designer': {
    dot: 'bg-agent-cad-designer',
    line: 'border-agent-cad-designer',
    tintStrong: 'bg-agent-cad-designer/25',
    tintFaint: 'bg-agent-cad-designer/10',
  },
  validator: {
    dot: 'bg-agent-validator',
    line: 'border-agent-validator',
    tintStrong: 'bg-agent-validator/25',
    tintFaint: 'bg-agent-validator/10',
  },
  repair: {
    dot: 'bg-agent-repair',
    line: 'border-agent-repair',
    tintStrong: 'bg-agent-repair/25',
    tintFaint: 'bg-agent-repair/10',
  },
  'assembly-resolver': {
    dot: 'bg-agent-assembly-resolver',
    line: 'border-agent-assembly-resolver',
    tintStrong: 'bg-agent-assembly-resolver/25',
    tintFaint: 'bg-agent-assembly-resolver/10',
  },
  sourcing: {
    dot: 'bg-agent-sourcing',
    line: 'border-agent-sourcing',
    tintStrong: 'bg-agent-sourcing/25',
    tintFaint: 'bg-agent-sourcing/10',
  },
  reviewer: {
    dot: 'bg-agent-reviewer',
    line: 'border-agent-reviewer',
    tintStrong: 'bg-agent-reviewer/25',
    tintFaint: 'bg-agent-reviewer/10',
  },
  'dfma-inspector': {
    dot: 'bg-agent-dfma-inspector',
    line: 'border-agent-dfma-inspector',
    tintStrong: 'bg-agent-dfma-inspector/25',
    tintFaint: 'bg-agent-dfma-inspector/10',
  },
}

const NEUTRAL_HUE: Hue = {
  dot: 'bg-ink-faint',
  line: 'border-ink-faint',
  tintStrong: 'bg-ink-faint/25',
  tintFaint: 'bg-ink-faint/10',
}

const normalizeRole = (agent: string) => agent.trim().toLowerCase().replace(/_/g, '-')

/* ── layout: lanes × time (or ordinal fallback when timestamps are unusable) ── */

interface PlacedSpan {
  key: string
  leftPct: number
  widthPct: number
  approx: boolean
  title: string
}

interface PlacedDot {
  seq: number
  leftPct: number
  /** false = position interpolated from seq, not a real timestamp — drawn hollow. */
  anchored: boolean
  failed: boolean
  title: string
}

interface PlacedLane {
  agent: string
  roleKey: string
  spans: PlacedSpan[]
  dots: PlacedDot[]
}

interface Layout {
  lanes: PlacedLane[]
  axis: { kind: 'time'; start: string; end: string } | { kind: 'ordinal' }
}

const MIN_SPAN_PCT = 0.75

function parseTs(iso: string | null): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}

function fmtTime(t: number): string {
  return new Date(t).toLocaleTimeString(undefined, { hour12: false })
}

function dotTitle(ev: ActivityEvent): string {
  return `#${ev.seq} ${ev.agent} ${ev.kind}: ${ev.label}${ev.outcome ? ` — ${ev.outcome}` : ''}`
}

function buildLayout(data: ActivityData): Layout {
  const stamps: number[] = []
  for (const lane of data.lanes) {
    for (const span of lane.spans) {
      const end = parseTs(span.endTs)
      if (end !== null) stamps.push(end)
      const start = parseTs(span.startTs)
      if (start !== null) stamps.push(start)
    }
  }
  for (const ev of data.events) {
    const t = parseTs(ev.ts)
    if (t !== null) stamps.push(t)
  }
  const min = Math.min(...stamps)
  const max = Math.max(...stamps)
  const timeMode = stamps.length >= 2 && max > min

  // Lane skeleton: server lane order first, then roles seen only in events.
  const lanes: PlacedLane[] = data.lanes.map((l) => ({
    agent: l.agent,
    roleKey: normalizeRole(l.agent),
    spans: [],
    dots: [],
  }))
  const byKey = new Map(lanes.map((l) => [l.roleKey, l]))
  const events = [...data.events].sort((a, b) => a.seq - b.seq)
  for (const ev of events) {
    const key = normalizeRole(ev.agent)
    if (!byKey.has(key)) {
      const lane: PlacedLane = { agent: ev.agent, roleKey: key, spans: [], dots: [] }
      byKey.set(key, lane)
      lanes.push(lane)
    }
  }
  const maxSeq = Math.max(1, ...events.map((e) => e.seq))
  const clampDot = (pct: number) => Math.max(1, Math.min(99, pct))

  if (timeMode) {
    const width = max - min
    const pct = (t: number) => ((t - min) / width) * 100

    data.lanes.forEach((lane, li) => {
      const placed = byKey.get(normalizeRole(lane.agent))
      if (!placed) return
      lane.spans.forEach((span, si) => {
        const end = parseTs(span.endTs)
        if (end === null) return
        const start = parseTs(span.startTs)
        const endPct = pct(end)
        let left = start !== null ? pct(Math.min(start, end)) : endPct - MIN_SPAN_PCT
        const w = Math.max(endPct - left, MIN_SPAN_PCT)
        left = Math.max(0, Math.min(left, 100 - w))
        placed.spans.push({
          key: `${li}-${si}`,
          leftPct: left,
          widthPct: w,
          approx: span.approx,
          title: `${lane.agent} — ${span.label}${span.part ? ` · ${span.part}` : ''}${span.approx ? ' (approx)' : ''}`,
        })
      })
    })

    // Null-ts events (design_log lines) interpolate between seq-neighbouring
    // anchored events so the whole conversation stays visible — drawn hollow.
    const anchors = events
      .map((ev) => ({ seq: ev.seq, t: parseTs(ev.ts) }))
      .filter((a): a is { seq: number; t: number } => a.t !== null)
    const timeFor = (ev: ActivityEvent): { t: number; anchored: boolean } => {
      const own = parseTs(ev.ts)
      if (own !== null) return { t: own, anchored: true }
      let prev: { seq: number; t: number } | null = null
      let next: { seq: number; t: number } | null = null
      for (const a of anchors) {
        if (a.seq <= ev.seq) prev = a
        else {
          next = a
          break
        }
      }
      if (prev && next && next.seq !== prev.seq) {
        return {
          t: prev.t + ((next.t - prev.t) * (ev.seq - prev.seq)) / (next.seq - prev.seq),
          anchored: false,
        }
      }
      if (prev) return { t: prev.t, anchored: false }
      if (next) return { t: next.t, anchored: false }
      return { t: min + (width * ev.seq) / maxSeq, anchored: false }
    }
    for (const ev of events) {
      const lane = byKey.get(normalizeRole(ev.agent))
      if (!lane) continue
      const { t, anchored } = timeFor(ev)
      lane.dots.push({
        seq: ev.seq,
        leftPct: clampDot(pct(t)),
        anchored,
        failed: ev.outcome === 'failed',
        title: dotTitle(ev),
      })
    }
    return { lanes, axis: { kind: 'time', start: fmtTime(min), end: fmtTime(max) } }
  }

  // Ordinal fallback: sequence-spaced dots, dashed first→last connector per lane.
  for (const ev of events) {
    const lane = byKey.get(normalizeRole(ev.agent))
    if (!lane) continue
    lane.dots.push({
      seq: ev.seq,
      leftPct: clampDot((ev.seq / maxSeq) * 100),
      anchored: false,
      failed: ev.outcome === 'failed',
      title: dotTitle(ev),
    })
  }
  for (const lane of lanes) {
    if (lane.dots.length < 2) continue
    const lo = Math.min(...lane.dots.map((d) => d.leftPct))
    const hi = Math.max(...lane.dots.map((d) => d.leftPct))
    lane.spans.push({
      key: 'ordinal-connector',
      leftPct: lo,
      widthPct: Math.max(hi - lo, MIN_SPAN_PCT),
      approx: true,
      title: `${lane.agent} — activity (ordinal, no timestamps)`,
    })
  }
  return { lanes, axis: { kind: 'ordinal' } }
}

/* ── component ──────────────────────────────────────────────────────────── */

const POLL_MS = 4000
const FLASH_MS = 1400

export function ActivityStrip({ project }: { project: string }) {
  const [data, setData] = useState<ActivityData | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [flashSeq, setFlashSeq] = useState<number | null>(null)
  const wasActiveRef = useRef(false)
  const maxSeqRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    wasActiveRef.current = false
    maxSeqRef.current = null
    setData(null)
    setUnavailable(false)

    const poll = async () => {
      try {
        const res = await fetch(`/api/activity/${encodeURIComponent(project)}`)
        if (!res.ok) throw new Error(String(res.status))
        const next = (await res.json()) as ActivityData
        if (cancelled) return
        wasActiveRef.current = next.isActive
        setData(next)
        setUnavailable(false)
        if (next.isActive) timer = setTimeout(() => void poll(), POLL_MS)
      } catch {
        if (cancelled) return
        setUnavailable(true)
        // Transient failure mid-run: keep the stale waterfall and retry.
        if (wasActiveRef.current) timer = setTimeout(() => void poll(), POLL_MS)
      }
    }
    void poll()
    return () => {
      cancelled = true
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [project])

  useEffect(() => {
    if (!data || data.events.length === 0) return
    const maxSeq = data.events.reduce((m, e) => Math.max(m, e.seq), 0)
    const prev = maxSeqRef.current
    maxSeqRef.current = maxSeq
    if (prev === null || maxSeq <= prev) return
    setFlashSeq(maxSeq)
    const timer = setTimeout(() => setFlashSeq(null), FLASH_MS)
    return () => clearTimeout(timer)
  }, [data])

  const layout = useMemo(() => (data ? buildLayout(data) : null), [data])
  const activeKey = data?.isActive && data.activeAgent ? normalizeRole(data.activeAgent) : null
  const empty =
    data !== null && data.events.length === 0 && data.lanes.every((l) => l.spans.length === 0)

  return (
    <section
      aria-label="Agent activity"
      className="rounded-sheet border border-stroke-object bg-card"
      data-testid="activity-strip"
    >
      <header className="flex items-center gap-3 px-3 py-1.5">
        <h3 className="text-2xs font-medium tracking-label text-ink-tertiary uppercase">Activity</h3>
        {data?.isActive ? (
          <span
            className="flex items-center gap-1.5 font-mono text-2xs text-ink-secondary"
            data-testid="activity-live"
          >
            <span
              aria-hidden
              className="size-1.5 rounded-full bg-pass-ink animate-pulse motion-reduce:animate-none"
            />
            live{data.activeAgent ? ` — ${data.activeAgent}` : ''}
          </span>
        ) : (
          data && <span className="font-mono text-2xs text-ink-faint">run ended</span>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="ml-auto rounded-sm text-2xs font-medium tracking-label text-ink-tertiary uppercase transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          data-testid="activity-toggle"
        >
          {expanded ? 'collapse' : 'expand'}
        </button>
      </header>

      {!data || !layout ? (
        <p
          className="border-t border-stroke-hairline px-3 py-2 text-2xs text-ink-faint"
          data-testid={unavailable ? 'activity-unavailable' : 'activity-loading'}
        >
          {unavailable ? 'Activity unavailable.' : 'Loading activity…'}
        </p>
      ) : empty ? (
        <p
          className="border-t border-stroke-hairline px-3 py-2 text-2xs text-ink-faint"
          data-testid="activity-empty"
        >
          No activity recorded.
        </p>
      ) : (
        <div className="border-t border-stroke-hairline px-3 pt-2 pb-1.5">
          <div className={cn('flex flex-col', expanded ? 'gap-1' : 'gap-px')} data-testid="activity-lanes">
            {layout.lanes.map((lane) => (
              <LaneRow
                key={lane.roleKey}
                lane={lane}
                expanded={expanded}
                isActiveLane={lane.roleKey === activeKey}
                flashSeq={flashSeq}
              />
            ))}
          </div>
          <div className="mt-0.5 grid grid-cols-[8rem_minmax(0,1fr)] gap-x-2">
            <span aria-hidden />
            {layout.axis.kind === 'time' ? (
              <div className="flex items-baseline justify-between border-t border-stroke-hairline pt-0.5 font-mono text-2xs text-ink-faint tabular-nums">
                <span>{layout.axis.start}</span>
                <span>{data.isActive ? 'now' : layout.axis.end}</span>
              </div>
            ) : (
              <div className="flex justify-end border-t border-stroke-hairline pt-0.5">
                <span className="text-2xs tracking-label text-ink-faint uppercase">
                  ordinal — no timestamps
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

function LaneRow({
  lane,
  expanded,
  isActiveLane,
  flashSeq,
}: {
  lane: PlacedLane
  expanded: boolean
  isActiveLane: boolean
  flashSeq: number | null
}) {
  const hue = AGENT_HUE[lane.roleKey] ?? NEUTRAL_HUE
  return (
    <div
      className={cn(
        'grid grid-cols-[8rem_minmax(0,1fr)] items-center gap-x-2',
        expanded ? 'h-7' : 'h-3',
      )}
      data-testid={`activity-lane-${lane.roleKey}`}
    >
      {expanded ? (
        <AgentChip agent={lane.agent} className="min-w-0" />
      ) : (
        <span className="flex min-w-0 items-center gap-1.5">
          <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', hue.dot)} />
          <span className="truncate font-mono text-2xs text-ink-tertiary">{lane.agent}</span>
        </span>
      )}
      <div className="relative h-full">
        {lane.spans.map((span) => (
          <div
            key={span.key}
            title={span.title}
            className={cn(
              'absolute top-1/2 -translate-y-1/2 rounded-sheet border',
              expanded ? 'h-3.5' : 'h-1.5',
              hue.line,
              span.approx ? cn('border-dashed', hue.tintFaint) : hue.tintStrong,
            )}
            style={{ left: `${span.leftPct}%`, width: `${span.widthPct}%` }}
          />
        ))}
        {lane.dots.map((dot) => (
          <span
            key={dot.seq}
            title={dot.title}
            className={cn(
              'absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-full transition-shadow duration-700',
              expanded ? 'size-2' : 'size-1',
              dot.anchored ? hue.dot : cn('border bg-transparent', hue.line),
              dot.failed && 'ring-2 ring-fail-line',
              dot.seq === flashSeq && 'ring-4 ring-ring/50',
            )}
            style={{ left: `${dot.leftPct}%` }}
          />
        ))}
        {isActiveLane && (
          <span
            aria-hidden
            title="working now"
            className={cn(
              'absolute top-1/2 right-0 z-20 -translate-y-1/2 rounded-full animate-pulse motion-reduce:animate-none',
              expanded ? 'size-2.5' : 'size-1.5',
              hue.dot,
            )}
          />
        )}
      </div>
    </div>
  )
}
