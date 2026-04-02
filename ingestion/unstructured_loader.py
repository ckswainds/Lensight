"""Unstructured Loader: PDF/HTML  →  text chunks for RAG."""

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

class UnstructuredLoader:
    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 150):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )

    def load_pdf(self, file_path: str) -> list:
        """
        Loads a PDF file and splits it into manageable text chunks.
        """
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        chunks = self.text_splitter.split_documents(docs)
        return chunks
