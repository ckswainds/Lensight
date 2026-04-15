"""Embedder: text → vector conversion using Google Generative AI (Gemini) embeddings."""

import logging
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from config import config

logger = logging.getLogger(__name__)

class Embedder:
    """Provides a thread-safe, fast embedding model using the user's existing Gemini API key."""
    
    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        # We ignore batch_size and num_workers here because the GoogleGenerativeAIEmbeddings
        # client internally handles its own batching and optimized network requests.
        logger.info("[EMBEDDER] Initializing Google Generative AI Embedder")
        
        try:
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model="models/embedding-001",
                google_api_key=config.GEMINI_API_KEY
            )
            logger.info("[EMBEDDER] Embedder ready using Google Generative AI")
        except Exception as e:
            logger.error(f"[EMBEDDER] Failed to initialize Gemini Embeddings: {e}")
            raise

    def get_embeddings_model(self):
        return self.embeddings
