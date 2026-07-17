"""
app/core/rate_limiter.py — Redis-backed rate limiter using INCR + EXPIRE pattern.

All functions are async and accept a redis.asyncio.Redis client instance.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# Key prefixes
_RATE_LIMIT_PREFIX = "rl:"
_LOGIN_FAILURE_PREFIX = "login_fail:"


async def check_rate_limit(
    redis,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """
    Sliding-window rate limiter using Redis INCR + EXPIRE.

    Increments a counter for `key`. On first increment, sets TTL to
    `window_seconds`. If the counter exceeds `max_requests`, returns False.

    Args:
        redis:          Async Redis client (redis.asyncio.Redis).
        key:            Unique identifier for this rate-limit bucket.
        max_requests:   Maximum allowed requests within the window.
        window_seconds: Duration of the sliding window in seconds.

    Returns:
        True  — request is within the allowed limit.
        False — limit exceeded; caller should return 429.
    """
    full_key = f"{_RATE_LIMIT_PREFIX}{key}"
    try:
        current: int = await redis.incr(full_key)
        if current == 1:
            # First request in this window; set expiry
            await redis.expire(full_key, window_seconds)
        if current > max_requests:
            log.warning("rate_limit.exceeded", key=key, current=current, max=max_requests)
            return False
        return True
    except Exception as exc:
        # If Redis is unavailable, fail open (allow the request) to avoid
        # blocking all users during an outage.
        log.error("rate_limit.redis_error", key=key, error=str(exc))
        return True


async def check_login_attempts(redis, email: str) -> int:
    """
    Return the current number of consecutive failed login attempts for an email.

    Args:
        redis: Async Redis client.
        email: The email address to check.

    Returns:
        Integer count of failed attempts (0 if no record exists).
    """
    full_key = f"{_LOGIN_FAILURE_PREFIX}{email.lower()}"
    try:
        val = await redis.get(full_key)
        return int(val) if val is not None else 0
    except Exception as exc:
        log.error("rate_limit.check_failed", email=email, error=str(exc))
        return 0


async def increment_login_failures(
    redis,
    email: str,
    lockout_minutes: int,
) -> int:
    """
    Increment the failed-login counter for an email address.

    On first failure, sets the TTL to lockout_minutes * 60 so the record
    naturally expires after the lockout window.

    Args:
        redis:           Async Redis client.
        email:           Email address that failed to authenticate.
        lockout_minutes: TTL in minutes for the failure counter.

    Returns:
        New count after incrementing.
    """
    full_key = f"{_LOGIN_FAILURE_PREFIX}{email.lower()}"
    try:
        current: int = await redis.incr(full_key)
        if current == 1:
            # First failure — set TTL so it auto-clears after lockout window
            await redis.expire(full_key, lockout_minutes * 60)
        log.info("login_failure.incremented", email=email, count=current)
        return current
    except Exception as exc:
        log.error("rate_limit.increment_failed", email=email, error=str(exc))
        return 0


async def reset_login_attempts(redis, email: str) -> None:
    """
    Clear the failed-login counter for an email address after a successful login.

    Args:
        redis: Async Redis client.
        email: Email address to reset.
    """
    full_key = f"{_LOGIN_FAILURE_PREFIX}{email.lower()}"
    try:
        await redis.delete(full_key)
        log.debug("login_failure.reset", email=email)
    except Exception as exc:
        log.error("rate_limit.reset_failed", email=email, error=str(exc))
