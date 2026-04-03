"""Embedder: text → vector conversion via HuggingFace InferenceClient with batch processing."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.embeddings import Embeddings
from huggingface_hub import InferenceClient
from config import config

logger = logging.getLogger(__name__)


class HFInferenceEmbeddings(Embeddings):
    """Langchain-compatible embedder using the official huggingface_hub InferenceClient with batch & parallel support."""

    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        logger.info("[EMBEDDER] Initializing HFInferenceEmbeddings")
        self.client = InferenceClient(
            provider="hf-inference",
            api_key=config.HUGGINGFACEHUB_API_TOKEN
        )
        self.model = config.EMBEDDING_MODEL
        self.batch_size = batch_size  # Embed this many texts per API call
        self.num_workers = num_workers  # Parallel workers
        logger.info(f"[EMBEDDER] Configured with batch_size={batch_size}, workers={num_workers}, model={self.model}")

    def _embed_batch(self, texts: list) -> list:
        """Embed a batch of texts in a single API call."""
        if not texts:
            return []
        logger.debug(f"[EMBEDDER] Embedding batch of {len(texts)} text(s)")
        vectors = []
        for text in texts:
            result = self.client.feature_extraction(text, model=self.model)
            vectors.append(result.tolist())
        return vectors

    def _embed_parallel(self, texts: list) -> list:
        """Embed texts using parallel worker threads with batch API calls."""
        if not texts:
            return []
        
        logger.info(f"[EMBEDDER] Starting parallel embedding for {len(texts)} texts with {self.num_workers} workers")
        
        # Split texts into batches
        batches = [texts[i:i + self.batch_size] for i in range(0, len(texts), self.batch_size)]
        logger.debug(f"[EMBEDDER] Split into {len(batches)} batches of size <= {self.batch_size}")
        
        all_vectors = []
        completed = 0
        
        # Process batches in parallel
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = {executor.submit(self._embed_batch, batch): i for i, batch in enumerate(batches)}
            
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    batch_vectors = future.result()
                    all_vectors.extend(batch_vectors)
                    completed += 1
                    logger.debug(f"[EMBEDDER] Batch {completed}/{len(batches)} completed ({completed*100//len(batches)}%)")
                except Exception as e:
                    logger.error(f"[EMBEDDER] Error embedding batch {batch_idx}: {e}", exc_info=True)
                    raise
        
        logger.info(f"[EMBEDDER] Parallel embedding complete. Total vectors: {len(all_vectors)}")
        return all_vectors

    def embed_documents(self, texts: list) -> list:
        logger.info(f"[EMBEDDER] Embedding {len(texts)} document(s) with parallel processing")
        if len(texts) > self.batch_size * 2:
            # Use parallel for larger batches
            return self._embed_parallel(texts)
        else:
            # Use simple batch for small sets
            return self._embed_batch(texts)

    def embed_query(self, text: str) -> list:
        logger.debug(f"[EMBEDDER] Embedding single query")
        return self._embed_batch([text])[0]


class Embedder:
    def __init__(self, batch_size: int = 10, num_workers: int = 4):
        logger.info("[EMBEDDER] Initializing Embedder")
        self.embeddings = HFInferenceEmbeddings(batch_size=batch_size, num_workers=num_workers)
        logger.info("[EMBEDDER] Embedder ready with batch and parallel processing")

    def get_embeddings_model(self):
        return self.embeddings
