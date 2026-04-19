"""Orchestrator: manages LLM call flow and chaining."""

import json
import logging
from typing import Any

from langsmith import traceable

from llm.narrative_generator import NarrativeGenerator
from llm.llm_router import LLMRouter
from llm.prompt_builder import PromptBuilder
from config import config

logger = logging.getLogger(__name__)

# Maximum number of messages before compressing history
_MAX_MESSAGES = 10


def _stringify_chunk_content(content: Any) -> str:
    """
    LangChain / Gemini stream chunks may use str, list[str], or list[dict] blocks.
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
        logger.info("[ORCHESTRATOR] Initializing LLMOrchestrator")
        self.generator = NarrativeGenerator()

        # Shared LLM router for chat and summarization
        self.router = LLMRouter()
        
        # We only need prompts now, the router encapsulates the LLM and parser
        self.chat_prompt = PromptBuilder.build_grounded_chat_prompt()
        self.summarize_prompt = PromptBuilder.build_summarization_prompt()
        
        logger.info("[ORCHESTRATOR] LLMOrchestrator initialized successfully with router")

    def analyze_company(self, data: dict, rag_context: str = "") -> str:
        """Generate a full qualitative narrative report from financial data."""
        return self.generator.generate_narrative(
            financial_data=data,
            context=rag_context
        )

    def chat_with_report(self, question: str, rag_context: str) -> str:
        """
        Legacy simple chat — used by tests.
        """
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
        Grounded chat using the strict system prompt.
        Uses computed ratios + RAG context. Refuses to fabricate.
        
        Parameters
        ----------
        rag_status : str
            One of: "idle", "indexing", "ready", "error"
            - "ready": Annual Report is indexed and available
            - "indexing": Annual Report is still being processed
            - "idle": No annual report uploaded
            - "error": Indexing failed
        """
        logger.info(f"[CHAT] Starting chat_grounded for {company}. Question: {question[:50]}...")
        logger.debug(f"[CHAT] RAG Status: {rag_status}, Summary length: {len(conversation_summary)}")
        
        # Adaptive report status message based on RAG state
        if rag_status == "ready":
            report_status = "Annual Report indexing is complete. Use report context specifically for quality/qualitative insights."
            rag_ready_flag = True
        elif rag_status == "indexing":
            report_status = "Annual Report is currently being indexed. It will be available shortly. For now, answer using ONLY the financial ratios provided. Disclose that the report is still processing."
            rag_ready_flag = False
        elif rag_status == "error":
            report_status = "Annual Report indexing encountered an error. Answer using ONLY the financial ratios provided. Disclose that the report become unavailable."
            rag_ready_flag = False
        else:  # idle or unknown
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
            logger.info(f"[CHAT] Response generated successfully. Length: {len(response)} chars")
        except Exception as e:
            logger.error(f"[CHAT] Error during chat_grounded: {str(e)}", exc_info=True)
            raise
        
        # Add adaptive disclaimer based on RAG status
        if rag_status == "indexing":
            disclaimer = "\n\n---\n⏳ **Note:** Annual Report indexing is in progress. This answer is based on financial data only. Qualitative insights from the report will be available once indexing completes."
            response = response + disclaimer
        elif rag_status == "idle":
            # No disclaimer needed for idle state - message is already clear
            pass
        elif rag_status == "error":
            disclaimer = "\n\n---\n⚠️ **Note:** Annual Report indexing encountered an error. This answer is based on financial data only."
            response = response + disclaimer
        
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
        Streaming version of chat_grounded.
        Yields tokens as they arrive from the LLM.
        Streams DIRECTLY from LLM (bypassing StrOutputParser to ensure real-time streaming).
        
        Parameters
        ----------
        rag_status : str
            One of: "idle", "indexing", "ready", "error"
        """
        logger.info(f"[STREAM] Starting chat_grounded_stream for {company}. Question: {question[:50]}...")
        logger.debug(f"[STREAM] RAG Status: {rag_status}, Conversation history length: {len(conversation_summary)}")
        
        # Adaptive report status message based on RAG state
        if rag_status == "ready":
            report_status = "Annual Report indexing is complete. Use report context specifically for quality/qualitative insights."
            rag_ready_flag = True
        elif rag_status == "indexing":
            report_status = "Annual Report is currently being indexed. It will be available shortly. For now, answer using ONLY the financial ratios provided. Disclose that the report is still processing."
            rag_ready_flag = False
        elif rag_status == "error":
            report_status = "Annual Report indexing encountered an error. Answer using ONLY the financial ratios provided. Disclose that the report became unavailable."
            rag_ready_flag = False
        else:  # idle or unknown
            report_status = "No annual report was uploaded. Answer using ONLY the financial ratios provided. Clarify that insights from an annual report are not available."
            rag_ready_flag = False

        try:
            import time
            
            # Build prompt
            prompt_input = {
                "company": company,
                "conversation_summary": conversation_summary or "No prior conversation.",
                "financial_summary": financial_summary,
                "report_status": report_status,
                "rag_context": rag_context if (rag_context and rag_ready_flag) else "No context available (no report uploaded).",
                "question": question,
            }
            
            # Get the prompt messages without the output parser
            prompt_messages = self.chat_prompt.invoke(prompt_input)
            
            token_count = 0
            start_time = time.time()
            first_token_time = None
            accumulated_response = ""

            # Gemini often sends *incremental* pieces; some providers send *cumulative* text.
            # Old logic assumed only cumulative (len(new) > len(old)), which drops most chunks.
            logger.debug("[STREAM] Starting LLM stream (cumulative + incremental chunk handling)")
            for chunk in self.router.stream(prompt_messages):
                raw = getattr(chunk, "content", None)
                if raw is None:
                    raw = chunk
                text = _stringify_chunk_content(raw)
                if not text:
                    continue

                if accumulated_response and text.startswith(accumulated_response):
                    delta = text[len(accumulated_response) :]
                    accumulated_response = text
                elif not accumulated_response:
                    delta = text
                    accumulated_response = text
                else:
                    # Incremental token / segment — append (does not repeat prior prefix)
                    delta = text
                    accumulated_response += text

                if not delta:
                    continue

                if token_count == 0:
                    first_token_time = time.time()
                    elapsed = first_token_time - start_time
                    logger.info(
                        f"[STREAM] ⚡ FIRST CHUNK after {elapsed:.3f}s, delta: '{delta[:40]}...'"
                    )

                token_count += 1
                yield delta

                if token_count % 25 == 0:
                    elapsed = time.time() - start_time
                    rate = len(accumulated_response) / (elapsed + 0.001)
                    logger.debug(
                        f"[STREAM] Chunk #{token_count}, accumulated: {len(accumulated_response)} chars, "
                        f"rate: {rate:.1f} chars/sec"
                    )
            
            elapsed_total = time.time() - start_time
            logger.info(f"[STREAM] ✓ Streaming complete. Chunks: {token_count}, Total: {len(accumulated_response)} chars, Time: {elapsed_total:.2f}s")
            
        except Exception as e:
            logger.error(f"[STREAM] Error during streaming: {str(e)}", exc_info=True)
            raise
        
        # Yield adaptive disclaimer after main response
        if rag_status == "indexing":
            disclaimer = "\n\n---\n⏳ **Note:** Annual Report indexing is in progress. This answer is based on financial data only. Qualitative insights will be available once indexing completes."
            for token in disclaimer:
                yield token
            logger.debug("[STREAM] Indexing note yielded")
        elif rag_status == "error":
            disclaimer = "\n\n---\n⚠️ **Note:** Annual Report indexing encountered an error. This answer is based on financial data only."
            for token in disclaimer:
                yield token
            logger.debug("[STREAM] Error note yielded")

    def compress_history(self, messages: list) -> str:
        """
        Takes a list of {"role": ..., "content": ...} dicts and
        returns a compressed summary string to use as conversation_summary.
        """
        logger.info(f"[COMPRESS] Compressing {len(messages)} messages into summary")
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in messages
        )
        try:
            prompt_messages = self.summarize_prompt.invoke({"conversation_text": conversation_text})
            summary = self.router.invoke(prompt_messages)
            logger.info(f"[COMPRESS] Summary generated. Length: {len(summary)} chars")
            return summary
        except Exception as e:
            logger.error(f"[COMPRESS] Error during compression: {str(e)}", exc_info=True)
            raise

    def maybe_compress(self, messages: list) -> tuple[list, str]:
        """
        If messages exceed _MAX_MESSAGES, compress the oldest half into a summary.
        Returns (remaining_messages, summary_text).
        """
        if len(messages) <= _MAX_MESSAGES:
            logger.debug(f"[COMPRESS] History has {len(messages)} messages (limit: {_MAX_MESSAGES}), no compression needed")
            return messages, ""

        # Compress the oldest half, keep the newest half live
        split = len(messages) // 2
        old_messages = messages[:split]
        new_messages = messages[split:]
        logger.info(f"[COMPRESS] History exceeds limit ({len(messages)} > {_MAX_MESSAGES}). Compressing {split} old messages...")
        summary = self.compress_history(old_messages)
        logger.info(f"[COMPRESS] Compression complete. Keeping {len(new_messages)} newest messages")
        return new_messages, summary
