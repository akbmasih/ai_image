# /ai/auth.py
# JWT token validation and authentication for AI server

import jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, Optional
from config import settings
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()

class AuthManager:
    def __init__(self):
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        
    def decode_token(self, token: str) -> Dict:
        """Decode and validate JWT token"""
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
            
    def get_user_id(self, payload: Dict) -> str:
        """Extract user ID from token payload"""
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user_id"
            )
        return user_id
        
    def get_user_email(self, payload: Dict) -> str:
        """Extract user email from token payload"""
        email = payload.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing email"
            )
        return email
        
    def get_user_role(self, payload: Dict) -> str:
        """Extract user role from token payload"""
        return payload.get("role", "user")

# Global auth manager instance
auth_manager = AuthManager()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """Dependency to get current authenticated user"""
    try:
        payload = auth_manager.decode_token(credentials.credentials)
        return {
            "user_id": auth_manager.get_user_id(payload),
            "email": auth_manager.get_user_email(payload),
            "role": auth_manager.get_user_role(payload),
            "payload": payload
        }
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )