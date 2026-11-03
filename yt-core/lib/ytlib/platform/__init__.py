"""OS detection and platform backend loading.

Everything that differs between operating systems lives in one module per
platform. Each module implements the same contract:

  NAME: str                               platform id
  package_manager() -> str | None         "brew", "apt", "dnf", or None
  install(packages: list[str]) -> int     install packages, return exit code
  sandbox_argv(policy, runtime, cmd)      argv that runs cmd inside the shared sandbox
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


SUPPORTED = {"macos": "macos", "linux": "linux", "wsl": "linux"}


class UnsupportedPlatform(RuntimeError):
    pass


def load(os_id=None):
    os_id = os_id or detect()
    if os_id == "windows":
        raise UnsupportedPlatform(
            "Native Windows is not supported. Install WSL2 (wsl --install), "
            "then run yt-setup inside the WSL2 Linux shell.")
    if os_id not in SUPPORTED:
        raise UnsupportedPlatform(f"Unsupported platform: {os_id}")
    module = importlib.import_module(f"{__name__}.{SUPPORTED[os_id]}")
    module.OS_ID = os_id
    return module
