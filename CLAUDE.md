# meeting-transcriber

Turns meeting recordings into speaker-labeled transcripts, offline by default.
Source of truth for scope and decisions: `docs/PLAN.md`.

## Hard rules (all agents)
- Never commit real meeting recordings or transcripts. Test media is generated (ffmpeg `lavfi`, offline TTS).
- Demo only with own or Creative Commons / public-domain content.
- Stay inside MVP scope in `docs/PLAN.md`; anything else goes to "Open questions", not code.
- Never push, open PRs, publish images, or tag releases without explicit user approval.

## Team workflow
The main session is the orchestrator. Role agents live in `.claude/agents/`:
`ba` → `developer` + `tester` → `devops` → `tech-writer` → orchestrator review → user approval.

Handoffs are files, not chat:
| Artifact | Owner | Path |
|---|---|---|
| Milestone spec (stories, acceptance criteria) | ba | `docs/specs/M<n>-<slug>.md` |
| Code | developer | `src/meeting_transcriber/**`, `pyproject.toml` |
| Tests | tester | `tests/**` |
| Test report / bug reports | tester | `docs/reports/M<n>-test-report.md` |
| Docker, CI | devops | `docker/**`, `.github/workflows/**` |
| User docs, promo texts (GitHub About, LinkedIn, Upwork) | tech-writer | `README.md`, `docs/**` incl. `docs/promo/`, `docs/assets/` (except specs/reports) |

Acceptance criteria IDs (`AC-M1-01`, …) are referenced by code comments sparingly, by test names/docstrings, and by the test report.

Gates: user approves each spec before development starts, and approves the final diff before commit.
Developer ↔ tester fix loop: max 3 rounds, then escalate to the user.

## Conventions
- Python ≥ 3.10, package `meeting_transcriber` under `src/`, pytest, `@pytest.mark.slow` for real-model tests.
- Branch per milestone: `m<n>-<slug>`.
