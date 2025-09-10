# /ai/plugins/plugin_chatgpt.py
# ChatGPT plugin for OpenAI GPT-4o-mini integration with context management and caching

import json
import asyncio
import os
from typing import Dict, Any, Optional
from openai import AsyncOpenAI
from queue import Queue
import threading
import time
from config import settings
from cache_manager import cache_manager
import logging

logger = logging.getLogger(__name__)

class ChatGPTPlugin:
    def __init__(self):
        self.name = "chatgpt"
        self.model = "gpt-4o-mini"
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.contexts = {}
        self.request_queue = Queue()
        self.rate_limiter = {}
        self.load_contexts()
        
    def load_contexts(self):
        """Load context configurations from JSON file"""
        try:
            context_file = os.path.join("plugins", "context_chatgpt.json")
            with open(context_file, 'r', encoding='utf-8') as f:
                self.contexts = json.load(f)
            logger.info(f"Loaded {len(self.contexts)} contexts for ChatGPT plugin")
        except Exception as e:
            logger.error(f"Failed to load ChatGPT contexts: {e}")
            self.contexts = {}
            
    def check_rate_limit(self, user_id: str) -> bool:
        """Simple rate limiting per user"""
        current_time = time.time()
        minute_window = current_time - 60
        
        if user_id not in self.rate_limiter:
            self.rate_limiter[user_id] = []
            
        # Clean old requests
        self.rate_limiter[user_id] = [
            req_time for req_time in self.rate_limiter[user_id] 
            if req_time > minute_window
        ]
        
        # Check limit
        if len(self.rate_limiter[user_id]) >= settings.plugin_rate_limit_per_minute:
            return False
            
        # Add current request
        self.rate_limiter[user_id].append(current_time)
        return True
        
    async def process_request(self, request_data: Dict[Any, Any], user_id: str, 
                            force_refresh: bool = False) -> Dict[Any, Any]:
        """Process ChatGPT request with caching"""
        try:
            # Rate limiting check
            if not self.check_rate_limit(user_id):
                return {
                    "error": "Rate limit exceeded",
                    "error_type": "rate_limit",
                    "from_cache": False
                }
                
            # Generate cache key
            cache_key = cache_manager.generate_cache_key(request_data, user_id)
            
            # Check cache if not force refresh
            if not force_refresh:
                cached_response = await cache_manager.get_text_cache(self.name, cache_key)
                if cached_response:
                    cached_response["from_cache"] = True
                    return cached_response
                    
            # Get context and prepare messages
            context_name = request_data.get("context", "text")
            context_text = self.contexts.get(context_name, self.contexts.get("text", ""))
            
            # Replace placeholders in context
            from_lang = request_data.get("from_lang", "English")
            to_lang = request_data.get("to_lang", "Persian")
            context_text = context_text.replace("from_lang", from_lang).replace("to_lang", to_lang)
            
            # Prepare messages
            messages = [
                {"role": "system", "content": context_text}
            ]
            
            # Add user message based on context type
            if context_name == "imagecsv":
                # For image processing, handle image data
                if "image_data" in request_data:
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": request_data.get("prompt", "Analyze this image")},
                            {"type": "image_url", "image_url": {"url": request_data["image_data"]}}
                        ]
                    })
                else:
                    return {
                        "error": "Image data required for imagecsv context",
                        "error_type": "missing_image",
                        "from_cache": False
                    }
            else:
                # For text-based contexts
                user_prompt = request_data.get("prompt", "")
                if not user_prompt:
                    return {
                        "error": "Prompt is required",
                        "error_type": "missing_prompt",
                        "from_cache": False
                    }
                messages.append({"role": "user", "content": user_prompt})
                
            # Make API call
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=request_data.get("max_tokens", 2000),
                temperature=request_data.get("temperature", 0.7)
            )
            
            # Prepare response
            result = {
                "response": response.choices[0].message.content,
                "model": self.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                },
                "from_cache": False,
                "context_used": context_name
            }
            
            # Cache the response (except for imagecsv which doesn't need caching)
            if context_name != "imagecsv":
                await cache_manager.set_text_cache(
                    self.name, cache_key, request_data, result, user_id
                )
                
            return result
            
        except Exception as e:
            logger.error(f"ChatGPT plugin error: {e}")
            return {
                "error": str(e),
                "error_type": "api_error",
                "from_cache": False
            }
            
    async def health_check(self) -> Dict[str, Any]:
        """Health check for ChatGPT plugin"""
        try:
            # Simple API test
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            return {
                "status": "healthy",
                "model": self.model,
                "contexts_loaded": len(self.contexts)
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }

# Plugin instance
chatgpt_plugin = ChatGPTPlugin()