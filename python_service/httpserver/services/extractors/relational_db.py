import logging
from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

@register_extractor
class SQLiteExtractor(BaseExtractor):
    """
    Extracts schema and a sample of rows from SQLite databases.
    """
    def __init__(self, sample_size: int = 50):
        self.sample_size = sample_size
        
    async def extract_to_markdown(self, file_path: str) -> str:
        import sqlite3
        
        try:
            # Connect in read-only mode to prevent lock issues
            uri_path = f"file:{file_path}?mode=ro"
            conn = sqlite3.connect(uri_path, uri=True)
            cursor = conn.cursor()
            
            result = ["# SQLite Database Summary\n"]
            
            # 1. Extract Schema
            cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()
            
            if not tables:
                result.append("No tables found or empty database.\n")
                conn.close()
                return "\n".join(result)
                
            result.append(f"**Total Tables:** {len(tables)}\n")
            
            for table_name, schema_sql in tables:
                result.append(f"## Table: `{table_name}`")
                
                # Add schema
                result.append("### Schema:")
                result.append("```sql")
                result.append(schema_sql if schema_sql else "N/A")
                result.append("```\n")
                
                # 2. Extract Data Sample
                try:
                    cursor.execute(f"SELECT * FROM \"{table_name}\" LIMIT {self.sample_size}")
                    rows = cursor.fetchall()
                    
                    if not rows:
                        result.append("*No data in this table.*\n")
                        continue
                        
                    # Get column names
                    col_names = [description[0] for description in cursor.description]
                    
                    # Markdown Table Header
                    result.append("### Sample Data:")
                    header_line = "| " + " | ".join(col_names) + " |"
                    separator_line = "| " + " | ".join(["---"] * len(col_names)) + " |"
                    result.append(header_line)
                    result.append(separator_line)
                    
                    # Markdown Table Rows
                    for row in rows:
                        safe_row = []
                        for cell in row:
                            if cell is None:
                                safe_row.append("NULL")
                            elif isinstance(cell, bytes):
                                safe_row.append("[BLOB]")
                            else:
                                cell_str = str(cell).replace("|", "\\|").replace("\n", " ") # Escape pipe and newline
                                if len(cell_str) > 100:
                                    cell_str = cell_str[:97] + "..."
                                safe_row.append(cell_str)
                        row_line = "| " + " | ".join(safe_row) + " |"
                        result.append(row_line)
                    
                    if len(rows) == self.sample_size:
                        result.append(f"\n*(Showing only the first {self.sample_size} rows)*\n")
                    else:
                        result.append("\n")
                        
                except Exception as e:
                    logger.warning(f"Failed to extract rows from {table_name}: {e}")
                    result.append(f"*Failed to extract data: {e}*\n")
                    
            conn.close()
            return "\n".join(result)
            
        except sqlite3.Error as e:
            logger.error(f"SQLite error processing {file_path}: {e}")
            return f"Error: Failed to process SQLite database: {e}"
        except Exception as e:
            logger.error(f"Error parsing SQLite DB {file_path}: {e}")
            raise


@register_extractor
class SqlDumpExtractor(BaseExtractor):
    """
    Extracts the beginning of a SQL dump file. Since SQL dumps can be massive
    we only extract the first N lines.
    """
    def __init__(self, max_lines: int = 500):
        self.max_lines = max_lines
        
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            result = [f"# SQL Dump Summary (`{file_path.split('/')[-1]}`)\n"]
            result.append("```sql")
            
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for idx, line in enumerate(f):
                    if idx >= self.max_lines:
                        break
                    result.append(line.rstrip())
                    
            result.append("```\n")
            result.append(f"\n*(Truncated to first {self.max_lines} lines)*")
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error parsing SQL Dump {file_path}: {e}")
            return f"Error: Failed to read SQL Dump file: {e}"
