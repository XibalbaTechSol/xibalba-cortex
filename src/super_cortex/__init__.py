"""Super-Cortex: High-Performance Cryptographic Memory Engine backed by Supermemory Local."""

from .client import SupermemoryClient
from .config import SuperCortexConfig
from .memory import SuperCortex
from .server import create_server, main

__version__ = "0.1.0"
__all__ = [
    "SuperCortexConfig",
    "SupermemoryClient",
    "SuperCortex",
    "create_server",
    "main",
]
