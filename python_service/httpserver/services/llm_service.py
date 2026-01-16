"""
LLM Service - AI analysis integration.

This service provides LLM-based file analysis:
- Single file analysis
- Batch analysis with background processing
- Model status checking

Supports both text and vision models via OpenAI-compatible API.
"""

import asyncio
import base64
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for LLM-based analysis operations.
    
    Supports:
    - Text analysis via text models
    - Image analysis via vision models
    - Batch processing with background jobs
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize the LLM service.
        
        Args:
            settings: Application settings.
        """
        self.settings = settings
        self._text_client: Optional[httpx.AsyncClient] = None
        self._vision_client: Optional[httpx.AsyncClient] = None
        self._initialized = False
        
        # Background job tracking
        self._jobs: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self):
        """Initialize HTTP clients for LLM APIs."""
        if self._initialized:
            return
        
        # Text model client
        self._text_client = httpx.AsyncClient(
            base_url=self.settings.llm_text_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )
        
        # Vision model client
        self._vision_client = httpx.AsyncClient(
            base_url=self.settings.llm_vision_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )
        
        self._initialized = True
        logger.info("LLM service initialized")
    
    async def shutdown(self):
        """Close HTTP clients."""
        if self._text_client:
            await self._text_client.aclose()
            self._text_client = None
        
        if self._vision_client:
            await self._vision_client.aclose()
            self._vision_client = None
        
        self._initialized = False
    
    async def health_check(self) -> bool:
        """
        Check if LLM service is healthy.
        
        Returns:
            True if at least one model is available.
        """
        text_ok = await self.check_model_status("text")
        vision_ok = await self.check_model_status("vision")
        return text_ok or vision_ok
    
    async def check_model_status(self, model_type: str) -> bool:
        """
        Check if a specific model is available.
        
        Args:
            model_type: 'text' or 'vision'.
        
        Returns:
            True if model is available.
        """
        try:
            if model_type == "text":
                client = self._text_client or httpx.AsyncClient(
                    base_url=self.settings.llm_text_base_url,
                    timeout=httpx.Timeout(10.0),
                )
            else:
                client = self._vision_client or httpx.AsyncClient(
                    base_url=self.settings.llm_vision_base_url,
                    timeout=httpx.Timeout(10.0),
                )
            
            response = await client.get("/v1/models")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Model status check failed for {model_type}: {e}")
            return False
    
    async def read_file_content(self, file_path: str) -> str:
        """
        Read content from a file.
        
        Args:
            file_path: Path to the file.
        
        Returns:
            File content as string.
        
        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Try to read as text
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            # Truncate if too long
            max_len = self.settings.file_analysis_max_content_limit
            if len(content) > max_len:
                content = content[:max_len] + "\n... [truncated]"
            return content
        except Exception as e:
            logger.warning(f"Failed to read file as text: {e}")
            raise
    
    async def analyze(
        self,
        content: str,
        model_type: str = "text",
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze content using LLM.
        
        Args:
            content: Content to analyze.
            model_type: 'text' or 'vision'.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).
        
        Returns:
            Analysis result dict.
        """
        # Select model settings
        if model_type == "text":
            client = self._text_client or httpx.AsyncClient(
                base_url=self.settings.llm_text_base_url,
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
            )
            model = self.settings.llm_text_model
            default_max_tokens = self.settings.llm_text_max_tokens
            default_temperature = self.settings.llm_text_temperature
        else:
            client = self._vision_client or httpx.AsyncClient(
                base_url=self.settings.llm_vision_base_url,
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
            )
            model = self.settings.llm_vision_model
            default_max_tokens = self.settings.llm_vision_max_tokens
            default_temperature = self.settings.llm_vision_temperature
        
        # Build prompt
        system_prompt = """You are a digital forensics expert analyzing file content.
Provide a concise analysis including:
1. Brief description of the content
2. Key findings or notable information
3. Potential forensic significance
4. Any suspicious patterns or indicators

