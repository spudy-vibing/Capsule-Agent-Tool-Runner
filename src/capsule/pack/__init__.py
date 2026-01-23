"""
Pack system for Capsule.

This module provides the pack infrastructure for bundling prompts,
policies, plans, and patterns into reusable packages.

Key Components:
    - PackManifest: Pydantic model for pack metadata
    - PackInputSchema: Input parameter definitions
    - PackOutputSchema: Output definitions
    - PackLoader: Load and validate pack structures
"""

from capsule.pack.loader import PackLoader
from capsule.pack.manifest import (
    KNOWN_TOOLS,
    PackInputSchema,
    PackManifest,
    PackOutputSchema,
)

__all__ = [
    "KNOWN_TOOLS",
    "PackInputSchema",
    "PackLoader",
    "PackManifest",
    "PackOutputSchema",
]
