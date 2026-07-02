# Shim de compatibilité (scripts legacy) — la surface API vit désormais dans sporia.api.
import sys

from sporia import api as _mod

sys.modules[__name__] = _mod
