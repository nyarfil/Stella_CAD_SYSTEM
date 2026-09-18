/**
 * Shared extraction for the harness's bold-bullet field convention:
 *   - **Field name**: value possibly spanning
 *     continuation lines
 * Used by open_issues.md CONFLICT blocks and design_plan.md part sections.
 */

export interface BoldField {
  /** Field name as written, e.g. "Parts" or "parallel_safe". */
  name: string
  value: string
}

const BULLET = /^[-*]\s+\*\*([^*]+?)\*\*\s*:?\s*(.*)$/

/**
 * Parse a run of lines into bold-bullet fields. Lines that are neither a
 * bullet nor blank are treated as continuations of the current field's value.
 * Tolerates the colon inside or outside the bold span (`**Parts**:` / `**Parts:**`).
 */
export function parseBoldFields(lines: string[]): BoldField[] {
  const fields: BoldField[] = []
  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    const m = line.match(BULLET)
    if (m) {
      const name = m[1].replace(/:$/, '').trim()
      fields.push({ name, value: m[2].trim() })
    } else if (line.trim() && fields.length > 0) {
      const current = fields[fields.length - 1]
      current.value = current.value ? `${current.value}\n${line.trim()}` : line.trim()
    }
  }
  return fields
}

/** Case-insensitive lookup map: lowercased field name → value. */
export function fieldMap(fields: BoldField[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const field of fields) {
    const key = field.name.toLowerCase()
    if (!(key in map)) map[key] = field.value
  }
  return map
}
