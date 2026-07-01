# Shim de compatibilité (supprimé en Phase 3) — la logique vit dans sporia.enrich.soil_dynamic.
import sys

from sporia.enrich import soil_dynamic as _mod

sys.modules[__name__] = _mod
