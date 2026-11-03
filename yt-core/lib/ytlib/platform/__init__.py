"""OS detection and platform backend loading.

Everything that differs between operating systems lives in one module per
platform. Each module implements the same contract:

  NAME: str                               platform id
  package_manager() -> str | None         "brew", "apt", "dnf", "winget", "scoop", or None
  install(packages: list[str]) -> int     install packages, return exit code
  upgrade(packages: list[str]) -> int     upgrade installed packages, return exit code
  sandbox_problem() -> str | None         why sub-sessions cannot be sandboxed here, or None
  sandbox_argv(policy, runtime, cmd, profile_dir, extra_read, tmp_dir, cwd)
                                          argv that runs cmd inside the shared sandbox

Package names per package manager live in yt-core/deps.json, not in these modules.
"""
import importlib
import os
import platform as _platform


def detect():
    system = _platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        try:
            with open("/proc/version", encoding="utf-8") as f:
                if "microsoft" in f.read().lower():
                    return "wsl"
        except OSError:
            pass
        return "linux"
    if system == "Windows" or os.name == "nt":
        return "windows"
    return "unknown"


SUPPORTED = {"macos": "macos", "linux": "linux", "wsl": "linux", "windows": "windows"}


class UnsupportedPlatform(RuntimeError):
    pass


def load(os_id=None):
    os_id = os_id or detect()
    if os_id not in SUPPORTED:
        raise UnsupportedPlatform(f"Unsupported platform: {os_id}")
    module = importlib.import_module(f"{__name__}.{SUPPORTED[os_id]}")
    module.OS_ID = os_id
    return module
