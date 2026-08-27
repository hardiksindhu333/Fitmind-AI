import time
import logging
import redis
from app.core.config import settings

logger = logging.getLogger(__name__)

# Initialize Redis client
try:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
except Exception as e:
    logger.error(f"Failed to connect to Redis for rate limiting: {e}")
    redis_client = None

def check_chat_rate_limit(user_id: int) -> bool:
    """
    Checks rate limit using Token Bucket algorithm backed by Redis.
    Allows 20 requests per minute per user (refill rate: 20/60 per sec).
    Returns True if user is within limits, False otherwise.
    """
    if redis_client is None:
        logger.warning("Redis is not available; failing open for rate limiting.")
        return True

    key = f"rate_limit:chat:{user_id}"
    capacity = 20
    refill_rate = 20 / 60.0  # tokens per second
    now = time.time()
    
    try:
        # Retrieve existing bucket info
        result = redis_client.hgetall(key)
        
        if not result:
            # Initialize bucket with 1 token consumed
            tokens = capacity - 1
            last_updated = now
            
            pipe = redis_client.pipeline()
            pipe.hset(key, mapping={"tokens": tokens, "last_updated": last_updated})
            pipe.expire(key, 120)  # Expire after 2 minutes of inactivity
            pipe.execute()
            return True
        
        # Calculate how many tokens should be added since last request
        last_tokens = float(result.get("tokens", capacity))
        last_updated = float(result.get("last_updated", now))
        
        elapsed = max(0.0, now - last_updated)
        new_tokens = min(float(capacity), last_tokens + elapsed * refill_rate)
        
        if new_tokens >= 1.0:
            # Consume 1 token
            new_tokens -= 1.0
            
            pipe = redis_client.pipeline()
            pipe.hset(key, mapping={"tokens": new_tokens, "last_updated": now})
            pipe.expire(key, 120)
            pipe.execute()
            return True
        else:
            # Bucket is empty, rate limit exceeded
            return False
            
    except Exception as e:
        logger.error(f"Redis rate limiting error: {e}")
        return True  # Fail open
