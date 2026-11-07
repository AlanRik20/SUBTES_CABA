# Mapa y Serie Temporal de Demanda del Subte de Buenos Aires - Streamlit

Aplicación interactiva desarrollada en **Streamlit** para explorar y visualizar la demanda estimada de pasajeros en la red de Subterráneos de Buenos Aires (SBASE). Combina capas geográficas oficiales en tiempo real con resultados preprocesados de demanda en un mapa interactivo y gráficos de series temporales.

---

## 1. Estructura del proyecto

```text
subte_streamlit/
├── app.py
├── dashboard_data.json
├── guardar_modelo_colab.py
├── requirements.txt
├── README.md
└── data/                       # Directorio reservado para conjuntos de datos adicionales
```

---

## 2. Instalación y ejecución local

1. Abrir una terminal en la carpeta raíz del proyecto y crear un entorno virtual:

```bash
python -m venv .venv
```

2. Activar el entorno virtual (en Windows):

```bash
.venv\Scripts\activate
```

3. Instalar las dependencias y ejecutar la aplicación:

```bash
pip install -r requirements.txt
streamlit run app.py
```

_(Nota: Asegurarse de que el archivo `dashboard_data.json` se encuentre en la raíz del proyecto junto a `app.py`)._

---

## 3. Fuentes de datos y cartografía

- **Estaciones de Subte (GeoJSON)**: [Buenos Aires Data / SBASE](https://data.buenosaires.gob.ar/ar/dataset/subte-estaciones/resource/bea83c40-9400-4fe4-865b-f0f0610a060c) (`estaciones_de_subte.geojson`).
- **Líneas de Subte (GeoJSON)**: [Buenos Aires Data / SBASE](https://data.buenosaires.gob.ar/dataset/juqdkmgo-199/resource/89fef3c6-c133-4eee-8612-510fad192e3a) (`red_subte.geojson`).

Los conjuntos de datos geográficos son publicados por el Gobierno de la Ciudad Autónoma de Buenos Aires bajo licencia **CC-BY-2.5-AR**.
