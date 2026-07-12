# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Enable ``python -m pg_llm_batch``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
