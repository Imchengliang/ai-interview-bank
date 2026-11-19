"""Portable core for the AI interview question bank plugin.

Pure standard library. This package never writes answers: Step 4 (per-question
analysis) is deliberately left to the LLM, following SKILL.md.
"""

from . import bank, coach, config, graph, obsidian, pipeline, sources

__all__ = ["bank", "coach", "config", "graph", "obsidian", "pipeline", "sources"]
