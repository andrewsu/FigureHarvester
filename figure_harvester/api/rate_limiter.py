"""Rate limiter for API requests using token bucket algorithm."""

import threading
import time
from typing import Optional


class RateLimiter:
    """
    Thread-safe token bucket rate limiter.

    Limits the rate of operations to a specified requests per second.
    Uses token bucket algorithm to allow bursts while maintaining average rate.
    """

    def __init__(self, requests_per_second: float = 3.0):
        """
        Initialize rate limiter.

        Args:
            requests_per_second: Maximum number of requests per second
        """
        self.rate = requests_per_second
        self.tokens = requests_per_second
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire permission to make a request.

        Blocks until a token is available or timeout is reached.

        Args:
            timeout: Maximum time to wait in seconds (None = wait indefinitely)

        Returns:
            True if token acquired, False if timeout reached

        Raises:
            TimeoutError: If timeout is reached before token is available
        """
        start_time = time.time()

        with self.lock:
            while True:
                now = time.time()

                # Refill tokens based on elapsed time
                elapsed = now - self.last_update
                self.tokens = min(
                    self.rate,
                    self.tokens + elapsed * self.rate
                )
                self.last_update = now

                # If we have a token, consume it and return
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

                # Calculate sleep time needed
                sleep_time = (1.0 - self.tokens) / self.rate

                # Check timeout
                if timeout is not None:
                    elapsed_total = now - start_time
                    if elapsed_total + sleep_time > timeout:
                        return False

                # Release lock while sleeping
                self.lock.release()
                try:
                    time.sleep(sleep_time)
                finally:
                    self.lock.acquire()

    def reset(self):
        """Reset the rate limiter to full capacity."""
        with self.lock:
            self.tokens = self.rate
            self.last_update = time.time()
