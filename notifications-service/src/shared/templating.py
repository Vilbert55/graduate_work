"""Рендеринг шаблонов сообщений Jinja2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    subject: str
    body: str


_text_env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701
_html_env = Environment(
    undefined=StrictUndefined,
    autoescape=select_autoescape(default_for_string=True, default=True),
)


def render(
    subject_template: str,
    body_template: str,
    body_format: str,
    context: dict[str, Any],
) -> RenderedMessage:
    """Отрендерить subject и body для конкретного пользователя.

    body_format == 'html' включает auto-escape для тела (subject — всегда plain).
    """
    subj_tmpl = _text_env.from_string(subject_template)
    body_env = _html_env if body_format == "html" else _text_env
    body_tmpl = body_env.from_string(body_template)
    return RenderedMessage(
        subject=subj_tmpl.render(**context),
        body=body_tmpl.render(**context),
    )
