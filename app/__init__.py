"""QueueStorm Investigator backend package.

This file marks ``app/`` as a Python package and exposes a single version
constant that the FastAPI app (``app/main.py``) and the OpenAPI schema
surface to clients.

Example
-------
    from app import __version__
    print(__version__)  # -> "0.1.0"
"""

# Bumped by hand (or CI) whenever the public API changes. Rendered in
# the OpenAPI docs at ``GET /openapi.json`` as ``info.version``.
__version__ = "0.1.0"
