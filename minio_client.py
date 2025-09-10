# /ai/minio_client.py
# MinIO client for file caching system for AI plugins

from minio import Minio
from minio.error import S3Error
import io
import json
from typing import Optional, Dict, Any
from config import settings
import logging
import hashlib

logger = logging.getLogger(__name__)

class MinIOManager:
    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure
        )
        
    async def create_plugin_bucket(self, plugin_name: str):
        """Create bucket for specific plugin"""
        bucket_name = f"{plugin_name}-cache"
        
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                logger.info(f"Bucket '{bucket_name}' created for plugin '{plugin_name}'")
            else:
                logger.info(f"Bucket '{bucket_name}' already exists for plugin '{plugin_name}'")
        except S3Error as e:
            logger.error(f"Failed to create bucket for plugin '{plugin_name}': {e}")
            raise
            
    def _generate_cache_key(self, request_data: Dict) -> str:
        """Generate cache key from request data"""
        request_str = json.dumps(request_data, sort_keys=True)
        return hashlib.md5(request_str.encode()).hexdigest()
        
    async def get_file_cache(self, plugin_name: str, cache_key: str) -> Optional[bytes]:
        """Get cached file for plugin"""
        bucket_name = f"{plugin_name}-cache"
        
        try:
            response = self.client.get_object(bucket_name, cache_key)
            return response.read()
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            logger.error(f"Failed to get cache for plugin '{plugin_name}': {e}")
            return None
            
    async def set_file_cache(self, plugin_name: str, cache_key: str, file_data: bytes, 
                            content_type: str = "application/octet-stream"):
        """Set file cache for plugin"""
        bucket_name = f"{plugin_name}-cache"
        
        try:
            file_stream = io.BytesIO(file_data)
            self.client.put_object(
                bucket_name,
                cache_key,
                file_stream,
                length=len(file_data),
                content_type=content_type
            )
            logger.info(f"File cached for plugin '{plugin_name}' with key '{cache_key}'")
        except S3Error as e:
            logger.error(f"Failed to set cache for plugin '{plugin_name}': {e}")
            raise
            
    async def delete_file_cache(self, plugin_name: str, cache_key: str):
        """Delete specific cached file"""
        bucket_name = f"{plugin_name}-cache"
        
        try:
            self.client.remove_object(bucket_name, cache_key)
            logger.info(f"Cache deleted for plugin '{plugin_name}' with key '{cache_key}'")
        except S3Error as e:
            if e.code != "NoSuchKey":
                logger.error(f"Failed to delete cache for plugin '{plugin_name}': {e}")
                
    async def clear_plugin_cache(self, plugin_name: str):
        """Clear all cached files for plugin"""
        bucket_name = f"{plugin_name}-cache"
        
        try:
            objects = self.client.list_objects(bucket_name, recursive=True)
            for obj in objects:
                self.client.remove_object(bucket_name, obj.object_name)
            logger.info(f"All cache cleared for plugin '{plugin_name}'")
        except S3Error as e:
            logger.error(f"Failed to clear cache for plugin '{plugin_name}': {e}")

# Global MinIO manager instance
minio_manager = MinIOManager()