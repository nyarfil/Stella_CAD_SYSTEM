/**
 * design_log.md — the project's chronological agent activity feed, one
 * "[agent] message" line per action. Session-suffixed tags from the
 * mortal-orchestrator design ("[orchestrator S1]") map to the base agent.
 * Lines that don't open with a bracket tag are treated as continuations
 * of the previous message.
 */

export interface DesignLogEntry {
  agent: string
  message: string
  index: number
}

const ENTRY = /^\[([\w-]+)(?:\s+[\w-]+)?\]\s*(.*)$/

export function parseDesignLog(md: string | null | undefined): DesignLogEntry[] {
  if (!md) return []
  const entries: DesignLogEntry[] = []
  for (const line of md.split('\n')) {
    const m = line.match(ENTRY)
    if (m) {
      entries.push({ agent: m[1], message: m[2].trim(), index: entries.length })
    } else if (line.trim() && entries.length > 0) {
      const current = entries[entries.length - 1]
      current.message = `${current.message}\n${line.trim()}`
    }
  }
  return entries
}
