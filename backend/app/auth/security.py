from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_token(
    subject: int,
    token_type: str,
    expires_delta: timedelta,
    *,
    organization_id: int,
) -> tuple[str, str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = uuid4().hex
    payload = {
        "sub": str(subject),
        "type": token_type,
        "organization_id": organization_id,
        "jti": jti,
        "iat": now,
        "exp": expires_at,
    }
    return (
        jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm),
        jti,
        expires_at,
    )


def decode_token(token: str, expected_type: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
    if (
        payload.get("type") != expected_type
        or not payload.get("sub")
        or not isinstance(payload.get("organization_id"), int)
        or payload["organization_id"] < 1
    ):
        raise ValueError(f"Expected a {expected_type} token")
    return payload
