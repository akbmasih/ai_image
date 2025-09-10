# /ai/plugins/plugin_flux.py
# Flux 1 Schnell plugin for image generation using external API with caching

import httpx
import asyncio
import time
import base64
from typing import Dict, Any, Optional
from config import settings
from cache_manager import cache_manager
import logging

logger = logging.getLogger(__name__)

class FluxPlugin:
    def __init__(self):
        self.name = "flux"
        self.model = "flux-1-schnell"
        self.base_url = settings.flux_api_url
        self.timeout = 120  # 2 minutes timeout for image generation
        self.rate_limiter = {}
        
    def check_rate_limit(self, user_id: str) -> bool:
        """Rate limiting per user for image generation"""
        current_time = time.time()
        minute_window = current_time - 60
        
        if user_id not in self.rate_limiter:
            self.rate_limiter[user_id] = []
            
        # Clean old requests
        self.rate_limiter[user_id] = [
            req_time for req_time in self.rate_limiter[user_id] 
            if req_time > minute_window
        ]
        
        # Check limit (lower for image generation)
        if len(self.rate_limiter[user_id]) >= 5:  # 5 images per minute max
            return False
            
        # Add current request
        self.rate_limiter[user_id].append(current_time)
        return True
        
    async def process_request(self, request_data: Dict[Any, Any], user_id: str, 
                            force_refresh: bool = False) -> Dict[Any, Any]:
        """Process Flux image generation request with caching"""
        try:
            # Rate limiting check
            if not self.check_rate_limit(user_id):
                return {
                    "error": "Rate limit exceeded for image generation",
                    "error_type": "rate_limit",
                    "from_cache": False
                }
                
            # Generate cache key
            cache_key = cache_manager.generate_cache_key(request_data, user_id)
            
            # Check file cache if not force refresh
            if not force_refresh:
                cached_image = await cache_manager.get_file_cache(self.name, cache_key)
                if cached_image:
                    # Convert to base64 for response
                    image_base64 = base64.b64encode(cached_image).decode('utf-8')
                    return {
                        "image": f"data:image/png;base64,{image_base64}",
                        "model": self.model,
                        "from_cache": True,
                        "prompt": request_data.get("prompt", ""),
                        "format": "png"
                    }
                    
            # Validate required parameters
            prompt = request_data.get("prompt")
            if not prompt:
                return {
                    "error": "Prompt is required for image generation",
                    "error_type": "missing_prompt",
                    "from_cache": False
                }
                
            # Prepare request payload
            payload = {
                "prompt": prompt,
                "width": request_data.get("width", 1024),
                "height": request_data.get("height", 1024),
                "num_inference_steps": request_data.get("steps", 4),
                "guidance_scale": request_data.get("guidance_scale", 7.5),
                "seed": request_data.get("seed", -1)
            }
            
            # Make API call to Flux server
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/generate",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Flux API error: {response.status_code} - {response.text}")
                    return {
                        "error": f"Flux API error: {response.status_code}",
                        "error_type": "api_error",
                        "from_cache": False
                    }
                    
                response_data = response.json()
                
                # Check if generation was successful
                if "image_id" not in response_data:
                    return {
                        "error": "Image generation failed",
                        "error_type": "generation_failed",
                        "from_cache": False
                    }
                    
                # Get the generated image
                image_id = response_data["image_id"]
                image_response = await client.get(f"{self.base_url}/image/{image_id}")
                
                if image_response.status_code != 200:
                    return {
                        "error": "Failed to retrieve generated image",
                        "error_type": "image_retrieval_failed",
                        "from_cache": False
                    }
                    
                image_data = image_response.content
                
                # Cache the image
                await cache_manager.set_file_cache(
                    self.name, cache_key, image_data, "image/png"
                )
                
                # Convert to base64 for response
                image_base64 = base64.b64encode(image_data).decode('utf-8')
                
                result = {
                    "image": f"data:image/png;base64,{image_base64}",
                    "model": self.model,
                    "from_cache": False,
                    "prompt": prompt,
                    "format": "png",
                    "generation_time": response_data.get("generation_time"),
                    "parameters": {
                        "width": payload["width"],
                        "height": payload["height"],
                        "steps": payload["num_inference_steps"],
                        "guidance_scale": payload["guidance_scale"],
                        "seed": response_data.get("seed", payload["seed"])
                    }
                }
                
                return result
                
        except httpx.TimeoutException:
            logger.error("Flux API timeout")
            return {
                "error": "Image generation timeout",
                "error_type": "timeout",
                "from_cache": False
            }
        except Exception as e:
            logger.error(f"Flux plugin error: {e}")
            return {
                "error": str(e),
                "error_type": "api_error",
                "from_cache": False
            }
            
    async def health_check(self) -> Dict[str, Any]:
        """Health check for Flux plugin"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/")
                
                if response.status_code == 200:
                    status_data = response.json()
                    return {
                        "status": "healthy",
                        "model": self.model,
                        "server_status": status_data.get("status", "unknown"),
                        "model_loaded": status_data.get("model_loaded", False),
                        "external_url": status_data.get("external_url")
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "error": f"Server returned {response.status_code}"
                    }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

# Plugin instance
flux_plugin = FluxPlugin()