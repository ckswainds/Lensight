"""Narrative Generator: produces final fundamental analysis text."""

import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from llm.prompt_builder import PromptBuilder
from llm.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class NarrativeGenerator:
    def __init__(self):
        self.router = LLMRouter()
        self.prompt_template = PromptBuilder.build_financial_analysis_prompt()

    def generate_narrative(self, financial_data: dict, context: str = "") -> str:
        """
        Generate a markdown-formatted fundamental analysis narrative from
        financial data and optional RAG context.
        """
        logger.info("Generating narrative report")
        financial_str = PromptBuilder.build_financial_summary_text(financial_data)

        prompt_messages = self.prompt_template.invoke({
            "financial_data": financial_str,
            "context": context if context else "No additional context provided."
        })
        response_text = self.router.invoke(prompt_messages)

        logger.debug("Narrative generated. Length: %d chars", len(response_text))
        return response_text
