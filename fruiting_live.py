# Shim de compatibilité (supprimé en Phase 3) — la logique vit dans sporia.enrich.fruiting_live.
import sys

from sporia.enrich import fruiting_live as _mod

sys.modules[__name__] = _mod
