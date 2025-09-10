# /ai/main.py
# Main FastAPI application for AI server with plugin architecture and authentication

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime, timedelta
import json
from typing import Dict, Any
import glob

# Import core modules
from config import settings
from database import db
from minio_client import minio_manager
from auth import get_current_user
from cache_manager import cache_manager

# Import plugins
from plugins.plugin_chatgpt import chatgpt_plugin
from plugins.plugin_flux import flux_plugin
from plugins.plugin_chatterbox import chatterbox_plugin

# Configure logging with rotation
class RotatingFileHandler(logging.FileHandler):
    def __init__(self, filename, days=60):
        self.days = days
        self.base_filename = filename
        self.cleanup_old_logs()
        super().__init__(self.get_current_filename())
        
    def get_current_filename(self):
        return self.base_filename.replace('{date}', datetime.now().strftime("%Y%m%d"))
        
    def cleanup_old_logs(self):
        """Remove logs older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.days)
            pattern = self.base_filename.replace('{date}', '*')
            for log_file in glob.glob(pattern):
                try:
                    file_date = datetime.fromtimestamp(os.path.getctime(log_file))
                    if file_date < cutoff_date:
                        os.remove(log_file)
                        print(f"Removed old log file: {log_file}")
                except Exception as e:
                    print(f"Error removing log file {log_file}: {e}")
        except Exception as e:
            print(f"Error in log cleanup: {e}")

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(f'logs/ai_server_{"{date}"}.log', days=settings.log_rotation_days),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Plugin registry (manual registration)
PLUGINS = {
    "chatgpt": chatgpt_plugin,
    "flux": flux_plugin,
    "chatterbox": chatterbox_plugin,
    # Add other plugins here when implemented:
    # "claude": claude_plugin,
    # "deepseek": deepseek_plugin,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events"""
    # Startup
    logger.info("Starting AI Server...")
    
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    
    # Initialize database
    await db.connect()
    
    # Create plugin tables and buckets
    for plugin_name in PLUGINS.keys():
        await db.create_plugin_table(plugin_name)
        await minio_manager.create_plugin_bucket(plugin_name)
        
    logger.info(f"AI Server started with {len(PLUGINS)} plugins: {', '.join(PLUGINS.keys())}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Server...")
    await db.disconnect()

# FastAPI app initialization
app = FastAPI(
    title="Lingudesk AI Server",
    description="AI services with plugin architecture for language learning",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
from pydantic import BaseModel
from typing import Optional, Union

class AIRequest(BaseModel):
    prompt: str
    context: Optional[str] = "text"
    from_lang: Optional[str] = "English"
    to_lang: Optional[str] = "Persian"
    max_tokens: Optional[int] = 2000
    temperature: Optional[float] = 0.7
    image_data: Optional[str] = None  # Base64 encoded image for imagecsv

class FluxRequest(BaseModel):
    prompt: str
    context: Optional[str] = "generate"
    width: Optional[int] = 1024
    height: Optional[int] = 1024
    steps: Optional[int] = 4
    guidance_scale: Optional[float] = 7.5
    seed: Optional[int] = -1

class ChatterboxRequest(BaseModel):
    text: str
    context: Optional[str] = "generate"
    language: Optional[str] = "en"
    emotion: Optional[str] = "neutral"
    speed: Optional[float] = 1.0
    exaggeration: Optional[float] = 1.0
    seed: Optional[int] = -1
    audio_prompt_path: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    plugins: Dict[str, Any]
    timestamp: str

# Middleware for request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.now()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    # Log response
    process_time = (datetime.now() - start_time).total_seconds()
    logger.info(f"Response: {response.status_code} - {process_time:.3f}s")
    
    return response

# Health check endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check for AI server and all plugins"""
    plugin_health = {}
    
    for plugin_name, plugin in PLUGINS.items():
        try:
            plugin_health[plugin_name] = await plugin.health_check()
        except Exception as e:
            plugin_health[plugin_name] = {
                "status": "error",
                "error": str(e)
            }
    
    return HealthResponse(
        status="running",
        plugins=plugin_health,
        timestamp=datetime.now().isoformat()
    )

# Generic plugin endpoint function
async def process_plugin_request(
    plugin_name: str,
    request: Union[AIRequest, FluxRequest, ChatterboxRequest],
    headers: Dict[str, str],
    current_user: Dict = Depends(get_current_user)
):
    """Generic function to process requests for any plugin"""
    
    # Check if plugin exists
    if plugin_name not in PLUGINS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{plugin_name}' not found"
        )
    
    plugin = PLUGINS[plugin_name]
    user_id = current_user["user_id"]
    
    # Check for force refresh
    force_refresh = await cache_manager.should_force_refresh(headers)
    
    # Process request
    try:
        result = await plugin.process_request(
            request.dict(),
            user_id,
            force_refresh
        )
        
        # Log successful request
        logger.info(f"Plugin '{plugin_name}' processed request for user '{user_id}'")
        
        return result
        
    except Exception as e:
        logger.error(f"Plugin '{plugin_name}' error for user '{user_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Plugin processing error: {str(e)}"
        )

