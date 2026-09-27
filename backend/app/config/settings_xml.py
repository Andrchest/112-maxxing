"""XML export/import of `Settings` (I5 E37, Q-E16-1, ТЗ ¶... «XML-конфигурация»).

Two directions, deliberately asymmetric (manager decision, this epic's brief):

* **Export** (`export_settings_xml`) is an ADMIN-only HTTP read (`exportSettingsXml`,
  `app.api.routers.admin`): the *effective* settings — whatever `Settings` actually resolved to,
  env/`.env`/profile overlay and all — rendered as
  `<settings version="1"><setting name="SIM_…">value</setting>…</settings>`. Every secret is
  **omitted entirely**, never masked-in-place (SPEC §41): a client that reads the XML learns that
  `SIM_JWT_SECRET` exists and is configured, never what it is.
* **Import** is CLI only (`python -m app.cli settings_import`, `make settings-import`): it
  validates an XML document — schema, known names, each value against its `Settings` field's own
  type — and, on success, hands back plain `NAME=value` lines for the caller to write to an env
  file. It never constructs the real `get_settings()` singleton and never touches `os.environ`
  except inside a `with`-scoped probe that restores every key it touched, whatever the outcome
  (`_temporary_env`) — "never touches the running process" (this epic's ruling) means literally
  that: nothing here changes what an already-running backend/voice-agent/gateway process sees.

**The secret list is derived, never retyped** (this epic's own rule, `CHECK`). `Settings` already
marks every credential-bearing field `Field(repr=False)` — `database_url`/`redis_url`
(credentials embedded in the URL), `jwt_secret`, `livekit_api_key`/`livekit_api_secret`,
`sip_gateway_secret`, `sip_password` — precisely so a stray `repr()`/traceback can never print one
(SPEC §41, predates this epic for the SIP pair). `SECRET_FIELD_NAMES` below reads that one
attribute off `Settings.model_fields`; a future secret field is excluded from every XML the moment
its declaration adds `repr=False`, with nothing here to remember to update.

**Value encoding.** A `Settings` field is one of: `str`, `int`, `float`, `bool`, a `Literal[...]`
of strings, `list[str]` or `dict[str, str]`. `bool` is written `"true"`/`"false"`, matching what
pydantic-settings itself accepts back (case-insensitively) from an env var; `list`/`dict` are
JSON — the exact wire pydantic-settings' `EnvSettingsSource` already expects for a complex-typed
env var (proved by this module's round-trip test, not asserted from documentation). Everything
else round-trips through a plain `str()`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from pydantic import ValidationError

from app.config.settings import Settings

__all__ = [
    "SECRET_FIELD_NAMES",
    "SETTINGS_XML_VERSION",
    "ParsedSetting",
    "SettingsXmlError",
    "export_settings_xml",
    "settings_env_lines",
]


SETTINGS_XML_VERSION = "1"


class SettingsXmlError(ValueError):
    """The XML is not a valid settings document: malformed, wrong root/version, an unknown or
    secret setting name, or a value that does not fit its setting's type."""


def _env_name_of(field_name: str, info: Any) -> str:
    """`Settings`' own `SIM_` prefix, or `info.validation_alias` when a field overrides it (e.g.
    `tts_model_variant` -> `SIM_TTS_QWEN3_MODEL`, the standalone TTS worker's own env var name)."""
    alias = info.validation_alias
    return alias if isinstance(alias, str) else f"SIM_{field_name.upper()}"


_ENV_NAME_BY_FIELD: Mapping[str, str] = {
    name: _env_name_of(name, info) for name, info in Settings.model_fields.items()
}
_FIELD_BY_ENV_NAME: Mapping[str, str] = {env: field for field, env in _ENV_NAME_BY_FIELD.items()}

SECRET_FIELD_NAMES: frozenset[str] = frozenset(
    name for name, info in Settings.model_fields.items() if info.repr is False
)
"""Every `Settings` field marked `repr=False` (SPEC §41's secrets) — see the module docstring."""

_SECRET_ENV_NAMES: frozenset[str] = frozenset(
    _ENV_NAME_BY_FIELD[name] for name in SECRET_FIELD_NAMES
)

#: Placeholder values for the settings that have no default (`Settings.model_fields[x].
#: is_required()`), used only to complete a throwaway probe `Settings` when validating a value for
#: some *other* field (see `_probe_kwargs`) — never written to an env file, never a claim about a
#: real deployment's secrets. The assertion right below keeps this dict from silently going stale.
_REQUIRED_FIELD_PLACEHOLDERS: Mapping[str, str] = {
    "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/settings_xml_probe",
    "redis_url": "redis://localhost:56379/0",
    "jwt_secret": "settings-xml-probe-secret-not-real-" + "x" * 8,
    "livekit_url": "ws://localhost:7880",
    "livekit_api_key": "probe-key",
    "livekit_api_secret": "probe-secret-0123456789",
    "llm_base_url": "http://localhost:8080/v1",
}
assert frozenset(_REQUIRED_FIELD_PLACEHOLDERS) == frozenset(
    name for name, info in Settings.model_fields.items() if info.is_required()
), (
    "a Settings field with no default was added/removed without updating "
    "_REQUIRED_FIELD_PLACEHOLDERS"
)


