"""Orchestrator: manages LLM call flow and chaining."""

from llm.narrative_generator import NarrativeGenerator

class LLMOrchestrator:
    def __init__(self):
        self.generator = NarrativeGenerator()
        
    def analyze_company(self, data: dict, rag_context: str = "") -> str:
        """
        Orchestrates the process of passing processed data and context into the LLM chain.
        """
        narrative = self.generator.generate_narrative(
            financial_data=data,
            context=rag_context
        )
        return narrative
