/** Parser suite against the real treasure_chest_test_fixture fixture tree (read via node fs). */
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseAttemptLog } from './attemptLog'
import { parseBom } from './bom'
import { parseConflicts } from './conflicts'
import { parseDesignLog } from './designLog'
import { parseDesignPlan } from './designPlan'
import { parseDfmaReport } from './dfma'
import { parseNotes } from './notes'
import { parseColorLegend, parseRenderFilenames, STANDARD_RENDER_FILENAMES } from './renders'

const fx = (rel: string): string =>
  readFileSync(new URL(`./__fixtures__/treasure_chest_test_fixture/${rel}`, import.meta.url), 'utf-8')

describe('parsers on treasure_chest_test_fixture fixtures', () => {
  it('extracts the VALIDATION verdict from part notes and strips it from the body', () => {
    const notes = parseNotes(fx('assembly/lid/notes.md'))
    expect(notes.validation).toBe('passed')
    expect(notes.body).not.toMatch(/^VALIDATION: PASSED$/m)
  })

  it('parses the dfma report with counts, failures, and severities', () => {
    const report = parseDfmaReport(fx('assembly/lid/dfma_report.json'))!
    expect(report.verdict).toBe('fail')
    expect(report.counts).toEqual({ evaluated: 10, passed: 4, failed: 6, uncertain: 0 })
    expect(report.failures).toHaveLength(6)
    for (const failure of report.failures) {
      expect(['critical', 'major', 'minor']).toContain(failure.severity)
    }
  })

  it('parses CONFLICT-001 as resolved with its structured fields', () => {
    const conflict = parseConflicts(fx('open_issues.md')).find((c) => c.id === 'CONFLICT-001')!
    expect(conflict.status).toBe('resolved')
    expect(conflict.parts).toEqual(['lid', 'base_box'])
    expect(conflict.resolution).toMatch(/promoted/)
  })

  it('parses design log entries with agent chips', () => {
    const entries = parseDesignLog(fx('design_log.md'))
    expect(entries[0]!.agent).toBe('planner')
    expect(entries.map((e) => e.agent)).toContain('sourcing')
  })

  it('skips malformed attempt-log lines and maps gate-entry aliases', () => {
    const text = fx('assembly/lid/attempt_log.json')
    expect(parseAttemptLog(text)).toHaveLength(3)
    const noisy = parseAttemptLog(`${text}\n{"broken": \nnot json at all\n[1,2,3]\n`)
    expect(noisy).toHaveLength(3)
    expect(noisy.some((e) => e.role === 'orchestrator' && e.outcome === 'promoted')).toBe(true)
  })

  it('maps the 8 standard render filenames to views, styles, and urls', () => {
    const set = parseRenderFilenames(STANDARD_RENDER_FILENAMES, (f) => `/r/${f}`)
    expect(set).toHaveLength(8)
    const iso = set.find((r) => r.view === 'iso' && r.style === 'clean')
    expect(iso).toEqual({ view: 'iso', style: 'clean', filename: 'iso_clean.png', url: '/r/iso_clean.png' })
  })

  it('parses the assembly color legend', () => {
    const legend = parseColorLegend(fx('assembly/renders/color_legend.txt'))
    expect(legend).toHaveLength(5)
    expect(legend[0]).toEqual({ part: 'base_box', color: 'red', rgb: 'rgb(220,40,40)' })
  })

  it('parses BOM rows out of the right table', () => {
    const bom = parseBom(fx('external/bom.md'))
    expect(bom.rows).toHaveLength(4)
    expect(bom.tables).toHaveLength(2)
    expect(bom.rows[0]).toMatchObject({ qty: 2, part: 'Steel dowel pin' })
  })

  it('parses design plan parts with make/buy kinds and qty', () => {
    const plan = parseDesignPlan(fx('design_plan.md'))
    expect(plan.parts).toHaveLength(5)
    expect(plan.parts.filter((p) => p.kind === 'make').map((p) => p.name)).toEqual([
      'base_box',
      'lid',
      'hinge_block',
      'hasp_plate',
    ])
    expect(plan.parts[2]).toMatchObject({ kind: 'make', qty: 2 })
    expect(plan.parts[4]!.kind).toBe('buy')
  })
})

const ifx = (rel: string): string =>
  readFileSync(new URL(`./__fixtures__/impeller_assembly_test_fixture/${rel}`, import.meta.url), 'utf-8')

describe('parsers on impeller_assembly_test_fixture fixtures (harness-era run formats)', () => {
  it('parses session-suffixed agent tags like [orchestrator S1] down to the base agent', () => {
    const entries = parseDesignLog(ifx('design_log.md'))
    expect(entries.length).toBeGreaterThan(20)
    expect(entries[0]!.agent).toBe('orchestrator')
    expect(entries[0]!.message).toMatch(/^ORIENT/)
  })

  it('returns zero conflicts for an ISSUE-only open_issues.md', () => {
    expect(parseConflicts(ifx('open_issues.md'))).toEqual([])
  })

  it('extracts the impeller validation verdict', () => {
    expect(parseNotes(ifx('assembly/impeller/notes.md')).validation).toBe('passed')
  })

  it('parses the conditional_pass dfm report with its counts', () => {
    const report = parseDfmaReport(ifx('assembly/impeller/dfma_report.json'))!
    expect(report.verdict).toBe('conditional_pass')
    expect(report.counts).toEqual({ evaluated: 10, passed: 3, failed: 3, uncertain: 4 })
    expect(report.failures).toHaveLength(3)
  })

  it('maps harness-era salvage entries ({agent, ...}) to a role', () => {
    const entries = parseAttemptLog(ifx('assembly/impeller/attempt_log.json'))
    expect(entries).toHaveLength(1)
    expect(entries[0]!.role).toBe('cad_designer')
    expect(entries[0]!.outcome).toBe('geometry_completed_agent_died_before_logging')
  })

  it('parses the six-part color legend', () => {
    const legend = parseColorLegend(ifx('assembly/renders/color_legend.txt'))
    expect(legend).toHaveLength(6)
    expect(legend[2]).toEqual({ part: 'impeller', color: 'green', rgb: 'rgb(40,160,40)' })
  })

  it('parses the 3-make + 3-buy design plan', () => {
    const plan = parseDesignPlan(ifx('design_plan.md'))
    expect(plan.parts).toHaveLength(6)
    expect(plan.parts.filter((p) => p.kind === 'make').map((p) => p.name)).toEqual([
      'pulley_shaft',
      'bearing_housing',
      'impeller',
    ])
    expect(plan.parts.filter((p) => p.kind === 'buy')).toHaveLength(3)
  })

  it('parses catalog BOM rows', () => {
    const bom = parseBom(ifx('external/bom.md'))
    expect(bom.rows).toHaveLength(4)
    expect(bom.rows[0]).toMatchObject({ qty: 1, part: 'main_bearing' })
  })
})
