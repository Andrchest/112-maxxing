"""The score-explanation prompt builder — pure, no I/O (SPEC §2, §29; R8).

`build_messages` is a function of exactly three things: a `ScoreReport`, the scenario's own
`rule_id -> name_ru` mapping (the same one `RescoreOutcome.scoring_rules` threads through for
`rescoreSession`, `backend/app/application/scoring/rescore_session.py:76-79`) and an
`ExplanationAudience`. That signature *is* R8's whole input whitelist: the function has no
parameter that could carry a transcript, `WorldTruth` or an `OperatorCard`, so nothing upstream can
hand it one by mistake — `test_the_builder_takes_exactly_the_whitelisted_parameters` in
`backend/tests/unit/application/reports/explanation/test_prompt.py` pins the parameter list
itself, not just today's call sites.

The system prompt's rules, verbatim in spirit: explain the computed result; cite rule titles (not
`rule_id`s) and the awarded/max points exactly as given, never a different number; never invent a
fact about the call, the trainee or the caller — the model sees no transcript, no card, no world
truth, only the `ScoreReport`; write Russian prose, no markdown. `TRAINEE` reads as supportive and
didactic; `INSTRUCTOR` as concise and analytic (DO item 1).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.application.ports.llm import ChatMessage
from app.application.ports.report_explanation_repository import ExplanationAudience
from app.domain.scoring.results import ScoreReport

__all__ = ["build_messages"]

#: Rules that hold for every audience — the input whitelist and the "never alter a number"
#: guarantee, stated to the model itself (belt and braces alongside the structural one).
_COMMON_RULES: tuple[str, ...] = (
    "Объясняй ТОЛЬКО уже посчитанный результат оценивания. Никогда не меняй и не придумывай "
    "числа: баллы и максимумы приведены тебе как факт — цитируй их дословно, не пересчитывай.",
    "Ссылайся на правила по их русским названиям, а не по идентификаторам rule_id.",
    "Не придумывай фактов о звонке, диалоге, стажёре или звонящем — тебе доступны только "
    "результаты оценивания (названия правил, баллы, признак критической ошибки и заметки к "
    "доказательствам), а не стенограмма и не карточка происшествия.",
    "Пиши по-русски, простыми предложениями, без markdown-разметки и без списков в квадратных "
    "скобках.",
)

_TRAINEE_TONE = (
    "Аудитория — стажёр, который только что прошёл тренировку. Тон — поддерживающий и "
    "обучающий: объясни, что получилось хорошо и что стоит улучшить в следующий раз, опираясь "
    "только на перечисленные правила и баллы."
)

_INSTRUCTOR_TONE = (
    "Аудитория — инструктор, который проверяет результат. Тон — сжатый и аналитический: "
    "перечисли ключевые расхождения и критические ошибки без обучающих пояснений."
)


def _system_prompt(audience: ExplanationAudience) -> str:
    tone = _TRAINEE_TONE if audience == "TRAINEE" else _INSTRUCTOR_TONE
    rules = "\n".join(f"- {rule}" for rule in _COMMON_RULES)
    return f"{tone}\n\nПравила:\n{rules}"


def _report_summary(report: ScoreReport, rule_titles: Mapping[str, str]) -> str:
    lines: list[str] = [
        f"Итог: {report.total_points:.2f} из {report.total_max_points:.2f} баллов.",
        "Баллы по категориям:",
    ]
    for category in report.by_category:
        lines.append(
            f"  - {category.category.value}: {category.points_awarded:.2f} из "
            f"{category.max_points:.2f}"
        )
    lines.append("Правила:")
    for result in report.results:
        title = rule_titles.get(result.rule_id, result.rule_id)
        if result.critical_failure:
            status = "критическая ошибка"
        elif result.passed:
            status = "выполнено"
        else:
            status = "не выполнено"
        notes = "; ".join(evidence.note_ru for evidence in result.evidence if evidence.note_ru)
        line = f"  - {title}: {result.points_awarded:.2f} из {result.max_points:.2f} ({status})"
        if notes:
            line += f" — {notes}"
        lines.append(line)
    return "\n".join(lines)


def build_messages(
    report: ScoreReport,
    rule_titles: Mapping[str, str],
    audience: ExplanationAudience,
) -> list[ChatMessage]:
    """`[system, user]` — the whole input an explanation LLM call may see (R8, DO item 1).

    `rule_titles` maps `rule_id -> ScoringRule.name_ru`; a rule id missing from it (should not
    happen — every `ScoreResult.rule_id` comes from the same scenario's rule catalog) falls back
    to the bare id rather than raising, so a caller's mapping bug degrades the prose, not the call.
    """
    return [
        ChatMessage(role="system", content=_system_prompt(audience)),
        ChatMessage(role="user", content=_report_summary(report, rule_titles)),
    ]
