# Graphiti Integration Module
#
# This module bridges the forensics SQLite database (containing LLM-generated
# file descriptions) with Graphiti to build a RAG knowledge graph.

from .config import GraphitiConfig
from .database_reader import ForensicsDatabase, FileRecord
from .toon_transformer import TOONTransformer, EpisodeData
from .graphiti_ingestor import GraphitiIngestor
from .pipeline import GraphitiPipeline, run_pipeline
from .exceptions import (
    GraphitiIntegrationError,
    DatabaseError,
    TransformationError,
    IngestionError,
)

__all__ = [
    # Config
    "GraphitiConfig",
    # Database
    "ForensicsDatabase",
    "FileRecord",
    # Transformer
    "TOONTransformer",
    "EpisodeData",
    # Ingestor
    "GraphitiIngestor",
    # Pipeline
    "GraphitiPipeline",
    "run_pipeline",
    # Exceptions
    "GraphitiIntegrationError",
    "DatabaseError",
    "TransformationError",
    "IngestionError",
]

__version__ = "0.1.0"
