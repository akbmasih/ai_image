# /ai/plugins/plugin_chatterbox.py
# Chatterbox TTS plugin for text-to-speech conversion using external API with caching

import httpx
import asyncio
import time
import base64
from typing import Dict, Any, Optional
from config import settings
from cache_manager import cache_manager
import logging

logger = logging.getLogger(__name__)

class ChatterboxPlugin:
    def __init__(self):
        self.name = "chatterbox"
        self.model = "chatterbox-tts"
        self.base_url = settings.chatterbox_api_url
        self.timeout = 60  # 1 minute timeout for TTS generation
        self.rate_limiter = {}
        
        # Supported languages and emotions from the API
        self.supported_languages = [
            {"code": "ar", "name": "Arabic"},
            {"code": "da", "name": "Danish"},
            {"code": "de", "name": "German"},
            {"code": "el", "name": "Greek"},
            {"code": "en", "name": "English"},
            {"code": "es", "name": "Spanish"},
            {"code": "fi", "name": "Finnish"},
            {"code": "fr", "name": "French"},
            {"code": "he", "name": "Hebrew"},
            {"code": "hi", "name": "Hindi"},
            {"code": "it", "name": "Italian"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ko", "name": "Korean"},
            {"code": "ms", "name": "Malay"},
            {"code": "nl", "name": "Dutch"},
            {"code": "no", "name": "Norwegian"},
            {"code": "pl", "name": "Polish"},
            {"code": "pt", "name": "Portuguese"},
            {"code": "ru", "name": "Russian"},
            {"code": "sv", "name": "Swedish"},
            {"code": "sw", "name": "Swahili"},
            {"code": "tr", "name": "Turkish"},
            {"code": "zh", "name": "Chinese"}
        ]
        
        self.emotion_presets = [
            "neutral", "happy", "sad", "angry", "excited", "calm", "dramatic"
        ]
        
    def check_rate_limit(self, user_id: str) -> bool:
        """Rate limiting per user for TTS generation"""
        current_time = time.time()
        minute_window = current_time - 60
        
        if user_id not in self.rate_limiter:
            self.rate_limiter[user_id] = []
            
        # Clean old requests
        self.rate_limiter[user_id] = [
            req_time for req_time in self.rate_limiter[user_id] 
            if req_time > minute_window
        ]
        
        # Check limit (moderate for TTS)
        if len(self.rate_limiter[user_id]) >= 10:  # 10 TTS requests per minute max
            return False
            
        # Add current request
        self.rate_limiter[user_id].append(current_time)
        return True
        
    def validate_language(self, language_code: str) -> bool:
        """Validate if language is supported"""
        return any(lang["code"] == language_code for lang in self.supported_languages)
        
    def validate_emotion(self, emotion: str) -> bool:
        """Validate if emotion preset is supported"""
        return emotion in self.emotion_presets
        
    async def process_request(self, request_data: Dict[Any, Any], user_id: str, 
                            force_refresh: bool = False) -> Dict[Any, Any]:
        """Process Chatterbox TTS request with caching"""
        try:
            # Rate limiting check
            if not self.check_rate_limit(user_id):
                return {
                    "error": "Rate limit exceeded for TTS generation",
                    "error_type": "rate_limit",
                    "from_cache": False
                }
                
            # Generate cache key
            cache_key = cache_manager.generate_cache_key(request_data, user_id)
            
            # Check file cache if not force refresh
            if not force_refresh:
                cached_audio = await cache_manager.get_file_cache(self.name, cache_key)
                if cached_audio:
                    # Convert to base64 for response
                    audio_base64 = base64.b64encode(cached_audio).decode('utf-8')
                    return {
                        "audio": f"data:audio/wav;base64,{audio_base64}",
                        "model": self.model,
                        "from_cache": True,
                        "text": request_data.get("text", ""),
                        "language": request_data.get("language", "en"),
                        "format": "wav"
                    }
                    
            # Validate required parameters
            text = request_data.get("text")
            if not text:
                return {
                    "error": "Text is required for TTS generation",
                    "error_type": "missing_text",
                    "from_cache": False
                }
                
            language = request_data.get("language", "en")
            if not self.validate_language(language):
                return {
                    "error": f"Unsupported language: {language}",
                    "error_type": "invalid_language",
                    "from_cache": False,
                    "supported_languages": [lang["code"] for lang in self.supported_languages]
                }
                
            emotion = request_data.get("emotion", "neutral")
            if not self.validate_emotion(emotion):
                return {
                    "error": f"Unsupported emotion: {emotion}",
                    "error_type": "invalid_emotion",
                    "from_cache": False,
                    "supported_emotions": self.emotion_presets
                }
                
            # Prepare request payload
            payload = {
                "text": text,
                "language": language,
                "emotion": emotion,
                "speed": request_data.get("speed", 1.0),
                "exaggeration": max(0.0, min(2.0, request_data.get("exaggeration", 1.0))),
                "seed": request_data.get("seed", -1)
            }
            
            # Add voice cloning if provided
            if "audio_prompt_path" in request_data:
                payload["audio_prompt_path"] = request_data["audio_prompt_path"]
                
            # Determine endpoint based on features
            endpoint = "/generate"
            if "audio_prompt_path" in request_data:
                endpoint = "/generate-with-voice"
                
            # Make API call to Chatterbox server
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}{endpoint}",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Chatterbox API error: {response.status_code} - {response.text}")
                    return {
                        "error": f"Chatterbox API error: {response.status_code}",
                        "error_type": "api_error",
                        "from_cache": False
                    }
                    
                response_data = response.json()
                
                # Check if generation was successful
                if "audio_id" not in response_data:
                    return {
                        "error": "TTS generation failed",
                        "error_type": "generation_failed",
                        "from_cache": False
                    }
                    
                # Get the generated audio
                audio_id = response_data["audio_id"]
                audio_response = await client.get(f"{self.base_url}/audio/{audio_id}")
                
                if audio_response.status_code != 200:
                    return {
                        "error": "Failed to retrieve generated audio",
                        "error_type": "audio_retrieval_failed",
                        "from_cache": False
                    }
                    
                audio_data = audio_response.content
                
                # Cache the audio
                await cache_manager.set_file_cache(
                    self.name, cache_key, audio_data, "audio/wav"
                )
                
                # Convert to base64 for response
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                
                result = {
                    "audio": f"data:audio/wav;base64,{audio_base64}",
                    "model": self.model,
                    "from_cache": False,
                    "text": text,
                    "language": language,
                    "emotion": emotion,
                    "format": "wav",
                    "generation_time": response_data.get("generation_time"),
                    "parameters": {
                        "speed": payload["speed"],
                        "exaggeration": payload["exaggeration"],
                        "seed": response_data.get("seed", payload["seed"])
                    }
                }
                
                # Add voice cloning info if used
                if "audio_prompt_path" in payload:
                    result["voice_cloned"] = True
                    
                return result
                
        except httpx.TimeoutException:
            logger.error("Chatterbox API timeout")
            return {
                "error": "TTS generation timeout",
                "error_type": "timeout",
                "from_cache": False
            }
        except Exception as e:
            logger.error(f"Chatterbox plugin error: {e}")
            return {
                "error": str(e),
                "error_type": "api_error",
                "from_cache": False
            }
            
    async def get_supported_languages(self) -> Dict[str, Any]:
        """Get list of supported languages"""
        return {
            "languages": self.supported_languages,
            "total_count": len(self.supported_languages)
        }
        
    async def get_supported_emotions(self) -> Dict[str, Any]:
        """Get list of supported emotion presets"""
        return {
            "emotions": self.emotion_presets,
            "total_count": len(self.emotion_presets)
        }
            
    async def health_check(self) -> Dict[str, Any]:
        """Health check for Chatterbox plugin"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/")
                
                if response.status_code == 200:
                    status_data = response.json()
                    return {
                        "status": "healthy",
                        "model": self.model,
                        "server_status": status_data.get("status", "unknown"),
                        "models_loaded": {
                            "english": status_data.get("models_loaded", {}).get("english", False),
                            "multilingual": status_data.get("models_loaded", {}).get("multilingual", False)
                        },
                        "supported_languages_count": len(status_data.get("supported_languages", [])),
                        "emotion_presets_count": len(status_data.get("emotion_presets", [])),
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
chatterbox_plugin = ChatterboxPlugin()