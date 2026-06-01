# MAXIMO AI Trading Brain Architecture

## Objective

Build a professional AI trading brain that converts raw educational material, live market data, broker state, macro events and execution telemetry into controlled probabilistic decisions.

The system must not assume the market is 100 percent reliable. It must estimate probability, prepare opportunities, wait for valid triggers, protect capital and only execute when context, risk and broker state are acceptable.

## Core Architecture

1. Perception layer

- Inputs: Telegram, courses, PDFs, videos, images, audio, manual notes, MT5 candles, spreads, account state, positions, macro calendar and execution telemetry.
- Goal: convert raw data into normalized observations.
- Current project components: ingestion services, media processors, `MT5Bridge`, `market_event_calendar`, platform execution reports.

2. Knowledge layer

- Inputs become chunks, extracted rules, normalized rules, strategy candidates, playbooks and market situation maps.
- Knowledge must include provenance: source, file, channel, rule family, confidence and traceability.
- Current project components: `ContentChunk`, `ExtractedRule`, `NormalizedRule`, `StrategyCandidate`, `StrategyPlaybook`, `TopStrategyDetected`, `market_situation_map`.

3. Retrieval and harmonization layer

- The brain retrieves only the knowledge relevant to the current market regime, symbol, timeframe, session and risk state.
- It must combine learned knowledge with the base strategy instead of forcing every rule as mandatory.
- Current project components: hybrid retrieval, `market_knowledge_harmonizer`, decision source audit.

4. Pattern recognition layer

- Detects market regime: trend, range, compression, expansion, post-news, liquidity manipulation, neutral and non-operable zones.
- Detects setup families: order block rejection, liquidity sweep, FVG continuation, session expansion, breakout retest, trend pullback and risk-only watch states.
- Output is probabilistic: setup maturity, confidence, harmony score, preferred side, missing trigger, invalidation and risk mode.

5. Planning and decision layer

- Converts market state into one of four operational states:
- BLOCKED: execution forbidden.
- WATCH: idea active, waiting for trigger.
- PREPARE_REDUCED: trigger may become executable with reduced risk.
- PREPARE_NORMAL: trigger may become executable with normal demo risk.
- EXECUTE remains gated by signal, SL, RR, broker/demo state, macro status, spread and risk binding.

6. Online adaptation layer

- The brain learns from streams, but does not blindly overwrite strategy logic.
- New learning must pass through audit, scoring and backtest/paper/demo validation.
- Useful future reference: online learning libraries such as River can support incremental models and concept drift monitoring.

7. Evaluation layer

- Every idea must be auditable:
- Which knowledge supported it.
- Which source blocked it.
- Whether the watch improved or deteriorated.
- Whether execution was blocked by market, macro, spread, broker, risk or missing final signal.

8. Risk governance layer

- Capital protection is not optional.
- No execution without logical stop loss.
- No execution without evaluable RR.
- Reduce risk after losses, poor market quality, deteriorating watch health or medium-quality setups.
- Block only critical conditions: live account not authorized, macro high impact window, extreme spread, no SL, invalid RR, non-operable zone, open bot position, risk limit hit or execution guard rejection.

## What To Borrow From External Projects

We should not copy external bots wholesale. We should study patterns and integrate only audited concepts.

- Freqtrade: dry-run first, persistence, backtesting, optimization, web UI, command separation, risk warnings.
- vectorbt: fast research/backtesting across many ideas and timeframes.
- River: streaming and incremental machine learning for market adaptation and concept drift.
- Agentic RAG research: retrieval, memory, planning, iterative reasoning and evaluation.
- LangGraph/LlamaIndex patterns: stateful workflows, memory/checkpointing, tool-based retrieval and document pipelines.

## Professional Safety Rules

- No production/live real-money execution until demo validation, account binding, broker verification, spread checks and risk controls pass.
- External repositories must be reviewed for license, security, dependency weight and architecture fit before integration.
- The system can learn continuously, but trading logic changes must remain controlled and measurable.
- The AI can prepare opportunities aggressively, but execution must remain conservative and auditable.

## Current Implementation Status

- Continuous knowledge cycle exists: `run-knowledge-learning-cycle`.
- Market/demo agent loop exists: `run-trading-service-agent --cycles ... --sleep-seconds ...`.
- Active watch, watch history, risk binding, risk application and decision source audit exist.
- Platform UI, owner/client roles, Exness referral CTA and MT5 agent shell exist.
- Current execution posture remains dry-run/demo until validation is complete.

## Next Integration Targets

1. Add a formal AI brain state model that persists perception, retrieved knowledge, hypothesis, risk state and final decision per cycle.
2. Add market memory by timeframe: M1, M5, M15, H1, H4 and daily summaries.
3. Add concept drift metrics: volatility regime shifts, spread regime shifts, signal conversion decay and strategy family decay.
4. Add news relevance scoring by symbol and currency.
5. Add validated external research adapters only after license/security review.

## Sources Reviewed

- Freqtrade GitHub: https://github.com/freqtrade/freqtrade
- vectorbt GitHub: https://github.com/polakowo/vectorbt
- River GitHub: https://github.com/online-ml/river
- Agentic RAG taxonomy paper: https://arxiv.org/abs/2603.07379
- Agentic AI architecture taxonomy paper: https://arxiv.org/abs/2601.12560
- LlamaIndex docs: https://docs.llamaindex.ai/
- LangGraph memory docs: https://docs.langchain.com/oss/javascript/langgraph/memory
