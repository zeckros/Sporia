# Shim de compatibilité (supprimé en Phase 3) — la logique vit dans sporia.pipeline.wx_features.
import sys

from sporia.pipeline import wx_features as _mod

sys.modules[__name__] = _mod
