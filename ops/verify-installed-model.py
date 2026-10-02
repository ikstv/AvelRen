"""Перевірка frozen моделі саме встановленого wheel, без source mounts/мережі."""
import importlib.metadata
import json
from pathlib import Path

from avelren import surge_model

module_path = Path(surge_model.__file__).resolve()
if "site-packages" not in module_path.parts:
    raise RuntimeError("Перевірка має використовувати встановлений пакет")
files = importlib.metadata.distribution("avelren").files or ()
if "avelren/models/surge_24h_v1.json" not in {str(path) for path in files}:
    raise RuntimeError("Файл моделі відсутній у встановленому wheel")
model = surge_model.frozen_model()
assert len(model.mean) == len(model.std) == 15
assert len(model.coefficients) == 16
print(json.dumps({"installed_model": "PASS", "model_version": surge_model.MODEL_VERSION}))
