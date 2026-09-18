/**
 * Minimal GFM table extraction — enough for the harness's bom.md and any
 * design_plan.md tables. Components render the raw markdown; these rows are
 * for typed access (sorting, column mapping), not for re-rendering.
 */

export interface MarkdownTable {
  headers: string[]
  rows: string[][]
}

const SEPARATOR_CELL = /^:?-+:?$/

function splitRow(line: string): string[] {
  let body = line.trim()
  if (body.startsWith('|')) body = body.slice(1)
  if (body.endsWith('|')) body = body.slice(0, -1)
  return body.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, '|'))
}

function isRow(line: string): boolean {
  return line.includes('|') && line.trim().length > 0
}

function isSeparator(line: string): boolean {
  if (!isRow(line)) return false
  const cells = splitRow(line)
  return cells.length > 0 && cells.every((cell) => SEPARATOR_CELL.test(cell))
}

/** All GFM tables in the document, in order of appearance. */
export function extractTables(md: string): MarkdownTable[] {
  const lines = md.split('\n')
  const tables: MarkdownTable[] = []
  let i = 0
  while (i < lines.length) {
    if (isRow(lines[i]) && i + 1 < lines.length && isSeparator(lines[i + 1])) {
      const headers = splitRow(lines[i])
      const rows: string[][] = []
      i += 2
      while (i < lines.length && isRow(lines[i]) && !isSeparator(lines[i])) {
        rows.push(splitRow(lines[i]))
        i++
      }
      tables.push({ headers, rows })
    } else {
      i++
    }
  }
  return tables
}

/** Index of the first header matching the pattern, or -1. */
export function findColumn(headers: string[], pattern: RegExp): number {
  return headers.findIndex((h) => pattern.test(h))
}
