"""
Custom exceptions for the Graphiti integration module.
"""


class GraphitiIntegrationError(Exception):
    """Base exception for all graphiti integration errors."""
    pass


class DatabaseError(GraphitiIntegrationError):
    """Error during database operations."""
    pass


class TransformationError(GraphitiIntegrationError):
    """Error during data transformation."""
    pass


class IngestionError(GraphitiIntegrationError):
    """Error during Graphiti ingestion."""
    
    def __init__(self, message: str, failed_records: list | None = None):
        super().__init__(message)
        self.failed_records = failed_records or []
