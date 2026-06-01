"""Summary pipeline placeholder."""

from __future__ import annotations

from src.ai.interfaces import LLMClient
from src.ai.prompts.knowledge_prompts import KNOWLEDGE_SUMMARY_PROMPT


class SummaryPipeline:
    """Future LLM summary orchestration."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client

    def summarize(self, text: str) -> str:
        if not self.client:
            # TODO: wire this pipeline into document/video knowledge summarization once an LLM provider is configured.
            return "LLM summary provider not configured yet."
        return self.client.summarize(KNOWLEDGE_SUMMARY_PROMPT, text)
