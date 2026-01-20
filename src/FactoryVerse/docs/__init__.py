"""
FactoryVerse Documentation System.

This module provides a registry-based documentation system with:
- Co-located examples that can be validated
- Coverage enforcement at test/CI time
- Decision-driven documentation that doesn't bias toward specific approaches
"""

from FactoryVerse.docs.registry import DocumentationRegistry, get_registry
from FactoryVerse.docs.models import (
    Example,
    ErrorCase,
    MethodDocumentation,
    ClassDocumentation,
    CoverageReport,
)
from FactoryVerse.docs.decorators import documented_method, documented_class
from FactoryVerse.docs.validators import CoverageValidator, ExampleValidator

__all__ = [
    "DocumentationRegistry",
    "get_registry",
    "Example",
    "ErrorCase",
    "MethodDocumentation",
    "ClassDocumentation",
    "CoverageReport",
    "documented_method",
    "documented_class",
    "CoverageValidator",
    "ExampleValidator",
]
