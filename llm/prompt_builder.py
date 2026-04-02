"""Prompt Builder: constructs dynamic prompts from ratio + RAG context."""

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

class PromptBuilder:
    @staticmethod
    def build_financial_analysis_prompt() -> ChatPromptTemplate:
        system_template = """You are an expert equity research analyst specializing in Indian equities.
Your task is to analyze financial ratios, trends, and provided context documents to generate professional, insightful, and concise narratives.
Do not use generic fluff. Focus on key drivers, risks, and profitability trends."""
        
        human_template = """Please provide a fundamental analysis summary based on the following financial data.

Financial Ratios & Trends:
{financial_data}

Additional Context (Annual Reports, News, etc.):
{context}

Generate a structured narrative report covering:
1. Overall Health & Performance
2. Profitability & Growth Trends
3. Solvency & Liquidity Risks
4. Final Outlook"""

        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(human_template)
        ])
