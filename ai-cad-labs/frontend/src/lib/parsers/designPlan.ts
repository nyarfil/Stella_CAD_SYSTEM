/**
 * design_plan.md — the planner's project decomposition. Typed access covers
 * the "## Parts" section: one "### N. name" block of bold-bullet fields per
 * part. Make-parts here ARE the part roster (each owns assembly/<name>/);
 * buy-parts have no directory. Kind detection prefers the "(make)"/"(buy)"
 * parenthetical because Type values like "Standard (buy) — see Make vs Buy"
 * contain the other keyword as prose. Raw markdown passes through untouched.
 */

import { extractTables, type MarkdownTable } from './markdownTables'
import { parseBoldFields, fieldMap } from './boldFields'

export interface PlanPart {
  /** Header text after the "N." prefix, e.g. "base_box" — the directory name for make-parts. */
  name: string
  /** The header's own number when present, else position + 1. */
  index: number
  kind: 'make' | 'buy' | 'unknown'
  /** From "qty N" in the Type field; null when unstated (typical for buy rows). */
  qty: number | null
  /** From the parallel_safe field; null when the field is absent. */
  parallelSafe: boolean | null
  /** All bold-bullet fields, lowercased name → value (description, interfaces, …). */
  fields: Record<string, string>
}

export interface ParsedDesignPlan {
  parts: PlanPart[]
  tables: MarkdownTable[]
  raw: string
}

const PART_HEADER = /^###\s+(?:(\d+)\.\s*)?(.+?)\s*$/

function toPart(header: RegExpMatchArray, fields: Record<string, string>, position: number): PlanPart {
  const typeValue = fields['type'] ?? ''
  const paren = typeValue.match(/\(\s*(make|buy)\s*\)/i)
  let kind: PlanPart['kind'] = 'unknown'
  if (paren) kind = paren[1].toLowerCase() as 'make' | 'buy'
  else if (/\bbuy\b/i.test(typeValue)) kind = 'buy'
  else if (/\bmake\b/i.test(typeValue)) kind = 'make'
  const qty = typeValue.match(/qty\s*:?\s*(\d+)/i)
  const parallel = fields['parallel_safe']
  return {
    name: header[2],
    index: header[1] ? Number.parseInt(header[1], 10) : position + 1,
    kind,
    qty: qty ? Number.parseInt(qty[1], 10) : null,
    parallelSafe:
      parallel === undefined ? null : /^true\b/i.test(parallel) ? true : /^false\b/i.test(parallel) ? false : null,
    fields,
  }
}

export function parseDesignPlan(md: string | null | undefined): ParsedDesignPlan {
  if (!md) return { parts: [], tables: [], raw: '' }
  const lines = md.split('\n')

  // Bounds of the "## Parts" section (### headers don't match /^##\s/).
  let start = -1
  let end = lines.length
  for (let i = 0; i < lines.length; i++) {
    if (start === -1) {
      if (/^##\s+Parts\s*$/i.test(lines[i])) start = i + 1
    } else if (/^##\s/.test(lines[i])) {
      end = i
      break
    }
  }

  const parts: PlanPart[] = []
  let i = start === -1 ? end : start
  while (i < end) {
    const m = lines[i].match(PART_HEADER)
    if (!m) {
      i++
      continue
    }
    const block: string[] = []
    i++
    while (i < end && !/^#{2,3}\s/.test(lines[i])) {
      block.push(lines[i])
      i++
    }
    parts.push(toPart(m, fieldMap(parseBoldFields(block)), parts.length))
  }
  return { parts, tables: extractTables(md), raw: md }
}
