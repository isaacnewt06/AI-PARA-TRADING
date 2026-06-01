"""Prompt placeholders for future LLM pipelines."""

KNOWLEDGE_SUMMARY_PROMPT = """
You are the future knowledge brain of TELEGRAM_TRADING_BRAIN.
Summarize the provided material into structured trading knowledge:
- key concepts
- operational rules
- risk management guidance
- common setups
- contradictions or caveats
"""

RULE_EXTRACTION_PROMPT = """
Extract explicit and implicit trading rules from the content.
Return rules that can later become measurable conditions for backtesting.
"""
