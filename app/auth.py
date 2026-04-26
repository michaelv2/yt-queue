"""Session-based authentication."""

from fastapi import Request, HTTPException, status
from starlette.middleware.sessions import SessionMiddleware
import bcrypt


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


async def require_auth(request: Request) -> None:
    """Middleware: require valid session or raise 401."""
    if not request.session.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
