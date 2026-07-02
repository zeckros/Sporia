# Shim de compatibilité (supprimé en Phase 3) — la logique vit dans sporia.pipeline.interpret_day.
import sys

from sporia.pipeline import interpret_day as _mod

sys.modules[__name__] = _mod
