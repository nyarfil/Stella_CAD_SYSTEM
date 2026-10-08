# Claude Code operating rules (applies to local, project and cloud sessions)
@AGENTS.md

## Model discipline (cost control, mandatory)
- Never run work on Opus by default. The main session runs on Sonnet (see .claude/settings.json). Do not switch it.
- Do small things yourself (<=3 tool calls or one small edit). Delegate coherent chunks, in parallel when independent.
- Use only the named staff in .claude/agents. Never use Explore or general-purpose (denied).

| need | agent | model |
|---|---|---|
| locate files/symbols, read & summarize code/logs/docs | scout | haiku |
| mechanical edits, renames, formatting, run commands, data wrangling | clerk | haiku |
| web/doc research with dated sources | researcher | sonnet |
| implement features, fix bugs, write tests | implementer | sonnet |
| quick sanity check | checker | sonnet (low effort) |
| high-stakes review (security, release, final CAD parts, irreversible/physical actions) | reviewer | opus |

- Escalate on failure only: retry one tier higher if the cheaper agent failed. implementer with model:"opus" only for genuinely hard algorithmic/architectural code or after a failed sonnet attempt.
- Brief subagents in English, self-contained: goal, paths, constraints, done-criteria, return format with a word cap (<=150 words, file:line refs instead of pasted code).
- Reviewer reports blocking issues only.
- Ask the user before irreversible or physical actions (deleting data, printing, publishing, purchases).
