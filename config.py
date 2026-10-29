"""Configuration for the JB HiFi Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT           port the API listens on (default 8000)
    JB_HIFI_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                   (default: none — direct). Product, search, suggestion,
                   store and review data come from the search, store and
                   review services jbhifi.com.au itself uses, which answer any
                   connection; if your IP ever starts getting 403s, set an
                   Australian residential proxy.
    MAX_RETRIES    attempts per upstream request on a transport error or a
                   block (default 3)
    RETRY_BACKOFF  seconds between attempts, multiplied by the attempt
                   number (default 2)
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.environ.get("RETRY_BACKOFF", "2"))

JB_HIFI_PROXY = os.environ.get("JB_HIFI_PROXY") or None


def jb_hifi_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("JB_HIFI_PROXY") or None
