"""Russian prompt texts for the dialogue chain, as module constants (HLD `50-voice-pipeline.md` §5).

E13-B1 ships the interpreter's prompts only (`interpreter.py`); the caller generator's system
prompt (§5.2, `CALLER_SYSTEM_PROMPT_RU`) belongs to E13-B2, which owns `generator.py`.
"""

from __future__ import annotations

from app.application.dialogue.prompts.interpreter import (
    INTERPRETER_REPAIR_PROMPT_RU,
    INTERPRETER_SYSTEM_PROMPT_RU,
    INTERPRETER_USER_TEMPLATE_RU,
    few_shot_messages_ru,
    render_fact_catalog_ru,
    render_turn_window_ru,
    speech_act_help_ru,
)

__all__ = [
    "INTERPRETER_REPAIR_PROMPT_RU",
    "INTERPRETER_SYSTEM_PROMPT_RU",
    "INTERPRETER_USER_TEMPLATE_RU",
    "few_shot_messages_ru",
    "render_fact_catalog_ru",
    "render_turn_window_ru",
    "speech_act_help_ru",
]
