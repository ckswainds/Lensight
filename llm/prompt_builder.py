"""Prompt Builder: constructs dynamic prompts from ratio + RAG context."""

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

class PromptBuilder:

    @staticmethod
    def build_grounded_chat_prompt() -> ChatPromptTemplate:
        system_template = """You are a senior financial analyst assistant for {company}.

STRICT RULES — follow them exactly:
1. Answer ONLY using the financial data and annual report context provided below.
2. If neither source contains enough information, respond with EXACTLY:
   "I don't have enough information in the provided data to answer that reliably."
3. Never fabricate numbers, ratios, dates, or management quotes.
4. Professional tone. If using info from the Annual Report context, you MUST cite the page number if available (e.g., "[Page 12]").
5. REPORT AVAILABILITY: {report_status}

--- Prior Conversation Summary ---
{conversation_summary}

--- Financial Ratios & Trends ---
{financial_summary}

--- Annual Report Context (retrieved chunks) ---
{rag_context}"""

        human_template = "{question}"

        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(human_template)
        ])

    @staticmethod
    def build_summarization_prompt() -> ChatPromptTemplate:
        system_template = "You are a concise summarizer. Summarize the following financial Q&A conversation history into a compact paragraph preserving the key facts, numbers, and conclusions discussed."
        human_template = "{conversation_text}"
        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(human_template)
        ])

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
