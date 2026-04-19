import logging
from typing import Iterator

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser

from config import config

logger = logging.getLogger(__name__)

class GeminiProvider:
    """
    Block A: Gemini 2.5 Flash Provider.
    Handles both streaming chat and single-shot narrative generation.
    All calls tagged with LangSmith run names and tags.
    """
    def __init__(self):
        logger.info("[PROVIDER] Initializing GeminiProvider")
        self.llm = ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            api_key=config.GEMINI_API_KEY,
            streaming=True,
            timeout=config.LLM_TIMEOUT,
            max_retries=0
        ).with_config(
            run_name="gemini_primary",
            tags=["provider:gemini", f"model:{config.LLM_MODEL}"]
        )

    def stream(self, prompt_messages) -> Iterator:
        """Stream tokens. Raises on any error (router handles fallback)."""
        logger.debug("[PROVIDER] Streaming from Gemini")
        for chunk in self.llm.stream(prompt_messages):
            yield chunk

    def invoke(self, prompt_messages) -> str:
        """Non-streaming call for narrative gen. Raises on any error."""
        logger.debug("[PROVIDER] Invoking Gemini")
        chain = self.llm | StrOutputParser()
        return chain.invoke(prompt_messages)
