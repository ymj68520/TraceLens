import logging
import json
import subprocess
from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

@register_extractor
class LevelDBExtractor(BaseExtractor):
    """
    Extracts key-value pairs from a LevelDB directory.
    To prevent large context consumption, it only samples the first 100 pairs.
    """
    def __init__(self, sample_size: int = 100):
        self.sample_size = sample_size
        
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import plyvel
        except ImportError:
            return "Error: plyvel library is not installed. Please install plyvel to analyze LevelDB databases."
            
        try:
            # Connect in read-only mode to prevent lock issues
            db = plyvel.DB(file_path, create_if_missing=False)
            
            result = [f"# LevelDB Summary\n"]
            result.append("### Sample Data:")
            result.append("| Key | Value |")
            result.append("| --- | --- |")
            
            count = 0
            for key, value in db:
                if count >= self.sample_size:
                    break
                    
                # Safe decode
                try:
                    k_str = key.decode('utf-8', errors='replace')
                except:
                    k_str = str(key)
                    
                try:
                    v_str = value.decode('utf-8', errors='replace')
                    # Try format as JSON string if possible
                    try:
                        v_json = json.loads(v_str)
                        v_str = json.dumps(v_json)[:200]
                    except:
                        pass
                except:
                    v_str = "[Binary Data]"
                    
                # Escape markdown table characters
                k_str = k_str.replace("|", "\\|").replace("\n", " ").replace("\r", "")
                v_str = v_str.replace("|", "\\|").replace("\n", " ").replace("\r", "")
                
                if len(k_str) > 100: k_str = k_str[:97] + "..."
                if len(v_str) > 200: v_str = v_str[:197] + "..."
                
                result.append(f"| `{k_str}` | {v_str} |")
                count += 1
                
            db.close()
            
            if count == self.sample_size:
                result.append(f"\n*(Showing first {self.sample_size} keys)*")
            elif count == 0:
                result.append("\n*(Database is empty)*")
                
            return "\n".join(result)
            
        except plyvel.Error as e:
            logger.error(f"LevelDB error processing {file_path}: {e}")
            return f"Error: Failed to open LevelDB directory. Ensure the path is a valid LevelDB directory and is not locked: {e}"
        except Exception as e:
            logger.error(f"Error parsing LevelDB {file_path}: {e}")
            raise


@register_extractor
class RedisExtractor(BaseExtractor):
    """
    Extracts key-value pairs from a Redis offline .rdb dump using rdbtools.
    """
    def __init__(self, sample_size: int = 100):
        self.sample_size = sample_size
        
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            result_process = subprocess.run(
                ["rdb", "--command", "json", file_path],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result_process.returncode != 0:
                logger.warning(f"rdbtools failed to parse {file_path}. Error: {result_process.stderr[:200]}")
                return f"Error: Failed to parse Redis Database (rdbtools error): {result_process.stderr[:200]}"
                
            json_str = result_process.stdout.strip()
            
            if not json_str:
                return "# Redis Database Summary\n\n*(Database is empty)*\n"
                
            parsed_data = json.loads(json_str)
            
            result = [f"# Redis Database Summary\n"]
            result.append("### Sample Data:")
            result.append("| Key | Type | Value |")
            result.append("| --- | --- | --- |")
            
            count = 0
            
            if isinstance(parsed_data, list):
                items = parsed_data
            elif isinstance(parsed_data, dict):
                items = []
                for db_idx, db_content in parsed_data.items():
                    if isinstance(db_content, dict):
                        for k, v in db_content.items():
                            items.append({"key": k, "type": type(v).__name__, "value": v})
                    else:
                        items.append({"key": db_idx, "type": type(db_content).__name__, "value": db_content})
            else:
                items = [{"key": "Data", "type": "unknown", "value": parsed_data}]

            for item in items:
                if count >= self.sample_size:
                    break
                    
                k_str = str(item.get("key", "Unknown"))
                type_str = str(item.get("type", "string"))
                v_str = str(item.get("value", ""))
                
                if len(v_str) > 200:
                    v_str = v_str[:197] + "..."
                    
                k_str = k_str.replace("|", "\\|").replace("\n", " ")
                v_str = v_str.replace("|", "\\|").replace("\n", " ").replace("\r", "")
                
                result.append(f"| `{k_str}` | `{type_str}` | {v_str} |")
                count += 1
                
            if count == self.sample_size:
                result.append(f"\n*(Showing first {self.sample_size} keys)*")
            elif count == 0:
                result.append("\n*(Database is empty)*")
                
            return "\n".join(result)
            
        except subprocess.TimeoutExpired:
            return "Error: Timeout parsing Redis RDB file. File may be too large for offline AI extraction."
        except json.JSONDecodeError:
            return "Error: Internal Failure parsing rdbtools JSON output."
        except Exception as e:
            logger.error(f"Error parsing Redis {file_path}: {e}")
            return f"Error: Failed to extract Redis data: {e}"


@register_extractor
class MongoBsonExtractor(BaseExtractor):
    """
    Extracts documents from an offline MongoDB .bson dump file natively using pymongo's bson module.
    """
    def __init__(self, sample_size: int = 50):
        self.sample_size = sample_size
        
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import bson
            from bson.json_util import dumps
        except ImportError:
            return "Error: pymongo library is not installed. Please install pymongo to analyze MongoDB BSON files."
            
        try:
            result = [f"# MongoDB BSON Dump Summary (`{file_path.split('/')[-1]}`)\n"]
            result.append("### Sample Documents:\n")
            result.append("```json")
            
            count = 0
            with open(file_path, "rb") as f:
                for doc in bson.decode_file_iter(f):
                    if count >= self.sample_size:
                        break
                        
                    doc_json = dumps(doc, indent=2)
                    
                    if len(doc_json) > 1000:
                        doc_json = doc_json[:997] + "\n  ... (truncated)"
                        
                    result.append(doc_json)
                    result.append(",")
                    count += 1
                    
            if result[-1] == ",":
                result.pop() # Remove trailing comma
                
            result.append("```\n")
            
            if count == self.sample_size:
                result.append(f"\n*(Showing first {self.sample_size} BSON documents)*")
            elif count == 0:
                result.append("\n*(BSON file is empty)*")
                
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error parsing MongoDB BSON {file_path}: {e}")
            return f"Error: Failed to process BSON Dump: {e}"
