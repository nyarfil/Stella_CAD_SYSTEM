/**
 * external/bom.md — the sourcing agent's Bill of Materials. The BOM proper is
 * the first GFM table carrying Qty + Part columns; sourcing appends further
 * tables (interface-dimension cross-checks) which stay reachable via `tables`.
 * Raw markdown passes through untouched for rendering.
 */

import { extractTables, findColumn, type MarkdownTable } from './markdownTables'

export interface BomRow {
  /** null when the Qty cell is not a plain integer. */
  qty: number | null
  part: string
  specification: string
  source: string
  notes: string
}

export interface ParsedBom {
  rows: BomRow[]
  /** Every table in the document, BOM included, in order of appearance. */
  tables: MarkdownTable[]
  raw: string
}

export function parseBom(md: string | null | undefined): ParsedBom {
  if (!md) return { rows: [], tables: [], raw: '' }
  const tables = extractTables(md)
  const bomTable = tables.find(
    (t) => findColumn(t.headers, /qty|quantity/i) !== -1 && findColumn(t.headers, /part/i) !== -1,
  )
  const rows: BomRow[] = []
  if (bomTable) {
    const col = {
      qty: findColumn(bomTable.headers, /qty|quantity/i),
      part: findColumn(bomTable.headers, /part/i),
      specification: findColumn(bomTable.headers, /spec/i),
      source: findColumn(bomTable.headers, /source/i),
      notes: findColumn(bomTable.headers, /note/i),
    }
    for (const cells of bomTable.rows) {
      const cell = (i: number) => (i >= 0 && i < cells.length ? cells[i] : '')
      const qty = Number.parseInt(cell(col.qty), 10)
      rows.push({
        qty: Number.isNaN(qty) ? null : qty,
        part: cell(col.part),
        specification: cell(col.specification),
        source: cell(col.source),
        notes: cell(col.notes),
      })
    }
  }
  return { rows, tables, raw: md }
}
