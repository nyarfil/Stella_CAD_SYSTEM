/**
 * attempt_log.json — JSONL despite the .json extension: one JSON object per
 * line. Two shapes coexist in real logs: designer/resolver entries
 * ({role, ts, part, approach, outcome, ...}), orchestrator gate entries
 * ({actor, action, verdict, timestamp: "YYYY-MM-DD"}), and harness-era
 * salvage entries ({agent, action, outcome, ...}). Malformed lines are
 * skipped. Entries with a full ISO `ts` sort chronologically; date-only
 * `timestamp` entries are not time-precise, so they keep file order (after
 * the timestamped ones) rather than jumping to midnight.
 */

export interface AttemptLogEntry {
  /** Full ISO `ts`, or the gate entries' date-only `timestamp`. */
  ts: string | null
  /** `role`, or `actor` on gate entries. */
  role: string | null
  part: string | null
  /** `outcome`, or `verdict` on gate entries. */
  outcome: string | null
  /** The whole parsed line, for detail views. */
  raw: Record<string, unknown>
}

export function parseAttemptLog(text: string | null | undefined): AttemptLogEntry[] {
  if (!text) return []
  const decorated: { entry: AttemptLogEntry; key: number; index: number }[] = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    let parsed: unknown
    try {
      parsed = JSON.parse(line)
    } catch {
      continue
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) continue
    const raw = parsed as Record<string, unknown>
    const str = (k: string) => (typeof raw[k] === 'string' ? (raw[k] as string) : null)
    const ts = str('ts')
    const epoch = ts === null ? Number.NaN : Date.parse(ts)
    decorated.push({
      entry: {
        ts: ts ?? str('timestamp'),
        role: str('role') ?? str('actor') ?? str('agent'),
        part: str('part'),
        outcome: str('outcome') ?? str('verdict'),
        raw,
      },
      key: Number.isNaN(epoch) ? Number.POSITIVE_INFINITY : epoch,
      index: decorated.length,
    })
  }
  decorated.sort((a, b) => a.key - b.key || a.index - b.index)
  return decorated.map((d) => d.entry)
}
