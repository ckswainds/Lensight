"""Narrative Generator: produces final fundamental analysis text."""

import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from llm.prompt_builder import PromptBuilder
from config import config

class NarrativeGenerator:
    def __init__(self):
        # Initialize Gemini LLM using our config
        self.llm = ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.GEMINI_API_KEY
        )
        self.prompt_template = PromptBuilder.build_financial_analysis_prompt()
        self.output_parser = StrOutputParser()
        
        # Build standard chain
        self.chain = self.prompt_template | self.llm | self.output_parser

    def generate_narrative(self, financial_data: dict, context: str = "") -> str:
        """
        Takes raw dictionary of financial data and optional RAG context
        and returns a markdown formatted narrative string.
        """
        financial_str = json.dumps(financial_data, indent=2)
        
        response_text = self.chain.invoke({
            "financial_data": financial_str,
            "context": context if context else "No additional context provided."
        })
        
        return response_text