Be specific and factual in your analysis."""
        
        user_prompt = prompt or f"Analyze the following file content:\n\n{content}"
        
        # Make API request
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": max_tokens or default_max_tokens,
                    "temperature": temperature or default_temperature,
                },
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {},
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Extract response
            analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)
            
            return {
                "analysis": {
                    "description": analysis_text,
                    "model_type": model_type,
                },
                "model": model,
                "tokens_used": tokens_used,
            }
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            raise
    
    async def analyze_image(
        self,
        image_data: bytes,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an image using vision model.
        
        Args:
            image_data: Image binary data.
            prompt: Custom prompt (optional).
        
        Returns:
            Analysis result dict.
        """
        # Encode image to base64
        image_b64 = base64.b64encode(image_data).decode("utf-8")
        
        client = self._vision_client or httpx.AsyncClient(
            base_url=self.settings.llm_vision_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )
        
        system_prompt = """You are a digital forensics expert analyzing image content.
Describe what you see in the image and note any potentially relevant forensic details."""
        
        user_prompt = prompt or "Analyze this image for forensic significance."
        
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": self.settings.llm_vision_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}"
                                    },
                                },
                            ],
                        },
                    ],
                    "max_tokens": self.settings.llm_vision_max_tokens,
                    "temperature": self.settings.llm_vision_temperature,
                },
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {},
            )
            response.raise_for_status()
            
            result = response.json()
            analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)
            
            return {
                "analysis": {
                    "description": analysis_text,
                    "model_type": "vision",
                },
                "model": self.settings.llm_vision_model,
                "tokens_used": tokens_used,
            }
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            raise
    
    async def start_batch_analysis(
        self,
        files: List[Dict[str, Any]],
        model_type: str = "text",
    ) -> str:
        """
        Start batch analysis of files.
        
        Args:
            files: List of file info dicts with 'path' key.
            model_type: 'text' or 'vision'.
        
        Returns:
            Job ID for tracking progress.
        """
        job_id = str(uuid.uuid4())
        
        self._jobs[job_id] = {
            "status": "running",
            "progress": 0.0,
            "files_processed": 0,
            "files_total": len(files),
            "results": [],
            "errors": [],
        }
        
        # Start background task
        asyncio.create_task(self._run_batch_analysis(job_id, files, model_type))
        
        return job_id
    
    async def _run_batch_analysis(
        self,
        job_id: str,
        files: List[Dict[str, Any]],
        model_type: str,
    ):
        """Run batch analysis in background."""
        try:
            total = len(files)
            for i, file_info in enumerate(files):
                try:
                    file_path = file_info.get("path") or file_info.get("file_path")
                    if not file_path:
                        continue
                    
                    content = await self.read_file_content(file_path)
                    result = await self.analyze(content, model_type)
                    
                    self._jobs[job_id]["results"].append({
                        "file_path": file_path,
                        "analysis": result.get("analysis"),
                    })
                except Exception as e:
                    self._jobs[job_id]["errors"].append(f"{file_path}: {str(e)}")
                
                self._jobs[job_id]["files_processed"] = i + 1
                self._jobs[job_id]["progress"] = (i + 1) / total
            
            self._jobs[job_id]["status"] = "completed"
        except Exception as e:
            logger.error(f"Batch analysis job {job_id} failed: {e}")
            self._jobs[job_id]["status"] = "failed"
            self._jobs[job_id]["errors"].append(str(e))
    
    async def get_batch_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a batch analysis job."""
        return self._jobs.get(job_id)
    
    async def get_status(self) -> Dict[str, Any]:
        """
        Get the status of LLM services.
        
        Returns:
            Status information dict.
        """
        text_available = await self.check_model_status("text")
        vision_available = await self.check_model_status("vision")
        
        return {
            "status": "available" if (text_available or vision_available) else "unavailable",
            "text_model": {
                "name": self.settings.llm_text_model,
                "base_url": self.settings.llm_text_base_url,
                "available": text_available,
            },
            "vision_model": {
                "name": self.settings.llm_vision_model,
                "base_url": self.settings.llm_vision_base_url,
                "available": vision_available,
            },
        }
