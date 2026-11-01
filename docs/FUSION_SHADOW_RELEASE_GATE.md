# APT FUSION — shadow integration and release gates

This document accompanies the draft safety-gate PR. It describes evidence required before any
claim of operational readiness. It is **not** an authorization to trade or a performance claim.

## Locked scope

- APT is a research and strategy-data source. The existing APT → SENSEI adapter consumes
  documented `StrategyExportBundle` objects under schema `phase3.v1`, with explicit
  source bytes, SHA-256 verification, and offline parsing.
- SENSEI stays at `RUNTIME=SIMULATION`, `PERFORMANCE=LOCKED`, and
  `TRADING_AUTHORITY=NONE`.
- No execution through MetaTrader 5, `order_send`, broker sessions, DEMO or LIVE orders,
  or management of real capital is permitted by this release.
- No paid inference/transcription API, automatic credit purchase, or new subscription is
  required. Accidental availability of an API credential must not enable spending.
- Claude Code's GitHub integration is for read-only reviews of pull-request revisions.
  Automatic PR fixes and additional connectors are disabled. ChatGPT Plus and Claude Pro
  do not by themselves constitute interchangeable paid API credentials.

## Evidence ledger

| Gate | Evidence | Status |
| --- | --- | --- |
| Focused safety regressions | 147/147 offline tests at `701d8f5cf3abbd905fad13c3252fd81d8f932434`, Actions run `41276443868` | PASS at that SHA only |
| Additional hard-lock CI | 166/166 offline tests at `89a714d5ea8b645c497b298318b2d413448469c2`, Actions run `41276925586` | PASS at that SHA only |
| Producer schema fixture CI | 168/168 offline tests at `32f3c3be5bac4b053ef0c49791e9f86b5d08252d`, Actions run `41277105541` | PASS at that SHA only |
| Independent review | Claude Code read-only static inspection of exact code head `32f3c3be5bac4b053ef0c49791e9f86b5d08252d`: https://claude.ai/code/session_01BqW8hPv9q35SE69z8rQ7kM; GitHub CI independently checked separately | Static lock evidence supports no direct order_send; whole repo NOT PROVEN |
| Whole-repository testing | 467 tests collected locally after installing optional test dependencies; first full-suite failure is a missing `data/strategies/adaptive_strategy_library.json` artifact | NOT PROVEN |
| APT → SENSEI data contract | Actual Pydantic `StrategyExportBundle` bytes from a **synthetic** sample, SHA-256 `f11ed6b675e69651f3f8ded72e45678fd174fc5f7c7a7c45ac5da15479027147`; SENSEI PR #379 exact head `eaf530b` passed 19/19 adapter tests in Actions `41277176271` | PASS synthetic contract only; source truth NOT PROVEN |
| Backtest integrity | Auditable source licensing, chronological splits, fees, spread, slippage, out-of-sample testing | NOT PROVEN |
| Financial results | Live or simulated P&L cannot be inferred from unit tests or a repository audit | NOT PROVEN |

## Review procedure

1. Keep the pull request in DRAFT. Record its head SHA before running any tests.
2. Run only offline, no-broker, no-paid-API CI; cite run IDs and distinguish tested paths
   from untested legacy modules.
3. Require an independent review of the exact diff and source contract. Any P0/P1 risk
   remains a merge blocker; ambiguous evidence is `NOT_PROVEN`, not `PASS`.
4. Test the cross-repository contract without granting one repository authority to
   place orders on behalf of the other.
5. Any future demo, live, or capital authorization requires a separate explicit
   governance decision, compliance/risk review, and defensible validation. This
   document grants none.

## Legacy trading hard-lock remediation (draft branch)

- All three mutating `MT5Bridge` methods fail before loading a backend:
  `place_demo_market_order`, `modify_position_sl_tp`, and `close_position_partial`.
  Their former broker `order_send` implementations have been removed. This is
  an unconditional research-release lock, not an environment opt-in.
- Importing `demo_engine_patch` no longer monkey-patches the controlled demo
  survival protocol. `UnleashedDemoProtocolV1` always blocks and grants zero
  risk. The legacy `run_unleashed_ai.py` runner and direct MT5 replication
  wrapper reject execution, including calls that bypass the entrypoint.
- The original offline safety checks now include specific legacy bypass
  regression tests and MAXIMO/replay simulation suites. CI scans every
  production Python file for newly introduced direct `order_send` calls and
  asserts that all mutating bridge methods have only the unconditional guard.
  The legacy `quick_ai_check` is explicitly false for all tested configurations.
  Record the latest exact SHA and GitHub Actions result before treating the
  updated checks as verified.
- Simulated and historical replay positions are internal fakes, not broker
  orders. Their tests do not authorize reconnecting live or DEMO execution.

## Commercial-readiness distinction

A product may eventually monetize lawful research tools, reporting, or simulation
services, but **no revenue, trading profitability, or launch readiness is demonstrated**
by the current CI. Before commercialization, verify rights to the underlying Telegram
content and market data, customer terms, support, and applicable regulatory obligations.
Do not advertise backtested figures as guaranteed future performance.
