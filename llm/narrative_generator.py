"""Narrative Generator: produces final fundamental analysis text."""

import json
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from llm.prompt_builder import PromptBuilder
from config import config

logger = logging.getLogger(__name__)

class NarrativeGenerator:
    def __init__(self):
        logger.info("[NARRATIVE] Initializing NarrativeGenerator")
        # Initialize Gemini LLM using our config
        self.llm = ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.GEMINI_API_KEY
        )
        self.prompt_template = PromptBuilder.build_financial_analysis_prompt()
        self.output_parser = StrOutputParser()
        
        # Build chain with run name and tags for LangSmith tracing
        self.chain = (
            self.prompt_template 
            | self.llm.with_config(run_name="financial_analysis_llm", tags=["narrative", "analysis"])
            | self.output_parser
        )
        logger.info("[NARRATIVE] NarrativeGenerator initialized with LangSmith tracing enabled")

    def generate_narrative(self, financial_data: dict, context: str = "") -> str:
        """
        Takes raw dictionary of financial data and optional RAG context
        and returns a markdown formatted narrative string.
        """
        logger.info("[NARRATIVE] Generating narrative report")
        financial_str = json.dumps(financial_data, indent=2)
        
        response_text = self.chain.invoke(
            {
                "financial_data": financial_str,
                "context": context if context else "No additional context provided."
            },
            {"run_name": "financial_analysis_flow", "tags": ["narrative", "report-generation"]}
        )
        
        logger.debug(f"[NARRATIVE] Narrative generated successfully, length: {len(response_text)} chars")
        return response_text
