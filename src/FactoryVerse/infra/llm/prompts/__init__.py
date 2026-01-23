"""LLM prompt generation and documentation module.

This module consolidates all prompt-related generation:
- System prompt assembly
- API reference documentation
- Schema documentation
- Tech/recipe prompts
- Categorical references

Usage:
    from FactoryVerse.infra.llm.prompts import generate_system_prompt

    # Generate complete system prompt
    prompt = generate_system_prompt(
        include_api_reference=True,
        include_schema=True,
        include_examples=False
    )
"""

from FactoryVerse.infra.llm.prompts.system_prompt import generate_system_prompt
from FactoryVerse.infra.llm.prompts.api_reference import generate_api_reference
from FactoryVerse.infra.llm.prompts.schema_reference import generate_schema_reference
from FactoryVerse.infra.llm.prompts.tech_recipes import (
    TechRecipePromptGenerator,
    TechInfo,
    RecipeInfo,
)
from FactoryVerse.infra.llm.prompts.categorical import CategoricalReferenceGenerator

__all__ = [
    "generate_system_prompt",
    "generate_api_reference",
    "generate_schema_reference",
    "TechRecipePromptGenerator",
    "TechInfo",
    "RecipeInfo",
    "CategoricalReferenceGenerator",
]
