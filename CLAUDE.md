# CLAUDE.md — MockPost contribution workflow

This file documents the git workflow for MockPost, distilled from the
`release-plan` skill conventions. Follow it for every change: commits,
branches, issues and pull requests must read as written by a senior
developer — natural, concise, technical prose. No AI marks anywhere.

## Language

All repository artifacts are in **English**: commit titles/bodies, branch
names, issue titles/bodies, PR titles/bodies, code comments and docs.
The only exception is communication in chat; everything committed is English.

## Conventional commits

Format: `<prefix>: <summary in third-person singular, max 72 chars>`

Valid prefixes:

| Prefix | Use for |
|---|---|
| `feat` | New capability, improvement, refactor, infrastructure |
| `fix` | Bug correction or incorrect behavior |
| `chore` | Maintenance, dependencies, CI/CD, packaging, technical cleanup |
| `refactor` | Code restructuring without behavior change |
| `docs` | Documentation only |
| `test` | Tests only |

Rules:

- Summary in **third-person singular** ("adds X", "fixes Y") — never imperative ("add X").
- No accents, no parentheses, max **72 characters** (validated with
  `bash ~/.claude/skills/release-plan/validate-msg.sh "<title>"`).
- **Body** — pick the case that applies, in order:
  - **A — No body**: title fully explains the change.
  - **B — Short prose** (small, unit-like change): 1-2 direct lines explaining
    the *why* or *what for* — not the *what* (that is the title/diff).
  - **C — Bulleted justifications** (diverse commit): one `- ` line per
    area/reason.
- Body lines: max 72 chars.
- **NEVER** include `Co-Authored-By` or any AI attribution in any commit.
- **Footer**: intermediate commits in a group use `Refs #N`; the last commit
  of the group uses `Closes #N` (N = issue number).

## Branches

Pattern: `<prefix>/<N>-<kebab-case-description>`

- Features, chores, spikes: `feat/12-verificacion-otp` (see language note below).
- Bug fixes: `fix/23-error-snapshot-nulo`.
- Description in **kebab-case**, lowercase, no accents.

> **Language note:** the `release-plan` default mandates Spanish branch
> descriptions. This project commits in English but keeps branch names in
> Spanish kebab-case per that rule. If you prefer English branches, say so
> once and it becomes the project rule.

One branch per issue; mergeable and deployable independently.

## Issues

Titles orient to delivered value; bodies use the `release-plan` templates:

- **feat**: `Title` + `User story: As <role>, I want <action>, so that <benefit>.`
  + `Why` + Gherkin scenarios (`Scenario / Given / When / Then`) + `Out of scope`.
- **bug**: `[Bug] <what fails and where>` + `Steps / Expected / Actual /
  Frequency / Impact`.
- **chore**: `[Chore] <task>` + `What / Why now / Scope / Definition of Done`.
- **spike**: `[Spike] <question>` + `Context / Questions / Timebox`.

No labels, no quick actions.

## Pull requests

- **Title**: `<Verb phrase in third person>, relates #<N>` (e.g. "Adds OTP
  verification, relates #12"). For the closing PR of an issue:
  "Closes #<N>" in the body, title keeps the verb phrase.
- **Body**: context paragraph + `Changes` bullet list + `Closes #N` +
  `How to test` + `Change type` (only the applicable ones from
  feat/fix/refactor/docs/test/chore) + `Deploy considerations` (only if any)
  + `Checklist` (CI green, tested locally, self-review done).
- When merging, delete the source branch.

## Workflow per change

1. `openspec` proposal → issue → branch (`feat/N-desc` or `fix/N-desc`).
2. Commit per layer with the rules above; validate each title.
3. Push branch, open PR with the template, self-review.
4. After merge: delete branch, close issue via the PR.

## Validation

```bash
bash ~/.claude/skills/release-plan/validate-msg.sh "feat: adds otp verification"
# ✓ OK → usable; ✗ FALLO → reword before committing
```
