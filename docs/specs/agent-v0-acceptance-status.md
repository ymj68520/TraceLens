# Agent v0 Project Status — Acceptance Track

Updated: 2026-10-01 (Acceptance Generation 1 closure / Generation 2 preparation).

```text
Agent v0 Architecture:
FROZEN

Calibration:
COMPLETE / ZERO_CHANGE

Acceptance Generation 1:
CLOSED
B6_INVALID
holdout CONSUMED

Generation-1 diagnostic:
functional requirement NOT MET

Formal Agent v0 acceptance:
NOT ESTABLISHED

Acceptance Generation 2:
IN PREPARATION

Production runtime:
UNCHANGED
```

## Model status (exact wording, superseding earlier summaries)

```text
SenseNova (sensenova-6.8-flash-lite):
CALIBRATION-QUALIFIED

Generation-1 B6 diagnostic:
functional requirement not met

Formal sealed acceptance:
NOT ESTABLISHED
```

It is incorrect to say "SenseNova was formally rejected by a valid B6":
the Generation-1 B6 execution is formally B6_INVALID
(HOLDOUT_AGENT_INPUT_NOT_PRESEALED — the Agent-visible charter was authored
at execution entry instead of being presealed before admission), so no
formal sealed acceptance measurement exists for any model.  The 6-run
diagnostic remains preserved as DIAGNOSTIC_ONLY evidence
(functional floor not met: refund-fraud 0/3, vpn-causal 1/3 qualifying;
five other axes clean).

## Frozen vs open

- `formal acceptance not established` does NOT unfreeze the architecture:
  there is no Evidence Integrity / StateTransition / Grounding / Handle
  correctness regression.  Architecture stays FROZEN.
- Production runtime (A1-S, Supervisor v2, A1-T, A1-H, StateTransitionPolicy,
  FinalizationGate) and the ZERO_CHANGE calibration stay UNCHANGED.  Any
  future runtime change requires a new runtime generation → calibration
  requalification → a new acceptance generation, driven by general
  product/calibration evidence — never by consumed holdout answers.

## Generation-1 permanent history (never to be overwritten)

1. B6 execution occurred (6 scheduled attempts; artifacts immutable).
2. Formal measurement invalid (B6_INVALID).
3. Holdout consumed (entire Generation-1 pool retired).
4. Diagnostic functional requirement not met (DIAGNOSTIC_ONLY).

Primary records:
`benchmarks/profiles/b6-interpretation-amendment-v1.json`,
`benchmarks/profiles/acceptance-generation-closure-v1.json`,
`benchmarks/results/agent-v0/b6-holdout/` (immutable),
`docs/specs/agent-b6-holdout-acceptance-audit.md` (execution-era record).
