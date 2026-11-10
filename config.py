"""Configuration for the Immobiliare It Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                           port the API listens on (default 8000)
    IMMOBILIARE_IT_PROXY           proxy URL for every request, e.g.
                                   http://user:pass@host:port (default: none —
                                   direct). immobiliare.it sits behind DataDome;
                                   your own connection is usually all you need.
                                   Set one for steady high volume, so every retry
                                   after a block leaves through a fresh IP.
    IMMOBILIARE_IT_FALLBACK_PROXY  proxy URL used only after DataDome refused every
                                   browser identity on your own connection, for
                                   IMMOBILIARE_IT_BLOCK_HOLD_S seconds (default:
                                   none — keep retrying direct).

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# How long new sessions use IMMOBILIARE_IT_FALLBACK_PROXY once every browser
# identity was refused on your own connection.
IMMOBILIARE_IT_BLOCK_HOLD_S = 600

IMMOBILIARE_IT_PROXY = os.environ.get("IMMOBILIARE_IT_PROXY") or None


def immobiliare_it_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("IMMOBILIARE_IT_PROXY") or None


def immobiliare_it_fallback_proxy():
    """The proxy new sessions take while your own connection is held off
    (None = keep retrying direct)."""
    return os.environ.get("IMMOBILIARE_IT_FALLBACK_PROXY") or None
