/**
 * notes.md verdict extraction. Validators end part/assembly notes with a
 * final verdict line, either bare or as a bold list item:
 *   VALIDATION: PASSED
 *   - **VALIDATION: FAILED**
 * Everything else is prose the UI renders as markdown.
 */

export type ValidationStatus = 'passed' | 'failed' | 'pending'

export interface ParsedNotes {
  validation: ValidationStatus
  /** Prose with the verdict line removed. */
  body: string
}

const VERDICT = /^(?:[-*]\s+)?\*{0,2}VALIDATION:\s*(PASSED|FAILED)\*{0,2}\s*$/

export function parseNotes(md: string | null | undefined): ParsedNotes {
  if (!md) return { validation: 'pending', body: '' }
  const lines = md.split('\n')
  let verdictLine = -1
  let verdict: ValidationStatus = 'pending'
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].trim().match(VERDICT)
    if (m) {
      verdictLine = i
      verdict = m[1] === 'PASSED' ? 'passed' : 'failed'
    }
  }
  if (verdictLine === -1) return { validation: 'pending', body: md.trim() }
  const body = [...lines.slice(0, verdictLine), ...lines.slice(verdictLine + 1)].join('\n').trim()
  return { validation: verdict, body }
}
