import os
from dotenv import load_dotenv

load_dotenv()

from llm.orchestrator import LLMOrchestrator

def test_gemini_api():
    print("Testing Gemini API through Lensight Orchestrator...")
    try:
        orchestrator = LLMOrchestrator()
        print(f"Loaded LLM Model Configuration: {orchestrator.chat_llm.model}")
        response = orchestrator.chat_with_report(
            question="Respond with exactly 'connection verified'.",
            rag_context=""
        )
        print(f"✅ Gemini API Success! Response: {response}")
    except Exception as e:
        print(f"❌ Gemini API Failed!\nError Details: {e}")

def test_raw_hf_api():
    print("\nTesting Hugging Face Embeddings API (via InferenceClient)...")
    from rag.embedder import Embedder
    try:
        embedder = Embedder()
        model = embedder.get_embeddings_model()
        test_vector = model.embed_query("This is a mathematical test.")
        size = len(test_vector)
        if size > 0:
            print(f"✅ Hugging Face API Success! Extracted a vector of size {size}")
        else:
            print("❌ Hugging Face API returned an empty vector.")
    except Exception as e:
        print(f"❌ Hugging Face API Failed!\nError Details: {e}")

if __name__ == "__main__":
    test_gemini_api()
    test_raw_hf_api()