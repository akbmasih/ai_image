# /ai/database.py
# PostgreSQL database connection and cache table management for AI plugins

import asyncpg
import asyncio
import json
from typing import Optional, Dict, Any
from config import settings
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        
    async def connect(self):
        """Initialize database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=2,
                max_size=10
            )
            logger.info("Database connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise
            
    async def disconnect(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
            
    async def create_plugin_table(self, plugin_name: str):
        """Create cache table for specific plugin"""
        table_name = f"cache_{plugin_name}"
        
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            cache_key VARCHAR(255) UNIQUE NOT NULL,
            request_data JSONB NOT NULL,
            response_data JSONB NOT NULL,
            user_id VARCHAR(10) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_{plugin_name}_cache_key ON {table_name}(cache_key);
        CREATE INDEX IF NOT EXISTS idx_{plugin_name}_user_id ON {table_name}(user_id);
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(create_table_query)
            logger.info(f"Cache table for plugin '{plugin_name}' created/verified")
            
    async def get_cache(self, plugin_name: str, cache_key: str) -> Optional[Dict[Any, Any]]:
        """Get cached response for plugin"""
        table_name = f"cache_{plugin_name}"
        
        query = f"""
        UPDATE {table_name} 
        SET accessed_at = CURRENT_TIMESTAMP 
        WHERE cache_key = $1
        RETURNING response_data;
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, cache_key)
            return result if result else None
            
    async def set_cache(self, plugin_name: str, cache_key: str, request_data: Dict, 
                       response_data: Dict, user_id: str):
        """Set cache for plugin"""
        table_name = f"cache_{plugin_name}"
        
        query = f"""
        INSERT INTO {table_name} (cache_key, request_data, response_data, user_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (cache_key) 
        DO UPDATE SET 
            response_data = $2,
            accessed_at = CURRENT_TIMESTAMP;
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(
                query, 
                cache_key, 
                json.dumps(request_data), 
                json.dumps(response_data), 
                user_id
            )
            
    async def clear_plugin_cache(self, plugin_name: str, user_id: Optional[str] = None):
        """Clear cache for plugin (optionally for specific user)"""
        table_name = f"cache_{plugin_name}"
        
        if user_id:
            query = f"DELETE FROM {table_name} WHERE user_id = $1"
            async with self.pool.acquire() as conn:
                await conn.execute(query, user_id)
        else:
            query = f"DELETE FROM {table_name}"
            async with self.pool.acquire() as conn:
                await conn.execute(query)

# Global database manager instance
db = DatabaseManager()