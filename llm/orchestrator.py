"""Orchestrator: manages LLM call flow and chaining."""

import json
import logging
import time
from typing import Any

from langsmith import traceable

from llm.narrative_generator import NarrativeGenerator
from llm.llm_router import LLMRouter
from llm.prompt_builder import PromptBuilder
from config import config

logger = logging.getLogger(__name__)

_MAX_MESSAGES = 10


def _stringify_chunk_content(content: Any) -> str:
    """
    Normalise a stream chunk's content field to a plain string.
    LangChain / Gemini chunks may carry str, list[str], or list[dict] blocks.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
                else:
                    c = item.get("content")
                    if isinstance(c, str):
                        parts.append(c)
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


class LLMOrchestrator:
    def __init__(self):
        self.generator = NarrativeGenerator()
        self.router = LLMRouter()
        self.chat_prompt = PromptBuilder.build_grounded_chat_prompt()
        self.summarize_prompt = PromptBuilder.build_summarization_prompt()

    def analyze_company(self, data: dict, rag_context: str = "") -> str:
        """Generate a full qualitative narrative report from financial data."""
        return self.generator.generate_narrative(
            financial_data=data,
            context=rag_context
        )

    def chat_with_report(self, question: str, rag_context: str) -> str:
        """Simple chat used by tests — no grounding or conversation history."""
        from langchain_core.prompts import ChatPromptTemplate
        simple_prompt = ChatPromptTemplate.from_template(
            "You are a helpful financial analyst assistant answering questions based on the provided Annual Report context.\n"
            "Context: {context}\n\nQuestion: {question}"
        )
        prompt_messages = simple_prompt.invoke({"context": rag_context or "No context.", "question": question})
        return self.router.invoke(prompt_messages)

    @traceable(run_type="chain", name="chat_grounded")
    def chat_grounded(
        self,
        question: str,
        company: str,
        financial_summary: str,
        rag_context: str,
        conversation_summary: str = "",
        rag_status: str = "idle",
    ) -> str:
        """
        Grounded chat using computed ratios + optional RAG context. Refuses to fabricate.

        Parameters
        ----------
        rag_status : str
            One of: "idle", "indexing", "ready", "error".
        """
        logger.info("Starting chat_grounded for %s. Question: %s...", company, question[:50])

        if rag_status == "ready":
            report_status = "Annual Report indexing is complete. Use report context specifically for quality/qualitative insights."
            rag_ready_flag = True
        elif rag_status == "indexing":
            report_status = "Annual Report is currently being indexed. It will be available shortly. For now, answer using ONLY the financial ratios provided. Disclose that the report is still processing."
            rag_ready_flag = False
        elif rag_status == "error":
            report_status = "Annual Report indexing encountered an error. Answer using ONLY the financial ratios provided. Disclose that the report became unavailable."
            rag_ready_flag = False
        else:
            report_status = "No annual report was uploaded. Answer using ONLY the financial ratios provided. Clarify that insights from an annual report are not available."
            rag_ready_flag = False

        try:
            prompt_messages = self.chat_prompt.invoke({
                "company": company,
                "conversation_summary": conversation_summary or "No prior conversation.",
                "financial_summary": financial_summary,
                "report_status": report_status,
                "rag_context": rag_context if (rag_context and rag_ready_flag) else "No context available (no report uploaded).",
                "question": question,
            })
            response = self.router.invoke(prompt_messages)
            logger.info("Response generated. Length: %d chars", len(response))
        except Exception as e:
            logger.error("Error during chat_grounded: %s", e, exc_info=True)
            raise

        if rag_status == "indexing":
            response += "\n\n---\n⏳ **Note:** Annual Report indexing is in progress. This answer is based on financial data only. Qualitative insights from the report will be available once indexing completes."
        elif rag_status == "error":
            response += "\n\n---\n⚠️ **Note:** Annual Report indexing encountered an error. This answer is based on financial data only."

        return response

    @traceable(run_type="chain", name="chat_grounded_stream")
    def chat_grounded_stream(
        self,
        question: str,
        company: str,
        financial_summary: str,
        rag_context: str,
        conversation_summary: str = "",
        rag_status: str = "idle",
    ):
        """
        Streaming version of chat_grounded. Yields tokens as they arrive from the LLM.

        Parameters
        ----------
        rag_status : str
            One of: "idle", "indexing", "ready", "error".
        """
        logger.info("Starting chat_grounded_stream for %s. Question: %s...", company, question[:50])

        if rag_status == "ready":
            report_status = "Annual Report indexing is complete. Use report context specifically for quality/qualitative insights."
            rag_ready_flag = True
        elif rag_status == "indexing":
            report_status = "Annual Report is currently being indexed. It will be available shortly. For now, answer using ONLY the financial ratios provided. Disclose that the report is still processing."
            rag_ready_flag = False
        elif rag_status == "error":
            report_status = "Annual Report indexing encountered an error. Answer using ONLY the financial ratios provided. Disclose that the report became unavailable."
            rag_ready_flag = False
        else:
            report_status = "No annual report was uploaded. Answer using ONLY the financial ratios provided. Clarify that insights from an annual report are not available."
            rag_ready_flag = False

        try:
            prompt_messages = self.chat_prompt.invoke({
                "company": company,
                "conversation_summary": conversation_summary or "No prior conversation.",
                "financial_summary": financial_summary,
                "report_status": report_status,
                "rag_context": rag_context if (rag_context and rag_ready_flag) else "No context available (no report uploaded).",
                "question": question,
            })

            token_count = 0
            start_time = time.time()
            accumulated_response = ""

            for chunk in self.router.stream(prompt_messages):
                raw = getattr(chunk, "content", None)
                if raw is None:
                    raw = chunk
                text = _stringify_chunk_content(raw)
                if not text:
                    continue

                if accumulated_response and text.startswith(accumulated_response):
                    delta = text[len(accumulated_response):]
                    accumulated_response = text
                elif not accumulated_response:
                    delta = text
                    accumulated_response = text
                else:
                    delta = text
                    accumulated_response += text

                if not delta:
                    continue

                if token_count == 0:
                    elapsed = time.time() - start_time
                    logger.info("First chunk after %.3fs: '%s...'", elapsed, delta[:40])

                token_count += 1
                yield delta

            elapsed_total = time.time() - start_time
            logger.info(
                "Streaming complete. Chunks: %d, Total: %d chars, Time: %.2fs",
                token_count, len(accumulated_response), elapsed_total
            )

        except Exception as e:
            logger.error("Error during streaming: %s", e, exc_info=True)
            raise

        if rag_status == "indexing":
            yield "\n\n---\n⏳ **Note:** Annual Report indexing is in progress. This answer is based on financial data only. Qualitative insights will be available once indexing completes."
        elif rag_status == "error":
            yield "\n\n---\n⚠️ **Note:** Annual Report indexing encountered an error. This answer is based on financial data only."

    def compress_history(self, messages: list) -> str:
        """
        Compress a list of {role, content} message dicts into a summary string
        to use as conversation_summary on the next turn.
        """
        logger.info("Compressing %d messages into summary", len(messages))
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in messages
        )
        try:
            prompt_messages = self.summarize_prompt.invoke({"conversation_text": conversation_text})
            summary = self.router.invoke(prompt_messages)
            logger.info("Summary generated. Length: %d chars", len(summary))
            return summary
        except Exception as e:
            logger.error("Error during compression: %s", e, exc_info=True)
            raise

    def maybe_compress(self, messages: list) -> tuple[list, str]:
        """
        If messages exceed _MAX_MESSAGES, compress the oldest half into a summary.
        Returns (remaining_messages, summary_text).
        """
        if len(messages) <= _MAX_MESSAGES:
            return messages, ""

        split = len(messages) // 2
        old_messages = messages[:split]
        new_messages = messages[split:]
        logger.info("History exceeds limit (%d > %d). Compressing %d old messages...", len(messages), _MAX_MESSAGES, split)
        summary = self.compress_history(old_messages)
        return new_messages, summary
