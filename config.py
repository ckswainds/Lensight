"""Lensight — Global Configuration.
Centralizes env vars, file paths, model settings, and constants.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # LLM Settings
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google")
    LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    # RAG Settings
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "chroma")
    RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
    HUGGINGFACEHUB_API_TOKEN = os.getenv("HUGGINGFACEHUB_API_TOKEN")
    
    # LangSmith Observability & Tracing
    # Note: These are picked up automatically by LangChain for tracing
    LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "Lensight")
    LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
    LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

config = Config()
