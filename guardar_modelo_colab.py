# Ejecutar en Google Colab DESPUÉS de entrenar el modelo Gradient Boosting.
# El notebook debe tener la variable `modelo_gb` ya entrenada.

import joblib
from google.colab import files

ruta_modelo = "/content/modelo_gradient_boosting.joblib"
joblib.dump(modelo_gb, ruta_modelo)
print("Modelo guardado en:", ruta_modelo)
files.download(ruta_modelo)

# Opcional: descargar también la base horaria consolidada.
# files.download("/content/base_horaria_subte_2023_2026.parquet")
