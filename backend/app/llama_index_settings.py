from llama_index.core import Settings
from llama_index.core.settings import _Settings
from llama_index.llms.gemini import Gemini
from llama_index.embeddings.gemini import GeminiEmbedding
from app.core.config import settings
from llama_index.core.node_parser import SentenceSplitter

from app.chat.constants import (
    NODE_PARSER_CHUNK_OVERLAP,
    NODE_PARSER_CHUNK_SIZE,
)

def _setup_llama_index_settings() -> _Settings:
    Settings.llm = Gemini(
        model=settings.GEMINI_CHAT_LLM_NAME,
        api_key=settings.GOOGLE_API_KEY,
        timeout=120,  # Bound runaway Gemini calls; prevents silent 504s
    )
    Settings.embed_model = GeminiEmbedding(
        model_name=settings.GEMINI_EMBEDDING_MODEL_NAME,
        api_key=settings.GOOGLE_API_KEY,
        timeout=60,  # Embedding calls should be fast; fail early if not
    )
    Settings.node_parser = SentenceSplitter(
        chunk_size=NODE_PARSER_CHUNK_SIZE,
        chunk_overlap=NODE_PARSER_CHUNK_OVERLAP,
    )
    return Settings