# ChatGPT endpoint
@app.post("/chatgpt")
async def chatgpt_endpoint(
    request: AIRequest,
    req: Request,
    current_user: Dict = Depends(get_current_user)
):
    """ChatGPT plugin endpoint for text analysis, translation, and image processing"""
    return await process_plugin_request(
        "chatgpt", 
        request, 
        dict(req.headers), 
        current_user
    )

# Flux endpoint
@app.post("/flux")
async def flux_endpoint(
    request: FluxRequest,
    req: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Flux plugin endpoint for AI image generation using Flux 1 Schnell model"""
    return await process_plugin_request(
        "flux", 
        request, 
        dict(req.headers), 
        current_user
    )

# Chatterbox endpoint
@app.post("/chatterbox")
async def chatterbox_endpoint(
    request: ChatterboxRequest,
    req: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Chatterbox plugin endpoint for text-to-speech conversion with voice cloning"""
    return await process_plugin_request(
        "chatterbox", 
        request, 
        dict(req.headers), 
        current_user
    )

# Additional Chatterbox utility endpoints
@app.get("/chatterbox/languages")
async def get_chatterbox_languages(
    current_user: Dict = Depends(get_current_user)
):
    """Get supported languages for Chatterbox TTS"""
    return await chatterbox_plugin.get_supported_languages()

@app.get("/chatterbox/emotions")
async def get_chatterbox_emotions(
    current_user: Dict = Depends(get_current_user)
):
    """Get supported emotion presets for Chatterbox TTS"""
    return await chatterbox_plugin.get_supported_emotions()

# Cache management endpoints (admin only)
@app.delete("/cache/{plugin_name}")
async def clear_plugin_cache(
    plugin_name: str,
    current_user: Dict = Depends(get_current_user)
):
    """Clear cache for specific plugin (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    if plugin_name not in PLUGINS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{plugin_name}' not found"
        )
    
    await cache_manager.clear_plugin_cache(plugin_name)
    return {"message": f"Cache cleared for plugin '{plugin_name}'"}

@app.delete("/cache/{plugin_name}/user/{user_id}")
async def clear_user_cache(
    plugin_name: str,
    user_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """Clear cache for specific user and plugin"""
    # Users can only clear their own cache, admins can clear any user's cache
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    if plugin_name not in PLUGINS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{plugin_name}' not found"
        )
    
    await cache_manager.clear_plugin_cache(plugin_name, user_id)
    return {"message": f"Cache cleared for user '{user_id}' in plugin '{plugin_name}'"}

# Plugin status endpoint
@app.get("/plugins")
async def get_plugins_status(
    current_user: Dict = Depends(get_current_user)
):
    """Get status and information about all available plugins"""
    plugins_info = {}
    
    for plugin_name, plugin in PLUGINS.items():
        try:
            health = await plugin.health_check()
            plugins_info[plugin_name] = {
                "name": plugin.name,
                "model": getattr(plugin, 'model', 'unknown'),
                "health": health,
                "features": getattr(plugin, 'supported_languages', None) or 
                          getattr(plugin, 'emotion_presets', None) or 
                          getattr(plugin, 'contexts', {}).keys() if hasattr(plugin, 'contexts') else []
            }
        except Exception as e:
            plugins_info[plugin_name] = {
                "name": plugin_name,
                "error": str(e),
                "health": {"status": "error"}
            }
    
    return {
        "plugins": plugins_info,
        "total_plugins": len(PLUGINS),
        "timestamp": datetime.now().isoformat()
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now().isoformat()
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)