/**
 * open_issues.md — assembly conflicts as "### CONFLICT-NNN [status]" blocks
 * of bold-bullet fields. The status bracket carries prose beyond the bare
 * word (e.g. "[RESOLVED 2026-07-13]"); anything mentioning "resolved" counts
 * as resolved, everything else (including no bracket) is open.
 */

import { parseBoldFields, fieldMap } from './boldFields'

export type ConflictStatus = 'open' | 'resolved'

export interface Conflict {
  id: string
  status: ConflictStatus
  parts: string[]
  issue: string
  proposal: string
  recommendation: string
  resolution?: string
}

const HEADER = /^###\s+(CONFLICT-\d+)\s*(?:\[([^\]]*)\])?/

export function parseConflicts(md: string | null | undefined): Conflict[] {
  if (!md) return []
  const lines = md.split('\n')
  const conflicts: Conflict[] = []
  let i = 0
  while (i < lines.length) {
    const m = lines[i].match(HEADER)
    if (!m) {
      i++
      continue
    }
    const block: string[] = []
    i++
    while (i < lines.length && !/^#{1,3}\s/.test(lines[i])) {
      block.push(lines[i])
      i++
    }
    const map = fieldMap(parseBoldFields(block))
    const conflict: Conflict = {
      id: m[1],
      status: /resolved/i.test(m[2] ?? '') ? 'resolved' : 'open',
      parts: (map['parts'] ?? '')
        .split(/[,;]\s*/)
        .map((p) => p.trim())
        .filter(Boolean),
      issue: map['issue'] ?? '',
      proposal: map['proposal'] ?? '',
      recommendation: map['recommendation'] ?? '',
    }
    if (map['resolution'] !== undefined) conflict.resolution = map['resolution']
    conflicts.push(conflict)
  }
  return conflicts
}
