# Shim de compatibilité (supprimé en Phase 3) — la logique vit dans sporia.enrich.forest.
import sys

from sporia.enrich import forest as _mod

sys.modules[__name__] = _mod
