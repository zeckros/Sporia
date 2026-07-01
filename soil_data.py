# Shim de compatibilité (supprimé en Phase 3) — la logique vit dans sporia.enrich.soil_static.
import sys

from sporia.enrich import soil_static as _mod

sys.modules[__name__] = _mod
