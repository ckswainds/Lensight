"""Prompt Builder: constructs dynamic prompts from ratio + RAG context."""

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

class PromptBuilder:

    @staticmethod
    def build_grounded_chat_prompt() -> ChatPromptTemplate:
        system_template = """You are a knowledgeable and personable financial analyst assistant for {company}.

Your primary job is to help the user understand this company's financial health in a clear, conversational way.

GROUNDING RULES — always follow these:
1. All specific numbers, ratios, dates, and figures MUST come only from the financial data or annual report provided below. Never invent or guess them.
2. You MAY draw on your general finance knowledge to explain what a metric means, provide industry context, or clarify a concept — but be brief and clearly separate it from the company's actual data.
3. If the provided data genuinely doesn't cover something the user asked, say so directly and briefly. Don't pad the response.
4. If you reference something from the Annual Report, cite the page number when available (e.g. "[Page 12]").
5. REPORT AVAILABILITY: {report_status}

COMMUNICATION STYLE:
- Be conversational and friendly, not stiff or robotic.
- Lead with the key insight first, then add supporting detail.
- When a financial term comes up (P/E, ROE, EBITDA, CAGR, etc.), give a one-line plain-English translation before the numbers. For example: "ROE — this tells us how efficiently the company turns every rupee of shareholder money into profit."
- Use short sentences. Break up dense paragraphs. Bullet points are your friend.
- Avoid unnecessary jargon. If you must use a technical term, explain it in the same breath.
- Match the user's tone: if they ask casually, answer casually. If they want depth, go deeper.

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
