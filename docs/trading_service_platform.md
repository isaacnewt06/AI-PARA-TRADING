# Trading Service Platform

This platform layer turns the existing trading AI into a service foundation that can later support multiple users, multiple broker accounts and controlled execution agents.

## Current scope

- Multi-user ownership and permissions
- Broker account registration
- Per-account broker symbol aliases such as `XAUUSD -> XAUUSDm`
- Execution agent registration for local/VPS MT5 terminals
- HTTP API for users, accounts, agents, deployments and symbol mappings
- Strategy deployment modes:
  - `ai_managed`
  - `signal_mirror`
  - `hybrid_guarded`
- Continuous learning source registration seeded from the existing Telegram and knowledge pipeline

## Core tables

- `platform_users`
- `broker_accounts`
- `account_access_grants`
- `execution_agents`
- `strategy_deployments`
- `learning_integrations`
- `broker_symbol_aliases`

## Design intent

The central AI should decide and learn, while broker-side execution happens through one agent per account or VPS. This keeps broker connectivity isolated and makes it possible to provide the service to approved third parties without mixing accounts together.

## Agent runtime flow

1. The platform owner provisions a broker account and registers an execution agent.
2. The platform returns an `agent_key` for that account-local worker.
3. A local MT5/VPS process runs `run-trading-service-agent`.
4. The agent authenticates against the central API.
5. The agent sends heartbeat updates and resolves broker symbols locally.
6. The agent prepares the local execution environment for the account's active deployments.
7. For supported deployments, the agent runs the assigned strategy cycle locally against MT5.

## Suggested rollout

1. Private owner account in demo
2. Private multi-account demo
3. Small trusted pilot users
4. Public service with stronger auth, billing and audit controls

## Current API endpoints

- `GET /health`
- `GET /`
- `GET /api/platform/status`
- `POST /api/platform/bootstrap`
- `POST /api/platform/users`
- `POST /api/platform/users/credentials`
- `POST /api/platform/auth/token`
- `POST /api/platform/accounts`
- `POST /api/platform/accounts/{account_id}/access`
- `POST /api/platform/accounts/{account_id}/agents`
- `POST /api/platform/accounts/{account_id}/agents/authenticate`
- `POST /api/platform/accounts/{account_id}/agents/heartbeat`
- `POST /api/platform/accounts/{account_id}/deployments`
- `POST /api/platform/accounts/{account_id}/symbols`

## Useful CLI commands

- `platform-issue-credential`
- `run-trading-service-api`
- `run-trading-service-agent`
