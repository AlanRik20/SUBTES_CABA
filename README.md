# Mapa de demanda del Subte de Buenos Aires - Streamlit

Aplicación para visualizar las estaciones y los recorridos oficiales del Subte de Buenos Aires sobre un mapa interactivo. Cada estación se representa con un círculo: su color y tamaño reflejan la demanda seleccionada.

## 1. Archivos del proyecto

```text
subte_streamlit/
├── app.py
├── requirements.txt
├── README.md
├── modelo_gradient_boosting.joblib      # opcional
└── data/
    └── base_horaria_subte_2023_2026.parquet
```

La aplicación también permite cargar el archivo Parquet o CSV desde el panel lateral, por lo que no es obligatorio dejarlo dentro de `data/` para probarla localmente.

## 2. Preparar los datos desde Google Colab

El notebook del proyecto ya genera este archivo:

```python
path_salida = '/content/base_horaria_subte_2023_2026.parquet'
df_consolidado.to_parquet(path_salida, index=False)
```

Para descargarlo desde Colab:

```python
from google.colab import files
files.download('/content/base_horaria_subte_2023_2026.parquet')
```

Para desplegar la aplicación sin tener que cargar el archivo cada vez, colocá el Parquet en la carpeta `data/` del repositorio. Si el archivo es demasiado grande para GitHub, mantenelo fuera del repositorio y cargalo desde el panel lateral al usar la aplicación.

## 3. Exportar el modelo (opcional)

Después de entrenar `modelo_gb` en el notebook, ejecutá:

```python
import joblib
from google.colab import files

joblib.dump(modelo_gb, '/content/modelo_gradient_boosting.joblib')
files.download('/content/modelo_gradient_boosting.joblib')
```

Colocá `modelo_gradient_boosting.joblib` en la carpeta raíz del proyecto, junto a `app.py`. Cuando el archivo esté disponible, la aplicación habilitará la opción **Predicción Gradient Boosting**.

**Importante:** al cargar un modelo guardado con Joblib, la versión de `scikit-learn` del entorno de Streamlit debe coincidir con la versión utilizada para entrenarlo en Colab. Para consultarla en Colab:

```python
import sklearn
print(sklearn.__version__)
```

Si fuera necesario, fijá esa misma versión en `requirements.txt` (por ejemplo, `scikit-learn==1.x.x`).

## 4. Ejecutar localmente

Desde una terminal ubicada en la carpeta del proyecto:

```bash
python -m venv .venv
```

En Windows:

```bash
.venv\Scripts\activate
```

Instalá las dependencias y ejecutá:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 5. Publicar en Streamlit Community Cloud

1. Subí esta carpeta a un repositorio de GitHub.
2. Abrí Streamlit Community Cloud y elegí **New app**.
3. Seleccioná el repositorio, la rama y `app.py` como archivo principal.
4. Desplegá la aplicación.
5. Si el Parquet no está dentro de `data/`, cargalo desde el panel lateral de la aplicación.

## 6. Cómo funciona el mapa

- Las líneas se dibujan usando el GeoJSON oficial de la Ciudad.
- Las estaciones se ubican usando el GeoJSON oficial de estaciones.
- Los registros de molinetes se agrupan por línea y estación, respetando los filtros de fecha y hora.
- La unión de nombres se realiza mediante normalización, equivalencias conocidas y coincidencia aproximada dentro de cada línea.
- La aplicación informa qué estaciones no pudo vincular para facilitar la revisión de nombres.
- El modo observado ofrece el total acumulado o el promedio por registro horario.
- El modo de predicción utiliza el modelo Gradient Boosting exportado desde el notebook y permite elegir fecha, hora y condición de feriado.

Los valores son históricos o estimados por el modelo. No representan ocupación en tiempo real.

## Fuentes geográficas

- Buenos Aires Data / SBASE, [Estaciones de Subte (GeoJSON)](https://data.buenosaires.gob.ar/ar/dataset/subte-estaciones/resource/bea83c40-9400-4fe4-865b-f0f0610a060c).
- Buenos Aires Data / SBASE, [Líneas de Subte (GeoJSON)](https://data.buenosaires.gob.ar/dataset/juqdkmgo-199/resource/89fef3c6-c133-4eee-8612-510fad192e3a).

Los conjuntos geográficos se publican con licencia CC-BY-2.5-AR según la ficha del dataset.
