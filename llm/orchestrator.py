"""Orchestrator: manages LLM call flow and chaining."""

from llm.narrative_generator import NarrativeGenerator
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from config import config

class LLMOrchestrator:
    def __init__(self):
        self.generator = NarrativeGenerator()
        
        # For general chat against RAG context
        self.chat_llm = ChatGoogleGenerativeAI(
            model=config.LLM_MODEL,
            temperature=0.4,
            api_key=config.GEMINI_API_KEY
        )
        self.chat_prompt = ChatPromptTemplate.from_template(
            "You are a helpful financial analyst assistant answering questions based on the provided Annual Report context.\n"
            "Context: {context}\n\n"
            "Question: {question}"
        )
        self.chat_chain = self.chat_prompt | self.chat_llm | StrOutputParser()
        
    def analyze_company(self, data: dict, rag_context: str = "") -> str:
        """
        Orchestrates the process of passing processed data and context into the LLM chain.
        """
        narrative = self.generator.generate_narrative(
            financial_data=data,
            context=rag_context
        )
        return narrative

    def chat_with_report(self, question: str, rag_context: str) -> str:
        """
        Uses the Chat Interface to answer a specific query against the retrieved RAG context.
        """
        return self.chat_chain.invoke({
            "context": rag_context if rag_context else "No context found.",
            "question": question
        })
