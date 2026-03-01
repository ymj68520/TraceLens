# Graphiti Integration Module
#
# This module bridges the forensics SQLite database (containing LLM-generated
# file descriptions) with Graphiti to build a RAG knowledge graph.

from .config import GraphitiConfig
from .database_reader import (
    ForensicsDatabase,
    FileRecord,
    EventsDatabase,
    WindowsDatabase,
    LinuxDatabase,
    AndroidDatabase,
    ForensicsDatabaseFactory,
    DiscoveredDatabases,
)
from .toon_transformer import TOONTransformer, EpisodeData, ForensicEpisodeTransformer
from .exceptions import (
    GraphitiIntegrationError,
    DatabaseError,
    TransformationError,
    IngestionError,
)

# Lazy import for graphiti_ingestor (requires graphiti_core which may not be installed)
def _get_graphiti_ingestor():
    from .graphiti_ingestor import GraphitiIngestor
    return GraphitiIngestor

def _get_graphiti_pipeline():
    from .pipeline import GraphitiPipeline, run_pipeline, MultiSourcePipeline, run_multi_source_pipeline
    return GraphitiPipeline, run_pipeline, MultiSourcePipeline, run_multi_source_pipeline

__all__ = [
    # Config
    "GraphitiConfig",
    # Database
    "ForensicsDatabase",
    "FileRecord",
    "EventsDatabase",
    "WindowsDatabase",
    "LinuxDatabase",
    "AndroidDatabase",
    "ForensicsDatabaseFactory",
    "DiscoveredDatabases",
    # Transformer
    "TOONTransformer",
    "EpisodeData",
    "ForensicEpisodeTransformer",
    # Ingestor (lazy)
    "GraphitiIngestor",
    # Pipeline (lazy)
    "GraphitiPipeline",
    "run_pipeline",
    "MultiSourcePipeline",
    "run_multi_source_pipeline",
    # Exceptions
    "GraphitiIntegrationError",
    "DatabaseError",
    "TransformationError",
    "IngestionError",
]

__version__ = "0.2.0"

# Lazy loading support
def __getattr__(name):
    if name == "GraphitiIngestor":
        return _get_graphiti_ingestor()
    elif name == "GraphitiPipeline":
        pipeline_mod = _get_graphiti_pipeline()
        return pipeline_mod[0]
    elif name == "run_pipeline":
        pipeline_mod = _get_graphiti_pipeline()
        return pipeline_mod[1]
    elif name == "MultiSourcePipeline":
        pipeline_mod = _get_graphiti_pipeline()
        return pipeline_mod[2]
    elif name == "run_multi_source_pipeline":
        pipeline_mod = _get_graphiti_pipeline()
        return pipeline_mod[3]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


