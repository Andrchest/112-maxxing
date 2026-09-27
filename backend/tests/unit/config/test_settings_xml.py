"""XML export/import of `Settings` (I5 E37, Q-E16-1): the secret list, the round trip, and every
refusal `settings_env_lines` must raise before a single byte reaches an env file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config.settings import Settings
from app.config.settings_xml import (
    SECRET_FIELD_NAMES,
    SettingsXmlError,
    export_settings_xml,
    settings_env_lines,
)

_BASE_KWARGS = {
    "database_url": "postgresql+asyncpg://sim:sim@localhost:55432/sim_test",
    "redis_url": "redis://localhost:56379/0",
    "jwt_secret": "x" * 32,
    "livekit_url": "ws://localhost:7880",
    "livekit_api_key": "devkey",
    "livekit_api_secret": "devsecret1234567890",
    "llm_base_url": "http://localhost:8080/v1",
}


def _settings(**overrides: object) -> Settings:
    return Settings(**{**_BASE_KWARGS, **overrides})  # type: ignore[arg-type]


def test_the_secret_list_is_derived_from_settings_repr_false_and_nothing_else() -> None:
    """The module's own rule (CHECK): no second, hand-kept list to drift from `Settings`."""
    derived = {name for name, info in Settings.model_fields.items() if info.repr is False}
    assert derived == SECRET_FIELD_NAMES
    # Every field this epic's brief names a category of ("passwords, keys, tokens, JWT secret, DB
    # URLs with credentials") is in fact marked — a sanity check on the *category*, not a retyped
    # membership list (`_BASE_KWARGS`' seven names would be circular here).
    assert {
        "jwt_secret",
        "database_url",
        "redis_url",
        "livekit_api_key",
        "livekit_api_secret",
    } <= derived


def test_the_export_names_no_secret_at_all() -> None:
    settings = _settings()
    xml = export_settings_xml(settings)
    for field_name in SECRET_FIELD_NAMES:
        env_name = f"SIM_{field_name.upper()}"
        assert f'name="{env_name}"' not in xml, f"{env_name} leaked into the export"
    # And the values themselves never appear either (belt and suspenders: a secret whose value
    # happens to collide with a non-secret field's name would still slip through the check above).
    assert _BASE_KWARGS["jwt_secret"] not in xml
    assert "devsecret1234567890" not in xml


def _write_env_file(tmp_path: Path, lines: tuple[str, ...]) -> Path:
    path = tmp_path / ".env.settings"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _reload(tmp_path: Path, lines: tuple[str, ...]) -> Settings:
    """The written env file loaded back — secrets supplied as explicit kwargs (init settings win
    over a value the file happens to also carry, and this file never carries one anyway), exactly
    as `settings_import.run_settings_import`'s own consumer would load it on the next restart."""
    path = _write_env_file(tmp_path, lines)
    return Settings(_env_file=str(path), **_BASE_KWARGS)  # type: ignore[arg-type, call-arg]


def test_export_then_import_round_trips_to_the_same_non_secret_settings(tmp_path: Path) -> None:
    settings = _settings(
        cors_allow_origins=["http://a.example", "http://b.example"], require_inference_ready=False
    )
    xml = export_settings_xml(settings)
    lines = settings_env_lines(xml)
    reloaded = _reload(tmp_path, lines)

    for field_name in Settings.model_fields:
        if field_name in SECRET_FIELD_NAMES:
            continue
        assert getattr(reloaded, field_name) == getattr(settings, field_name), field_name


def test_a_none_valued_field_is_omitted_and_still_round_trips(tmp_path: Path) -> None:
    settings = _settings(tts_default_voice=None)
    assert settings.tts_default_voice is None
    xml = export_settings_xml(settings)
    assert "SIM_TTS_DEFAULT_VOICE" not in xml
    lines = settings_env_lines(xml)
    reloaded = _reload(tmp_path, lines)
    assert reloaded.tts_default_voice is None


def test_a_field_with_a_validation_alias_exports_under_its_real_env_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tts_model_variant` reads `SIM_TTS_QWEN3_MODEL`, not `SIM_TTS_MODEL_VARIANT`."""
    monkeypatch.setenv("SIM_TTS_QWEN3_MODEL", "0.6B")
    settings = _settings()
    assert settings.tts_model_variant == "0.6B"
    xml = export_settings_xml(settings)
    assert 'name="SIM_TTS_QWEN3_MODEL">0.6B<' in xml
    assert "SIM_TTS_MODEL_VARIANT" not in xml


@pytest.mark.parametrize(
    "xml",
    [
        "<settings",  # not well-formed
        '<config version="1"></config>',  # wrong root
        '<settings version="2"></settings>',  # wrong version
        '<settings version="1"><setting/></settings>',  # missing name
        '<settings version="1"><other name="SIM_LOG_FORMAT">json</other></settings>',  # wrong child
    ],
)
def test_a_malformed_document_is_refused(xml: str) -> None:
    with pytest.raises(SettingsXmlError):
        settings_env_lines(xml)


def test_an_unknown_setting_name_is_refused() -> None:
    with pytest.raises(SettingsXmlError, match="unknown"):
        settings_env_lines(
            '<settings version="1"><setting name="SIM_NO_SUCH_SETTING">x</setting></settings>'
        )


@pytest.mark.parametrize("field_name", sorted(SECRET_FIELD_NAMES))
def test_every_secret_name_is_refused_on_import(field_name: str) -> None:
    env_name = f"SIM_{field_name.upper()}"
    with pytest.raises(SettingsXmlError, match="secret"):
        settings_env_lines(
            f'<settings version="1"><setting name="{env_name}">x</setting></settings>'
        )


def test_a_value_that_does_not_fit_its_type_is_refused() -> None:
    with pytest.raises(SettingsXmlError):
        settings_env_lines(
            '<settings version="1">'
            '<setting name="SIM_LOG_FORMAT">not-a-real-format</setting>'
            "</settings>"
        )
    with pytest.raises(SettingsXmlError):
        settings_env_lines(
            '<settings version="1"><setting name="SIM_API_PORT">not-a-number</setting></settings>'
        )


def test_a_repeated_name_is_refused() -> None:
    xml = (
        '<settings version="1">'
        '<setting name="SIM_LOG_FORMAT">json</setting>'
        '<setting name="SIM_LOG_FORMAT">text</setting>'
        "</settings>"
    )
    with pytest.raises(SettingsXmlError, match="repeated"):
        settings_env_lines(xml)
