from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows environments
    winreg = None


APP_NAME = "GoPro-Webcam"
SETTINGS_FILENAME = "settings.json"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REGISTRY_VALUE = "GoPro-Webcam"


@dataclass
class AppSettings:
    launch_at_startup: bool = False
    launch_with_view: bool = False
    network_stream_host: str = ""


def _get_settings_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def get_settings_path() -> Path:
    return _get_settings_dir() / SETTINGS_FILENAME


def load_settings() -> AppSettings:
    settings_path = get_settings_path()
    if not settings_path.exists():
        return AppSettings()

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    return AppSettings(
        launch_at_startup=bool(payload.get("launch_at_startup", False)),
        launch_with_view=bool(payload.get("launch_with_view", False)),
        network_stream_host=str(payload.get("network_stream_host", "")).strip(),
    )


def save_settings(settings: AppSettings) -> None:
    settings_path = get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def _build_startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'

    project_root = Path(__file__).resolve().parent.parent
    main_script = project_root / "main.py"
    return f'"{sys.executable}" "{main_script}"'


def set_launch_at_startup(enabled: bool) -> bool:
    if winreg is None:
        return False

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH) as registry_key:
            if enabled:
                winreg.SetValueEx(registry_key, STARTUP_REGISTRY_VALUE, 0, winreg.REG_SZ, _build_startup_command())
            else:
                try:
                    winreg.DeleteValue(registry_key, STARTUP_REGISTRY_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def apply_settings(settings: AppSettings) -> bool:
    save_settings(settings)
    return set_launch_at_startup(settings.launch_at_startup)


def load_and_sync_settings() -> AppSettings:
    settings = load_settings()
    set_launch_at_startup(settings.launch_at_startup)
    return settings