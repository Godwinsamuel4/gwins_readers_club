"""
Simple in-process TTL cache for hot, expensive-to-recompute read endpoints
(categories list, current book of the month, admin stats). Not distributed —
if this app ever runs multiple worker processes/instances behind a load
balancer, swap this for Redis (the cache key/TTL shape below maps directly).
"""
import time
from functools import wraps
from typing import Any, Callable

_cache_store: dict[str, tuple[float, Any]] = {}


def cache_get(key: str):
    entry = _cache_store.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _cache_store.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl_seconds: int = 60):
    _cache_store[key] = (time.time() + ttl_seconds, value)


def cache_invalidate(prefix: str = ""):
    """Clear all keys, or all keys starting with a prefix (e.g. on a write)."""
    if not prefix:
        _cache_store.clear()
        return
    for key in [k for k in _cache_store if k.startswith(prefix)]:
        _cache_store.pop(key, None)


def cached(key_fn: Callable[..., str], ttl_seconds: int = 60):
    """Decorator for read endpoints. key_fn builds the cache key from the same args."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = key_fn(*args, **kwargs)
            hit = cache_get(key)
            if hit is not None:
                return hit
            result = await func(*args, **kwargs)
            cache_set(key, result, ttl_seconds)
            return result
        return wrapper
    return decorator
