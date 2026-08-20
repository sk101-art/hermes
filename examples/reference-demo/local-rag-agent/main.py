import fastapi
import uvicorn
from sentence_transformers import SentenceTransformer
import chromadb
import torch

app = fastapi.FastAPI(title="Local RAG Agent")
