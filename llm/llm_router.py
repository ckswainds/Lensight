import logging
from typing import Iterator

from config import config

logger = logging.getLogger(__name__)

class LLMRouter:
    """
    Routes LLM calls to the primary provider.
    On quota/server errors, transparently retries with the fallback provider.
    """
    TRANSIENT_ERRORS = [
        '429', 'quota', 'resource_exhausted', 'rate_limit',
        '503', 'service_unavailable', 'service unavailable', 'timeout', 'deadline'
    ]

    def __init__(self):
        logger.info(f"[ROUTER] Initializing Router. Primary provider: {config.PRIMARY_LLM_PROVIDER}")
        
        # Lazy imports to avoid circular dependencies
        from llm.providers.gemini_provider import GeminiProvider
        from llm.providers.huggingface_provider import HuggingFaceProvider
        
        # Instantiate both blocks
        gemini = GeminiProvider()
        hf = HuggingFaceProvider()
        
        # Swap primary/fallback based on config
        if config.PRIMARY_LLM_PROVIDER.lower() == "huggingface":
            self.primary = hf
            self.fallback = gemini
            logger.info("[ROUTER] Set to HuggingFace Primary, Gemini Fallback")
        else:
            self.primary = gemini
            self.fallback = hf
            logger.info("[ROUTER] Set to Gemini Primary, HuggingFace Fallback")

    def _is_transient(self, e: Exception) -> bool:
        s = str(e).lower()
        return any(k in s for k in self.TRANSIENT_ERRORS)

    def stream(self, prompt_messages) -> Iterator:
        try:
            yield from self.primary.stream(prompt_messages)
        except Exception as e:
            if self._is_transient(e):
                logger.warning("[ROUTER] Primary failed (%s: %s) → switching to fallback", type(e).__name__, e)
                yield from self.fallback.stream(prompt_messages)
            else:
                logger.error("[ROUTER] Primary failed with non-transient error: %s", e)
                raise

    def invoke(self, prompt_messages) -> str:
        try:
            return self.primary.invoke(prompt_messages)
        except Exception as e:
            if self._is_transient(e):
                logger.warning("[ROUTER] Primary failed (%s: %s) → switching to fallback", type(e).__name__, e)
                return self.fallback.invoke(prompt_messages)
            else:
                logger.error("[ROUTER] Primary failed with non-transient error: %s", e)
                raise
