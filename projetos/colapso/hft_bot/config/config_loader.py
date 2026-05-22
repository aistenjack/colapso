import json
import dataclasses
import os
from typing import Any

from config.settings import Settings
from core.logger import Log

_JSON_MAP: dict[str, str] = {
    "account": "mt5",
    "trading": "trading",
    "risk": "risk",
    "execution": "risk",
    "strategy": "signal",
    "position": "position",
    "session": "session",
    "system": "system",
    "hft": "hft",
}

_STRATEGY_TRADING_FIELDS: set[str] = {"take_profit_ticks", "stop_loss_ticks"}

_SECRET_FIELDS: set[str] = {"password"}

_LOADED_PATHS: set[str] = set()


def load_user_config(path: str, settings: Settings) -> Settings:
    if path in _LOADED_PATHS:
        return settings
    _LOADED_PATHS.add(path)

    log = Log.get("system")

    if not os.path.isfile(path):
        log.info("Config do usuário não encontrado: %s — usando defaults", path)
        return settings

    log.info("Carregando config do usuário: %s", path)

    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        log.warning("JSON inválido em %s: %s — usando defaults", path, e)
        return settings
    except Exception as e:
        log.warning("Erro lendo %s: %s — usando defaults", path, e)
        return settings

    if not isinstance(raw, dict):
        log.warning("JSON raiz não é objeto em %s — usando defaults", path)
        return settings

    applied = 0
    skipped = 0

    for section_key, section_data in raw.items():
        if not isinstance(section_data, dict):
            log.warning("Seção '%s' não é objeto — ignorada", section_key)
            skipped += 1
            continue

        settings_attr = _JSON_MAP.get(section_key)
        if settings_attr is None:
            log.warning("Seção desconhecida '%s' — ignorada", section_key)
            skipped += 1
            continue

        if section_key == "strategy":
            a, s = _apply_strategy_section(section_data, settings, log)
            applied += a
            skipped += s
            continue

        dc = getattr(settings, settings_attr, None)
        if dc is None:
            log.warning("Settings.%s não existe — seção '%s' ignorada", settings_attr, section_key)
            skipped += 1
            continue

        a, s = _apply_section(section_data, dc, section_key, log)
        applied += a
        skipped += s

    log.info("Config do usuário: %d campos aplicados, %d ignorados", applied, skipped)
    return settings


def _apply_section(data: dict, dc: Any, section_name: str, log) -> tuple[int, int]:
    applied = 0
    skipped = 0

    for key, value in data.items():
        if not hasattr(dc, key):
            log.warning("Campo desconhecido '%s' na seção '%s' — ignorado", key, section_name)
            skipped += 1
            continue

        current = getattr(dc, key)
        coerced = _coerce(value, type(current), key, section_name, log)
        if coerced is not None:
            setattr(dc, key, coerced)
            if key in _SECRET_FIELDS:
                log.info("  %s.%s = ***", section_name, key)
            else:
                log.info("  %s.%s = %s", section_name, key, coerced)
            applied += 1
        else:
            skipped += 1

    return applied, skipped


def _apply_strategy_section(data: dict, settings: Settings, log) -> tuple[int, int]:
    applied = 0
    skipped = 0

    trading_fields: dict[str, Any] = {}
    signal_fields: dict[str, Any] = {}

    for key, value in data.items():
        if key in _STRATEGY_TRADING_FIELDS:
            trading_fields[key] = value
        else:
            signal_fields[key] = value

    if trading_fields:
        a, s = _apply_section(trading_fields, settings.trading, "strategy→trading", log)
        applied += a
        skipped += s

    if signal_fields:
        a, s = _apply_section(signal_fields, settings.signal, "strategy→signal", log)
        applied += a
        skipped += s

    return applied, skipped


def _coerce(value: Any, target_type: type, key: str, section: str, log) -> Any:
    try:
        if isinstance(value, target_type):
            return value
        return target_type(value)
    except (TypeError, ValueError) as e:
        log.warning("Tipo inválido para %s.%s: esperado %s, recebido %s (%s) — mantendo default", section, key, target_type.__name__, type(value).__name__, value)
        return None
