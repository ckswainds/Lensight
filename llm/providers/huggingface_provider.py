import logging
from typing import Iterator, List, Dict

from huggingface_hub import InferenceClient
from langsmith import traceable

from config import config

logger = logging.getLogger(__name__)

class HuggingFaceProvider:
    """
    Block B: HuggingFace Serverless Inference Provider.
    Acts as the fallback when Gemini is unavailable.
    Uses InferenceClient.chat_completion() — required for router providers
    (e.g. Featherless-AI) that only support the 'conversational' task.
    Traced via LangSmith.
    """
    def __init__(self):
        logger.info("[PROVIDER] Initializing HuggingFaceProvider")
        self.model = config.HF_FALLBACK_MODEL
        self.client = InferenceClient(
            provider="featherless-ai",
            api_key=config.HUGGINGFACEHUB_API_TOKEN
        )

    def _to_chat_messages(self, messages) -> List[Dict[str, str]]:
        """Normalise LangChain / dict messages into OpenAI-style chat dicts."""
        result = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
            else:
                # LangChain message objects
                role = getattr(m, "type", "user")
                content = getattr(m, "content", str(m))
                # LangChain uses "human"/"ai" — map to OpenAI roles
                if role == "human":
                    role = "user"
                elif role == "ai":
                    role = "assistant"
            result.append({"role": role, "content": content})
        return result

    @traceable(run_type="llm", name="huggingface_fallback", tags=["provider:huggingface"])
    def stream(self, prompt_messages) -> Iterator[str]:
        """Stream tokens using chat_completion. Raises on any error."""
        logger.debug(f"[PROVIDER] Streaming from HuggingFace ({self.model})")
        messages = self._to_chat_messages(prompt_messages)

        response_stream = self.client.chat_completion(
            messages=messages,
            model=self.model,
            max_tokens=config.HF_FALLBACK_MAX_TOKENS,
            temperature=config.HF_FALLBACK_TEMPERATURE,
            stream=True,
        )
        for chunk in response_stream:
            if chunk is None:
                continue
            # OpenAI-compatible streaming delta format
            try:
                delta = chunk.choices[0].delta
                text = delta.content if delta and delta.content else None
                if text:
                    yield text
            except (AttributeError, IndexError, TypeError):
                continue

    @traceable(run_type="llm", name="huggingface_fallback", tags=["provider:huggingface"])
    def invoke(self, prompt_messages) -> str:
        """Non-streaming call using chat_completion. Raises on any error."""
        logger.debug(f"[PROVIDER] Invoking HuggingFace ({self.model})")
        messages = self._to_chat_messages(prompt_messages)

        response = self.client.chat_completion(
            messages=messages,
            model=self.model,
            max_tokens=config.HF_FALLBACK_MAX_TOKENS,
            temperature=config.HF_FALLBACK_TEMPERATURE,
        )
        return response.choices[0].message.content
