#!/usr/bin/env python3
"""yt collect runs this on a finished yt-code task (harness.yaml evals:): pass or fail on the last line."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "yt-core", "lib"))
from ytlib import evalkit  # noqa: E402

sys.exit(evalkit.main([("a commit of the task branch", r"\b[0-9a-f]{7,40}\b")]))
