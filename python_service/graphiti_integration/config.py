"""
Configuration management for the Graphiti integration module.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class GraphitiConfig:
    """Configuration for Graphiti integration pipeline."""
    
    # Neo4j connection
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "11111111"
    
    # LLM settings (supports local OpenAI-compatible servers like LM Studio)
    llm_base_url: str = "http://192.168.31.199:1234/v1"
    llm_model: str = "openai/gpt-oss-20b"
    llm_api_key: str = "local"  # Placeholder for local servers
    
    # Embedder settings (can use local or OpenAI)
    embedder_base_url: Optional[str] = None  # None = use OpenAI
    embedder_model: str = "text-embedding-3-small"
    embedder_api_key: Optional[str] = None
    embedder_dim: int = 1536
    
    # Database settings
    db_path: Optional[str] = None
    
    # Batch processing
    batch_size: int = 50
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds
    
    # Filtering options
    filter_analyzed_only: bool = True  # Only process files with LLM analysis
    filter_categories: list[str] = field(default_factory=list)  # Empty = all
    
    # Graphiti group_id for organizing data
    group_id: str = "forensics_files"
    
    # Use local LLM (LM Studio / Ollama compatible)
    use_local_llm: bool = True
    
    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "GraphitiConfig":
        """
        Load configuration from environment variables.
        
        Args:
            env_path: Optional path to .env file. If not provided,
                      searches in current and parent directories.
        """
        if env_path:
            load_dotenv(env_path)
        else:
            # Try to find .env in current or parent directories
            current = Path.cwd()
            for _ in range(5):  # Search up to 5 levels
                env_file = current / ".env"
                if env_file.exists():
                    load_dotenv(env_file)
                    break
                current = current.parent
        
        # Get LLM base URL - use the text model URL from .env
        llm_base_url = os.getenv("LLM_TEXT_BASE_URL", "http://192.168.31.199:1234")
        if not llm_base_url.endswith("/v1"):
            llm_base_url = llm_base_url.rstrip("/") + "/v1"
        
        return cls(
            neo4j_uri=os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
            llm_base_url=llm_base_url,
            llm_model=os.getenv("LLM_TEXT_MODEL", "openai/gpt-oss-20b"),
            llm_api_key=os.getenv("LLM_API_KEY", "local"),
            embedder_api_key=os.getenv("OPENAI_API_KEY"),
            db_path=os.getenv("GRAPHITI_DB_PATH"),
            batch_size=int(os.getenv("GRAPHITI_BATCH_SIZE", "50")),
            max_retries=int(os.getenv("GRAPHITI_MAX_RETRIES", "3")),
            group_id=os.getenv("GRAPHITI_GROUP_ID", "forensics_files"),
            use_local_llm=os.getenv("GRAPHITI_USE_LOCAL_LLM", "true").lower() == "true",
        )
    
    def validate(self) -> list[str]:
        """
        Validate configuration and return list of errors.
        
        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []
        
        if not self.neo4j_uri:
            errors.append("Neo4j URI is required")
        
        if not self.neo4j_user:
            errors.append("Neo4j user is required")
        
        if not self.neo4j_password:
            errors.append("Neo4j password is required")
        
        if self.use_local_llm:
            if not self.llm_base_url:
                errors.append("LLM base URL is required for local LLM")
            if not self.llm_model:
                errors.append("LLM model name is required for local LLM")
        else:
            if not self.embedder_api_key:
                errors.append("OpenAI API key is required when not using local LLM")
        
        if self.db_path and not Path(self.db_path).exists():
            errors.append(f"Database path does not exist: {self.db_path}")
        
        if self.batch_size < 1:
            errors.append("Batch size must be at least 1")
        
        return errors

