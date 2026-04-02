"""Orchestrator: manages LLM call flow and chaining."""

import json
from llm.narrative_generator import NarrativeGenerator
from llm.prompt_builder import PromptBuilder
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from config import config

# Maximum number of messages before compressing history
_MAX_MESSAGES = 10


class LLMOrchestrator:
    def __init__(self):
        self.generator = NarrativeGenerator()

        # Shared LLM for chat and summarization
        self.chat_llm = ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            temperature=0.3,
            api_key=config.GEMINI_API_KEY
        )

        # Grounded chat chain
        self.chat_prompt = PromptBuilder.build_grounded_chat_prompt()
        self.chat_chain = self.chat_prompt | self.chat_llm | StrOutputParser()

        # Summarization chain (for memory compression)
        self.summarize_prompt = PromptBuilder.build_summarization_prompt()
        self.summarize_chain = self.summarize_prompt | self.chat_llm | StrOutputParser()

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
        simple_chain = simple_prompt | self.chat_llm | StrOutputParser()
        return simple_chain.invoke({"context": rag_context or "No context.", "question": question})

    def chat_grounded(
        self,
        question: str,
        company: str,
        financial_summary: str,
        rag_context: str,
        conversation_summary: str = "",
    ) -> str:
        """
        Grounded chat using the strict system prompt.
        Uses computed ratios + RAG context. Refuses to fabricate.
        """
        return self.chat_chain.invoke({
            "company": company,
            "conversation_summary": conversation_summary or "No prior conversation.",
            "financial_summary": financial_summary,
            "rag_context": rag_context if rag_context else "No annual report context available.",
            "question": question,
        })

    def compress_history(self, messages: list) -> str:
        """
        Takes a list of {"role": ..., "content": ...} dicts and
        returns a compressed summary string to use as conversation_summary.
        """
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in messages
        )
        return self.summarize_chain.invoke({"conversation_text": conversation_text})

    def maybe_compress(self, messages: list) -> tuple[list, str]:
        """
        If messages exceed _MAX_MESSAGES, compress the oldest half into a summary.
        Returns (remaining_messages, summary_text).
        """
        if len(messages) <= _MAX_MESSAGES:
            return messages, ""

        # Compress the oldest half, keep the newest half live
        split = len(messages) // 2
        old_messages = messages[:split]
        new_messages = messages[split:]
        summary = self.compress_history(old_messages)
        return new_messages, summary
