import logging
import threading
import time
from collections import deque

from utils.config import TOKEN_LIMIT_PER_MINUTE, _RATE_WINDOW_SECONDS

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token rate limiter  (30 000 tokens / 60-second sliding window)
# ---------------------------------------------------------------------------


class TokenRateLimiter:
    """Sliding-window token rate limiter.

    Tracks API token consumption in a rolling 60-second window and blocks
    callers whenever the next request would push usage over the configured
    limit.  The implementation is thread-safe so it works correctly even if
    multiple threads share the same limiter instance.

    Usage pattern inside a provider (e.g. ``AnthropicProvider``):

    1. Before calling the API, call :meth:`wait_for_capacity` with a
       conservative *estimated* token count.  This call will block until
       the window has enough headroom, then atomically reserve the tokens.
       It returns an opaque *reservation_id*.
    2. After the API responds and the real usage is known, pass the
       *reservation_id* and actual token count to :meth:`record_actual`
       so the reservation is corrected to the true value.
    """

    def __init__(self, limit: int = TOKEN_LIMIT_PER_MINUTE) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        # Deque of mutable entries: [monotonic_timestamp, tokens, reservation_id]
        # Lists (not tuples) are used so record_actual() can update entry[1]
        # in-place by object identity without rebuilding the deque.
        self._usage: deque = deque()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evict_expired(self, now: float) -> None:
        """Drop entries older than the sliding window (caller holds lock)."""
        cutoff = now - _RATE_WINDOW_SECONDS
        while self._usage and self._usage[0][0] <= cutoff:
            self._usage.popleft()

    def _seconds_until_free(self, needed: int, now: float) -> float:
        """Seconds to wait before *needed* tokens fit in the window.

        Walks the usage deque from oldest to newest, computing how much
        capacity each expiring entry will free, and returns the time at
        which enough headroom first becomes available.

        Caller must hold *self._lock* and must have already called
        ``_evict_expired(now)`` so the deque contains only live entries.
        ``current_usage`` is computed once before the loop to avoid calling
        ``_evict_expired`` again mid-iteration (which would mutate the deque
        while it is being iterated).
        """
        current_usage = sum(entry[1] for entry in self._usage)
        freed = 0
        for entry in self._usage:
            freed += entry[1]
            if current_usage - freed + needed <= self.limit:
                # This entry expiring creates enough headroom.
                return max(0.0, entry[0] + _RATE_WINDOW_SECONDS - now)
        # Waiting for all entries to expire still leaves us short - fall back
        # to waiting for the oldest entry (caller will re-evaluate afterwards).
        if self._usage:
            return max(0.0, self._usage[0][0] + _RATE_WINDOW_SECONDS - now)
        return 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wait_for_capacity(self, estimated_tokens: int) -> object:
        """Block until *estimated_tokens* fit inside the rate limit window.

        Once capacity is confirmed the tokens are *reserved* optimistically
        so that concurrent callers see them immediately.

        Returns an opaque *reservation ID* that must be passed to
        :meth:`record_actual` so the correct entry can be updated, even
        when concurrent requests share the same estimated token count.

        If *estimated_tokens* exceeds the hard per-minute limit the request
        can never fit inside a single window.  Rather than hanging forever
        the limiter asks the user interactively whether to proceed anyway
        (bypassing the limit for this one call) or abort.
        """
        # --- Guard: estimate exceeds the hard limit - would hang forever ---
        if estimated_tokens > self.limit:
            _logger.warning(
                "Estimated token cost (%d) exceeds the per-minute limit (%d) - "
                "auto-proceeding (bypassing limit for this request).",
                estimated_tokens, self.limit,
            )
            # Reserve without enforcing the limit.
            reservation_id = object()
            with self._lock:
                entry = [time.monotonic(), estimated_tokens, reservation_id]
                self._usage.append(entry)
            return reservation_id
        # --------------------------------------------------------------------

        while True:
            with self._lock:
                now = time.monotonic()
                # Evict explicitly so _seconds_until_free receives a clean
                # deque and does not need to call _evict_expired itself.
                self._evict_expired(now)
                used = sum(entry[1] for entry in self._usage)
                if used + estimated_tokens <= self.limit:
                    reservation_id = object()
                    self._usage.append([now, estimated_tokens, reservation_id])
                    return reservation_id  # capacity secured
                wait_sec = self._seconds_until_free(estimated_tokens, now)

            # Log outside the lock to avoid blocking other threads.
            _logger.info(
                "%d/%d tokens used in the last %ds - waiting %.1fs for "
                "%d tokens of capacity ...",
                used, self.limit, _RATE_WINDOW_SECONDS, wait_sec, estimated_tokens,
            )
            time.sleep(max(0.5, wait_sec))

    def record_actual(self, reservation_id: object, actual_tokens: int) -> None:
        """Correct the optimistic reservation made in :meth:`wait_for_capacity`.

        Finds the reservation by its unique ID (returned by
        :meth:`wait_for_capacity`) and updates its token count to
        *actual_tokens*.  Using an ID rather than matching by token count
        means concurrent requests with the same estimate are each corrected
        independently without risk of updating the wrong entry.

        If the reservation is no longer in the window (it has already aged
        out) the correction is a no-op: the tokens have already left the
        window, so no adjustment is needed.
        """
        with self._lock:
            for entry in self._usage:
                if entry[2] is reservation_id:
                    entry[1] = actual_tokens
                    return
            # Reservation aged out of the window - no correction needed.

    def status(self) -> str:
        """Human-readable one-liner showing current window usage."""
        with self._lock:
            now = time.monotonic()
            self._evict_expired(now)
            used = sum(entry[1] for entry in self._usage)
        return (
            f"[RateLimiter] {used}/{self.limit} tokens used "
            f"in the last {_RATE_WINDOW_SECONDS}s"
        )


# Module-level singleton - shared by all providers.
_rate_limiter = TokenRateLimiter()
