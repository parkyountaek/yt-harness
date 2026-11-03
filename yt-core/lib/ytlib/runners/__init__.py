"""Runner adapters. Each module implements the same contract:

  spawn(name, cwd, argv, env) -> handle      start the sub-session, return a runner handle
  send(handle, text) -> int                  type text into the session and press Enter
  attach(handle) -> int                      hand the terminal to the human (blocks)
  stop(handle) -> int                        end the session; no processes left
  alive(handle) -> bool                      is the session still running
"""
import importlib

DEFAULT = "tmux"


def load(name=None):
    return importlib.import_module(f"{__name__}.{name or DEFAULT}")