def _encode_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def export_settings_xml(settings: Settings) -> str:
    """The effective, non-secret settings of `settings` as an XML document (`exportSettingsXml`).

    Fields in `Settings` declaration order; a `None` value (an unset nullable field, e.g.
    `tts_default_voice`) is omitted rather than written empty — absent on import leaves the field
    at its own default, which is `None` again, so nothing is lost (this module's round-trip test).
    """
    root = ET.Element("settings", version=SETTINGS_XML_VERSION)
    for field_name in Settings.model_fields:
        if field_name in SECRET_FIELD_NAMES:
            continue
        value = getattr(settings, field_name)
        if value is None:
            continue
        element = ET.SubElement(root, "setting", name=_ENV_NAME_BY_FIELD[field_name])
        element.text = _encode_value(value)
    return ET.tostring(root, encoding="unicode")


@dataclass(frozen=True, slots=True)
class ParsedSetting:
    """One `<setting name="SIM_…">value</setting>`, validated against the schema and against
    `Settings`' own names — not yet against its field's *type* (`settings_env_lines` does that)."""

    env_name: str
    field_name: str
    value: str


def _parse(xml_text: str) -> tuple[ParsedSetting, ...]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise SettingsXmlError(f"not well-formed XML: {error}") from error
    if root.tag != "settings":
        raise SettingsXmlError(f"root element must be <settings>, got <{root.tag}>")
    version = root.get("version")
    if version != SETTINGS_XML_VERSION:
        raise SettingsXmlError(
            f'unsupported <settings version="{version}">; expected "{SETTINGS_XML_VERSION}"'
        )
    parsed: list[ParsedSetting] = []
    seen: set[str] = set()
    for child in root:
        if child.tag != "setting":
            raise SettingsXmlError(f"unexpected element <{child.tag}> under <settings>")
        name = child.get("name")
        if not name:
            raise SettingsXmlError("<setting> is missing its name attribute")
        if name in seen:
            raise SettingsXmlError(f"{name} is repeated")
        seen.add(name)
        field_name = _FIELD_BY_ENV_NAME.get(name)
        if field_name is None:
            raise SettingsXmlError(f"unknown setting name: {name}")
        if name in _SECRET_ENV_NAMES:
            raise SettingsXmlError(f"{name} is a secret and may never be imported")
        parsed.append(ParsedSetting(env_name=name, field_name=field_name, value=child.text or ""))
    return tuple(parsed)


@contextmanager
def _temporary_env(overrides: Mapping[str, str]) -> Iterator[None]:
    """Set `overrides` in `os.environ` for the `with` block only, whatever happens inside it.

    The one place this module touches process state, and only to construct a **throwaway** probe
    `Settings()` (never `get_settings()`'s cached instance) — "never touches the running process"
    holds because every key is restored to exactly what it was before this function ran.
    """
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _probe_kwargs(overridden_fields: set[str]) -> dict[str, str]:
    """Placeholders for every required field the XML itself does not set — so the probe
    `Settings()` below never fails on a field this import has nothing to say about."""
    return {
        name: value
        for name, value in _REQUIRED_FIELD_PLACEHOLDERS.items()
        if name not in overridden_fields
    }


def _validate_types(parsed: Sequence[ParsedSetting]) -> None:
    """Each value must parse under its own field's type — proved by actually building a `Settings`
    with these values overlaid on the environment (temporarily) and letting pydantic-settings do
    the exact coercion a real restart would (JSON for `list`/`dict`, `"true"`/`"false"` for `bool`,
    the `Literal` choices, …), rather than a second, hand-rolled type checker that could drift from
    what `Settings` actually accepts.
    """
    if not parsed:
        return
    overrides = {item.env_name: item.value for item in parsed}
    kwargs = _probe_kwargs({item.field_name for item in parsed})
    with _temporary_env(overrides):
        try:
            Settings(**kwargs)  # type: ignore[arg-type]
        except ValidationError as error:
            raise SettingsXmlError(
                f"one or more setting values do not fit their type: {error}"
            ) from error


def settings_env_lines(xml_text: str) -> tuple[str, ...]:
    """Validate `xml_text` (schema, known names, no secret, each value's type) and return
    `NAME=value` lines in document order, ready to write to an env file.

    Raises `SettingsXmlError` naming what is wrong; writes nothing (that is the CLI's job, only
    once this has not raised).
    """
    parsed = _parse(xml_text)
    _validate_types(parsed)
    return tuple(f"{item.env_name}={item.value}" for item in parsed)
