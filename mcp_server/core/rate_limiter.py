"""Rate limiting infrastructure for MCP server.

Provides configurable rate limiting for tool calls to prevent resource
exhaustion and ensure fair usage.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import threading

from .logging_config import get_logger

logger = get_logger("rate_limiter")


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Global limits
    max_calls_per_minute: int = 120
    max_calls_per_hour: int = 3600

    # Per-tool limits (None = use global)
    tool_limits: Dict[str, int] = field(default_factory=dict)

    # Burst allowance (allows short bursts above limit)
    burst_multiplier: float = 1.5

    # Expensive operations get stricter limits
    expensive_tools: List[str] = field(default_factory=lambda: [
        "download_entity",
        "download_entities",
        "embedding_generate",
        "structure_align_to_reference",
        "sequence_annotate_with_grn",
    ])
    expensive_limit_divisor: int = 4  # expensive tools get 1/4 the normal limit

    @classmethod
    def default(cls) -> "RateLimitConfig":
        """Create default rate limit configuration."""
        return cls()

    @classmethod
    def disabled(cls) -> "RateLimitConfig":
        """Create configuration with rate limiting disabled."""
        return cls(
            max_calls_per_minute=999999,
            max_calls_per_hour=999999,
        )


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    retry_after_seconds: Optional[int] = None
    message: Optional[str] = None


class RateLimiter:
    """Thread-safe rate limiter for MCP tool calls.

    Tracks call history per tool and enforces configurable limits.

    Usage:
        limiter = RateLimiter(config)

        # Check before executing tool
        result = limiter.check("tool_name")
        if not result.allowed:
            return error_response(result.message, retry_after=result.retry_after_seconds)

        # Execute tool
        ...
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """Initialize rate limiter.

        Args:
            config: Rate limit configuration. If None, uses defaults.
        """
        self.config = config or RateLimitConfig.default()
        self._call_times: Dict[str, List[datetime]] = defaultdict(list)
        self._lock = threading.Lock()

    def _get_limit_for_tool(self, tool_name: str) -> int:
        """Get the rate limit for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Calls per minute allowed for this tool
        """
        # Check for tool-specific limit
        if tool_name in self.config.tool_limits:
            return self.config.tool_limits[tool_name]

        # Apply stricter limit for expensive tools
        if tool_name in self.config.expensive_tools:
            return max(1, self.config.max_calls_per_minute // self.config.expensive_limit_divisor)

        return self.config.max_calls_per_minute

    def _cleanup_old_entries(self, tool_name: str, now: datetime) -> None:
        """Remove entries older than 1 hour.

        Args:
            tool_name: Tool to clean up
            now: Current timestamp
        """
        cutoff = now - timedelta(hours=1)
        self._call_times[tool_name] = [
            t for t in self._call_times[tool_name] if t > cutoff
        ]

    def check(self, tool_name: str) -> RateLimitResult:
        """Check if a tool call is allowed.

        Args:
            tool_name: Name of the tool to check

        Returns:
            RateLimitResult indicating if call is allowed
        """
        with self._lock:
            now = datetime.now()

            # Clean old entries
            self._cleanup_old_entries(tool_name, now)

            calls = self._call_times[tool_name]
            limit = self._get_limit_for_tool(tool_name)

            # Check minute limit
            minute_ago = now - timedelta(minutes=1)
            recent_calls = sum(1 for t in calls if t > minute_ago)

            # Allow burst up to multiplier
            burst_limit = int(limit * self.config.burst_multiplier)

            if recent_calls >= burst_limit:
                # Calculate retry after
                oldest_in_window = min((t for t in calls if t > minute_ago), default=now)
                retry_after = 60 - (now - oldest_in_window).seconds

                logger.warning(
                    f"Rate limit exceeded for {tool_name}",
                    extra={"tool": tool_name, "calls": recent_calls, "limit": limit}
                )

                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=max(1, retry_after),
                    message=f"Rate limit exceeded for '{tool_name}'. "
                            f"Limit: {limit}/minute. Retry after {retry_after}s.",
                )

            # Check hourly limit
            hour_ago = now - timedelta(hours=1)
            hourly_calls = sum(1 for t in calls if t > hour_ago)

            if hourly_calls >= self.config.max_calls_per_hour:
                oldest_in_hour = min((t for t in calls if t > hour_ago), default=now)
                retry_after = 3600 - (now - oldest_in_hour).seconds

                logger.warning(
                    f"Hourly rate limit exceeded for {tool_name}",
                    extra={"tool": tool_name, "calls": hourly_calls}
                )

                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=max(1, retry_after),
                    message=f"Hourly rate limit exceeded. Retry after {retry_after}s.",
                )

            # Record this call
            self._call_times[tool_name].append(now)

            remaining = limit - recent_calls - 1
            return RateLimitResult(
                allowed=True,
                remaining=max(0, remaining),
            )

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Get current rate limit statistics.

        Returns:
            Dict mapping tool names to call counts
        """
        with self._lock:
            now = datetime.now()
            minute_ago = now - timedelta(minutes=1)
            hour_ago = now - timedelta(hours=1)

            stats = {}
            for tool_name, calls in self._call_times.items():
                stats[tool_name] = {
                    "calls_last_minute": sum(1 for t in calls if t > minute_ago),
                    "calls_last_hour": sum(1 for t in calls if t > hour_ago),
                    "limit_per_minute": self._get_limit_for_tool(tool_name),
                }

            return stats

    def reset(self, tool_name: Optional[str] = None) -> None:
        """Reset rate limit counters.

        Args:
            tool_name: If provided, reset only this tool. Otherwise reset all.
        """
        with self._lock:
            if tool_name:
                self._call_times[tool_name] = []
            else:
                self._call_times.clear()

            logger.info(f"Rate limits reset", extra={"tool": tool_name or "all"})


# Global rate limiter instance (initialized on first use)
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """Get or create the global rate limiter instance.

    Args:
        config: Configuration to use if creating new instance

    Returns:
        RateLimiter instance
    """
    global _rate_limiter

    if _rate_limiter is None:
        _rate_limiter = RateLimiter(config)

    return _rate_limiter


def check_rate_limit(tool_name: str) -> RateLimitResult:
    """Convenience function to check rate limit using global instance.

    Args:
        tool_name: Name of tool to check

    Returns:
        RateLimitResult
    """
    return get_rate_limiter().check(tool_name)
