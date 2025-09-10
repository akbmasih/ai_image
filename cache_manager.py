# /ai/cache_manager.py
# Cache management system for AI plugins using PostgreSQL and MinIO

import hashlib
import json
from typing import Dict, Any, Optional, Union
from database import db
from minio_client import minio_manager
from config import settings
import logging

logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self):
        self.cache_enabled = settings.cache_enabled
        
    def generate_cache_key(self, request_data: Dict, user_id: str) -> str:
        """Generate unique cache key from request data and user ID"""
        cache_data = {
            "request": request_data,
            "user_id": user_id
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(cache_str.encode()).hexdigest()
        
    async def get_text_cache(self, plugin_name: str, cache_key: str) -> Optional[Dict]:
        """Get cached text response from PostgreSQL"""
        if not self.cache_enabled:
            return None
            
        try:
            cached_data = await db.get_cache(plugin_name, cache_key)
            if cached_data:
                logger.info(f"Cache hit for plugin '{plugin_name}' with key '{cache_key[:8]}...'")
                return cached_data
        except Exception as e:
            logger.error(f"Failed to get text cache for plugin '{plugin_name}': {e}")
            
        return None
        
    async def set_text_cache(self, plugin_name: str, cache_key: str, 
                           request_data: Dict, response_data: Dict, user_id: str):
        """Set text cache in PostgreSQL"""
        if not self.cache_enabled:
            return
            
        try:
            await db.set_cache(plugin_name, cache_key, request_data, response_data, user_id)
            logger.info(f"Text cached for plugin '{plugin_name}' with key '{cache_key[:8]}...'")
        except Exception as e:
            logger.error(f"Failed to set text cache for plugin '{plugin_name}': {e}")
            
    async def get_file_cache(self, plugin_name: str, cache_key: str) -> Optional[bytes]:
        """Get cached file from MinIO"""
        if not self.cache_enabled:
            return None
            
        try:
            cached_file = await minio_manager.get_file_cache(plugin_name, cache_key)
            if cached_file:
                logger.info(f"File cache hit for plugin '{plugin_name}' with key '{cache_key[:8]}...'")
                return cached_file
        except Exception as e:
            logger.error(f"Failed to get file cache for plugin '{plugin_name}': {e}")
            
        return None
        
    async def set_file_cache(self, plugin_name: str, cache_key: str, 
                           file_data: bytes, content_type: str = "application/octet-stream"):
        """Set file cache in MinIO"""
        if not self.cache_enabled:
            return
            
        try:
            await minio_manager.set_file_cache(plugin_name, cache_key, file_data, content_type)
            logger.info(f"File cached for plugin '{plugin_name}' with key '{cache_key[:8]}...'")
        except Exception as e:
            logger.error(f"Failed to set file cache for plugin '{plugin_name}': {e}")
            
    async def should_force_refresh(self, headers: Dict) -> bool:
        """Check if cache should be bypassed"""
        force_refresh_header = settings.force_refresh_header.lower()
        return any(
            header.lower() == force_refresh_header and value.lower() in ["true", "1", "yes"]
            for header, value in headers.items()
        )
        
    async def clear_plugin_cache(self, plugin_name: str, user_id: Optional[str] = None):
        """Clear all cache for plugin"""
        try:
            # Clear text cache
            await db.clear_plugin_cache(plugin_name, user_id)
            
            # Clear file cache (only if no user_id specified, as MinIO doesn't support user-specific clearing)
            if not user_id:
                await minio_manager.clear_plugin_cache(plugin_name)
                
            logger.info(f"Cache cleared for plugin '{plugin_name}'" + 
                       (f" for user '{user_id}'" if user_id else ""))
        except Exception as e:
            logger.error(f"Failed to clear cache for plugin '{plugin_name}': {e}")

# Global cache manager instance
cache_manager = CacheManager()