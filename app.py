from __future__ import annotations

import difflib
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
from branca.colormap import LinearColormap
from streamlit_folium import st_folium
import json

# =============================================================================
# Configuración general
# =============================================================================
st.set_page_config(
    page_title="Demanda del Subte de Buenos Aires",
    page_icon="🚇",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DASHBOARD_PATH = DATA_DIR / "dashboard.json"

URL_ESTACIONES = (
    "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/sbase/"
    "subte-estaciones/estaciones_de_subte.geojson"
)
URL_LINEAS = (
    "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/sbase/"
    "subte-estaciones/red_subte.geojson"
)

COLORES_LINEAS = {
    "A": "#00A6D6",
    "B": "#E32636",
    "C": "#0066A1",
    "D": "#00843D",
    "E": "#7B2D8E",
    "H": "#F2CF00",
}

COLUMNAS_BASE = [
    "FECHA_DT", "HORA", "LINEA", "ESTACION", "PASAJEROS_REALES",
    "PRED_REGRESION_LINEAL", "PRED_RANDOM_FOREST",
    "PRED_GRADIENT_BOOSTING", "PRED_BASELINE",
]
COLUMNAS_PREDICCION = {
    "Demanda real observada": "PASAJEROS_REALES",
    "Regresión Lineal": "PRED_REGRESION_LINEAL",
    "Random Forest": "PRED_RANDOM_FOREST",
    "Gradient Boosting": "PRED_GRADIENT_BOOSTING",
    "Baseline histórico": "PRED_BASELINE",
}

# Equivalencias entre los nombres del GeoJSON y los usados en los molinetes.
# La búsqueda se restringe a la misma línea para evitar asociaciones incorrectas.
ALIAS_ESTACIONES = {
    "R SCALABRINI ORTIZ": ["SCALABRINI ORTIZ", "RAUL SCALABRINI ORTIZ"],
    "C PELLEGRINI": ["CARLOS PELLEGRINI"],
    "AV DE MAYO": ["AVENIDA DE MAYO"],
    "ONCE 30 DE DICIEMBRE": ["ONCE", "ONCE 30 DE DICIEMBRE"],
    "PLAZA DE MISERERE": ["PLAZA MISERERE", "ONCE"],
    "CONGRESO PDTE DR RAUL ALFONSIN": ["CONGRESO"],
    "JUAN MANUEL DE ROSAS VILLA URQUIZA": ["JUAN MANUEL DE ROSAS", "VILLA URQUIZA"],
    "TRONADOR VILLA ORTUZAR": ["TRONADOR"],
    "DE LOS INCAS PQE CHAS": ["DE LOS INCAS", "LOS INCAS"],
    "MINISTRO CARRANZA MIGUEL ABUELO": ["MINISTRO CARRANZA"],
    "MALABIA OSVALDO PUGLIESE": ["MALABIA"],
    "CALLAO MAESTRO ALFREDO BRAVO": ["CALLAO"],
    "SANTA FE CARLOS JAUREGUI": ["SANTA FE"],
    "FACULTAD DE DERECHO JULIETA LANTERI": ["FACULTAD DE DERECHO"],
    "INDEPENDENCIA BEATA MAMA ANTULA": ["INDEPENDENCIA"],
    "HOSPITALES RINGO BONAVENA": ["HOSPITALES"],
    "ECHEVERRIA MARTIRES PALOTINOS": ["ECHEVERRIA"],
    "PLAZA DE LOS VIRREYES EVA PERON": ["PLAZA DE LOS VIRREYES"],
    "TRIBUNALES TEATRO COLON": ["TRIBUNALES"],
    "PASTEUR AMIA": ["PASTEUR"],
    "ENTRE RIOS RODOLFO WALSH": ["ENTRE RIOS"],
    "JOSE MARIA MORENO": ["JOSE MARIA MORENO"],
    "RIO DE JANEIRO": ["RIO DE JANEIRO"],
}


def normalizar_nombre(valor: Any) -> str:
    if pd.isna(valor):
        return ""
    texto = str(valor).upper().strip()
    for sufijo in [".A", ".B", ".C", ".D", ".E", ".H"]:
        if texto.endswith(sufijo):
            texto = texto[:-len(sufijo)].strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return " ".join(texto.split())


def normalizar_linea(valor: Any) -> str:
    if pd.isna(valor):
        return ""
    linea = str(valor).upper().strip()
    linea = linea.replace("LÍNEA", "").replace("LINEA", "")
    return re.sub(r"[^A-Z]", "", linea)

# =============================================================================
# Carga del dashboard.json
# =============================================================================

@st.cache_data(show_spinner="Cargando los resultados del dashboard...")
def cargar_dashboard():

    if not DASHBOARD_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró dashboard.json en: {DASHBOARD_PATH}"
        )

    try:
        with open(DASHBOARD_PATH, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)

    except json.JSONDecodeError as error:
        raise ValueError(
            f"El archivo dashboard.json no contiene un JSON válido: {error}"
        )

    if not isinstance(datos, dict):
        raise ValueError("La estructura principal del JSON debe ser un objeto.")

    if datos.get("version") != 2:
        raise ValueError(
            f"Versión de dashboard no compatible: {datos.get('version')}"
        )

    if "estaciones" not in datos:
        raise ValueError("El JSON no contiene la sección 'estaciones'.")

    estaciones = pd.DataFrame(datos["estaciones"])

    columnas_requeridas = ["id", "nombre", "linea"]
    faltantes = [
        columna for columna in columnas_requeridas
        if columna not in estaciones.columns
    ]

    if faltantes:
        raise ValueError(
            "La sección estaciones no contiene: " + ", ".join(faltantes)
        )

    estaciones["nombre"] = estaciones["nombre"].astype(str).str.strip()
    estaciones["linea"] = estaciones["linea"].apply(normalizar_linea)

    return datos, estaciones
# =============================================================================
# Capas geográficas oficiales de Buenos Aires Data / SBASE
# =============================================================================
@st.cache_data(ttl=24 * 60 * 60, show_spinner="Cargando el mapa oficial del Subte...")
def cargar_geojson(url: str) -> dict:
    respuesta = requests.get(url, timeout=35)
    respuesta.raise_for_status()
    contenido = respuesta.json()
    if contenido.get("type") != "FeatureCollection":
        raise ValueError("El recurso geográfico no tiene formato GeoJSON FeatureCollection.")
    return contenido


def extraer_estaciones(geojson: dict) -> pd.DataFrame:
    filas = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coords) < 2:
            continue
        filas.append({
            "ESTACION_GEO": props.get("estacion", ""),
            "LINEA": normalizar_linea(props.get("linea", "")),
            "LONGITUD": float(coords[0]),
            "LATITUD": float(coords[1]),
        })

    estaciones = pd.DataFrame(filas)
    if estaciones.empty:
        raise ValueError("No se encontraron estaciones en el GeoJSON oficial.")
    estaciones["ESTACION_GEO_NORM"] = estaciones["ESTACION_GEO"].apply(normalizar_nombre)
    return estaciones


def encontrar_nombre_base(nombre_geo: str, linea: str, nombres_por_linea: dict) -> str | None:
    candidatos = nombres_por_linea.get(linea, [])
    if not candidatos:
        return None

    nombre_norm = normalizar_nombre(nombre_geo)
    por_normalizado = {normalizar_nombre(nombre): nombre for nombre in candidatos}
    if nombre_norm in por_normalizado:
        return por_normalizado[nombre_norm]

    for alias in ALIAS_ESTACIONES.get(nombre_norm, []):
        alias_norm = normalizar_nombre(alias)
        if alias_norm in por_normalizado:
            return por_normalizado[alias_norm]

    for clave_geo, alias_lista in ALIAS_ESTACIONES.items():
        alias_norms = [normalizar_nombre(a) for a in alias_lista]
        if nombre_norm in alias_norms:
            clave_norm = normalizar_nombre(clave_geo)
            if clave_norm in por_normalizado:
                return por_normalizado[clave_norm]

    mejor_nombre = None
    mejor_puntaje = 0.0
    for candidato in candidatos:
        puntaje = difflib.SequenceMatcher(
            None, nombre_norm, normalizar_nombre(candidato)
        ).ratio()
        if puntaje > mejor_puntaje:
            mejor_puntaje = puntaje
            mejor_nombre = candidato
    return mejor_nombre if mejor_puntaje >= 0.86 else None


def vincular_estaciones(estaciones: pd.DataFrame, pred: pd.DataFrame) -> pd.DataFrame:
    nombres_por_linea = (
        pred[["LINEA", "ESTACION"]]
        .drop_duplicates()
        .groupby("LINEA")["ESTACION"]
        .apply(list)
        .to_dict()
    )
    resultado = estaciones.copy()
    resultado["ESTACION_BASE"] = resultado.apply(
        lambda fila: encontrar_nombre_base(
            fila["ESTACION_GEO"], fila["LINEA"], nombres_por_linea
        ),
        axis=1,
    )
    return resultado


def construir_mapa(
    estaciones: pd.DataFrame,
    lineas_geojson: dict,
    demanda: pd.DataFrame,
    lineas_seleccionadas: list[str],
    etiqueta_metrica: str,
    tipo_agregacion: str,
) -> folium.Map:
    mapa = folium.Map(
        location=[-34.608, -58.425],
        zoom_start=12,
        control_scale=True,
        tiles="CartoDB positron",
    )

    features_linea = []
    for feature in lineas_geojson.get("features", []):
        nombre = str(feature.get("properties", {}).get("nombre", "")).upper()
        match = re.search(r"([A-H])\s*$", nombre)
        codigo = match.group(1) if match else ""
        if codigo in lineas_seleccionadas:
            features_linea.append(feature)

    def estilo_linea(feature: dict) -> dict:
        nombre = str(feature.get("properties", {}).get("nombre", "")).upper()
        match = re.search(r"([A-H])\s*$", nombre)
        codigo = match.group(1) if match else ""
        return {
            "color": COLORES_LINEAS.get(codigo, "#555555"),
            "weight": 5,
            "opacity": 0.9,
        }

    grupo_lineas = folium.FeatureGroup(name="Recorridos oficiales", show=True)
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features_linea},
        name="Líneas de Subte",
        style_function=estilo_linea,
        tooltip=folium.GeoJsonTooltip(fields=["nombre"], aliases=["Recorrido:"]),
    ).add_to(grupo_lineas)
    grupo_lineas.add_to(mapa)

    datos = estaciones[estaciones["LINEA"].isin(lineas_seleccionadas)].copy()
    datos = datos.merge(demanda, on=["LINEA", "ESTACION_BASE"], how="left")

    valores = datos["VALOR_MAPA"].dropna()
    minimo = max(0.0, float(valores.min())) if not valores.empty else 0.0
    maximo = float(valores.max()) if not valores.empty else 1.0
    if maximo <= minimo:
        maximo = minimo + 1.0

    escala = LinearColormap(
        colors=["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"],
        vmin=minimo,
        vmax=maximo,
    )
    escala.caption = f"{etiqueta_metrica} ({tipo_agregacion.lower()})"
    escala.add_to(mapa)

    grupo_estaciones = folium.FeatureGroup(name="Estaciones y demanda", show=True)
    for _, fila in datos.iterrows():
        valor = fila.get("VALOR_MAPA")
        tiene_datos = pd.notna(valor)
        valor_num = max(float(valor), 0.0) if tiene_datos else 0.0
        color_relleno = escala(valor_num) if tiene_datos else "#9E9E9E"
        color_borde = COLORES_LINEAS.get(fila["LINEA"], "#444444")

        if tiene_datos:
            radio = 5 + 10 * math.sqrt(valor_num / maximo)
            if tipo_agregacion == "Total del período":
                detalle = f"{valor_num:,.0f} pasajeros"
            else:
                detalle = f"{valor_num:,.1f} pasajeros por registro horario"
        else:
            radio = 5
            detalle = "Sin registros para los filtros seleccionados"

        popup_html = f"""
        <div style='font-family:Arial; min-width:210px;'>
            <b>{fila['ESTACION_GEO']}</b><br>
            Línea: {fila['LINEA']}<br>
            {etiqueta_metrica}: {detalle}
        </div>
        """
        folium.CircleMarker(
            location=[fila["LATITUD"], fila["LONGITUD"]],
            radius=radio,
            color=color_borde,
            weight=2,
            fill=True,
            fill_color=color_relleno,
            fill_opacity=0.9 if tiene_datos else 0.5,
            tooltip=f"{fila['ESTACION_GEO']} · Línea {fila['LINEA']}",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(grupo_estaciones)

    grupo_estaciones.add_to(mapa)
    folium.LayerControl(collapsed=False).add_to(mapa)
    return mapa


# =============================================================================
# Interfaz principal
# =============================================================================
st.title("🚇 Demanda de pasajeros del Subte de Buenos Aires")
st.markdown(
    "Exploración geográfica y comparación de los modelos de predicción "
    "entrenados en el notebook del Grupo 13."
)
st.caption(
    "Resultados finales del conjunto de prueba: enero–junio de 2026. "
    "Los datos se cargan automáticamente; no es necesario subir archivos."
)

try:
    dashboard, estaciones_json = cargar_dashboard()

    st.success(
        f"Dashboard cargado correctamente. "
        f"Estaciones disponibles: {len(estaciones_json)}"
    )

except Exception as exc:
    st.error(f"No se pudo cargar dashboard.json: {exc}")
    st.stop()

# Mostrar de forma visible el período realmente incluido en el archivo.
fecha_min = df_pred["FECHA_DT"].min().date()
fecha_max = df_pred["FECHA_DT"].max().date()

with st.sidebar:
    st.header("Filtros")
    st.caption("Los filtros afectan al mapa y al resumen por estación.")

    lineas_disponibles = sorted(df_pred["LINEA"].dropna().unique().tolist())
    lineas_seleccionadas = st.multiselect(
        "Líneas de subte",
        options=lineas_disponibles,
        default=lineas_disponibles,
        format_func=lambda x: f"Línea {x}",
    )

    fechas = st.date_input(
        "Período del conjunto de prueba",
        value=(fecha_min, fecha_max),
        min_value=fecha_min,
        max_value=fecha_max,
        format="DD/MM/YYYY",
    )
    if isinstance(fechas, (tuple, list)) and len(fechas) == 2:
        fecha_inicio, fecha_fin = fechas
    else:
        fecha_inicio = fecha_fin = fechas

    horas_disponibles = sorted(df_pred["HORA"].dropna().astype(int).unique().tolist())
    hora_min = min(horas_disponibles) if horas_disponibles else 0
    hora_max = max(horas_disponibles) if horas_disponibles else 23
    hora_inicio, hora_fin = st.slider(
        "Franja horaria",
        min_value=hora_min,
        max_value=hora_max,
        value=(hora_min, hora_max),
        format="%d:00",
    )

    metrica_elegida = st.selectbox(
        "Indicador para el mapa",
        options=list(COLUMNAS_PREDICCION.keys()),
        index=0,
    )
    agregacion = st.radio(
        "Tipo de resumen",
        options=["Total del período", "Promedio por registro horario"],
        index=0,
    )

if not lineas_seleccionadas:
    st.warning("Seleccioná al menos una línea en el panel lateral.")
    st.stop()

if fecha_inicio > fecha_fin:
    st.warning("La fecha inicial no puede ser posterior a la fecha final.")
    st.stop()

columna_metrica = COLUMNAS_PREDICCION[metrica_elegida]
df_filtrado = df_pred[
    df_pred["FECHA_DT"].dt.date.between(fecha_inicio, fecha_fin)
    & df_pred["HORA"].between(hora_inicio, hora_fin)
    & df_pred["LINEA"].isin(lineas_seleccionadas)
].copy()

# Los modelos pueden producir valores negativos. Se limitan a cero únicamente
# para visualización, porque no existe una cantidad negativa de pasajeros.
negativos_visuales = 0
if columna_metrica != "PASAJEROS_REALES":
    negativos_visuales = int((df_filtrado[columna_metrica] < 0).sum())
    df_filtrado[columna_metrica] = df_filtrado[columna_metrica].clip(lower=0)

if agregacion == "Total del período":
    demanda = (
        df_filtrado.groupby(["LINEA", "ESTACION"], as_index=False)[columna_metrica]
        .sum()
        .rename(columns={"ESTACION": "ESTACION_BASE", columna_metrica: "VALOR_MAPA"})
    )
else:
    demanda = (
        df_filtrado.groupby(["LINEA", "ESTACION"], as_index=False)[columna_metrica]
        .mean()
        .rename(columns={"ESTACION": "ESTACION_BASE", columna_metrica: "VALOR_MAPA"})
    )

# La geometría se descarga automáticamente desde Buenos Aires Data / SBASE.
try:
    with st.spinner("Preparando las estaciones y recorridos oficiales..."):
        geo_estaciones = cargar_geojson(URL_ESTACIONES)
        geo_lineas = cargar_geojson(URL_LINEAS)
        estaciones = vincular_estaciones(extraer_estaciones(geo_estaciones), df_pred)
except Exception as exc:
    st.error(
        "No se pudieron obtener las capas geográficas oficiales del Subte. "
        "La aplicación necesita conexión a internet para cargar el mapa."
    )
    st.caption(f"Detalle técnico: {exc}")
    st.stop()

# Indicadores generales.
combinaciones_estacion_linea = df_pred[["LINEA", "ESTACION"]].drop_duplicates().shape[0]
estaciones_vinculadas = estaciones[
    estaciones["LINEA"].isin(lineas_seleccionadas)
    & estaciones["ESTACION_BASE"].notna()
]
mapa_datos = estaciones[
    estaciones["LINEA"].isin(lineas_seleccionadas)
].merge(demanda, on=["LINEA", "ESTACION_BASE"], how="left")

if agregacion == "Total del período":
    valor_kpi = float(demanda["VALOR_MAPA"].sum()) if not demanda.empty else 0.0
    formato_kpi = f"{valor_kpi:,.0f}"
    etiqueta_kpi = "Pasajeros del indicador seleccionado"
else:
    valor_kpi = float(demanda["VALOR_MAPA"].mean()) if not demanda.empty else 0.0
    formato_kpi = f"{valor_kpi:,.1f}"
    etiqueta_kpi = "Promedio por estación y registro horario"

k1, k2, k3, k4 = st.columns(4)
k1.metric("Registros filtrados", f"{len(df_filtrado):,}")
k2.metric("Líneas seleccionadas", len(lineas_seleccionadas))
k3.metric("Estaciones geográficas vinculadas", f"{len(estaciones_vinculadas)}")
k4.metric(etiqueta_kpi, formato_kpi)

if negativos_visuales:
    st.info(
        f"Para esta selección se encontraron {negativos_visuales:,} predicciones negativas. "
        "En el mapa se representan como cero pasajeros; los archivos originales no se modifican."
    )

pestana_mapa, pestana_comparacion = st.tabs(["🗺️ Mapa de demanda", "📈 Real vs. predicho"])

with pestana_mapa:
    st.subheader("Mapa de estaciones y demanda")
    st.caption(
        f"{metrica_elegida} · {agregacion.lower()} · "
        f"{fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')} · "
        f"horas {hora_inicio:02d}:00 a {hora_fin:02d}:00"
    )

    mapa = construir_mapa(
        estaciones=estaciones,
        lineas_geojson=geo_lineas,
        demanda=demanda,
        lineas_seleccionadas=lineas_seleccionadas,
        etiqueta_metrica=metrica_elegida,
        tipo_agregacion=agregacion,
    )
    st_folium(mapa, width=None, height=690, returned_objects=[], key="mapa_subte")

    sin_coincidencia = estaciones[
        estaciones["LINEA"].isin(lineas_seleccionadas)
        & estaciones["ESTACION_BASE"].isna()
    ]
    if not sin_coincidencia.empty:
        with st.expander(f"Estaciones sin coincidencia con los datos ({len(sin_coincidencia)})"):
            st.warning(
                "Estas estaciones están en la cartografía oficial, pero sus nombres no "
                "se pudieron asociar automáticamente con el CSV de predicciones."
            )
            st.dataframe(
                sin_coincidencia[["LINEA", "ESTACION_GEO"]]
                .sort_values(["LINEA", "ESTACION_GEO"]),
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("Ranking de estaciones según el indicador seleccionado"):
        ranking = demanda.merge(
            estaciones[["LINEA", "ESTACION_BASE", "ESTACION_GEO"]].drop_duplicates(),
            on=["LINEA", "ESTACION_BASE"],
            how="left",
        )
        ranking = ranking.sort_values("VALOR_MAPA", ascending=False)
        ranking = ranking.rename(columns={
            "LINEA": "Línea",
            "ESTACION_GEO": "Estación",
            "VALOR_MAPA": "Valor",
        })
        st.dataframe(
            ranking[["Línea", "Estación", "Valor"]],
            use_container_width=True,
            hide_index=True,
        )

with pestana_comparacion:
    st.subheader("Demanda real y predicciones: estación Constitución")
    st.caption(
        "Serie de comparación exportada desde el notebook para la línea C, "
        "del 6 al 12 de abril de 2026."
    )

    opciones_modelos = {
        "Regresión Lineal": "PRED_REGRESION_LINEAL",
        "Random Forest": "PRED_RANDOM_FOREST",
        "Gradient Boosting": "PRED_GRADIENT_BOOSTING",
        "Baseline histórico": "PRED_BASELINE",
    }
    modelo_grafico = st.selectbox(
        "Modelo para comparar",
        options=list(opciones_modelos.keys()),
        index=2,
        key="modelo_grafico",
    )
    columna_pred = opciones_modelos[modelo_grafico]

    serie_grafico = df_serie[["FECHA_HORA", "PASAJEROS_REALES", columna_pred]].copy()
    serie_grafico[columna_pred] = serie_grafico[columna_pred].clip(lower=0)
    serie_grafico = serie_grafico.rename(columns={
        "PASAJEROS_REALES": "Demanda real",
        columna_pred: f"Predicción {modelo_grafico}",
    }).set_index("FECHA_HORA")
    st.line_chart(serie_grafico, height=390, use_container_width=True)

    valores_reales = df_serie["PASAJEROS_REALES"].sum()
    valores_predichos = df_serie[columna_pred].clip(lower=0).sum()
    diferencia = valores_predichos - valores_reales
    c1, c2, c3 = st.columns(3)
    c1.metric("Pasajeros reales (serie)", f"{valores_reales:,.0f}")
    c2.metric(f"Pasajeros estimados ({modelo_grafico})", f"{valores_predichos:,.0f}")
    c3.metric("Diferencia acumulada", f"{diferencia:+,.0f}")

    with st.expander("Consultar registros de la serie comparativa"):
        tabla_serie = df_serie[[
            "FECHA_HORA", "PASAJEROS_REALES", columna_pred
        ]].rename(columns={
            "FECHA_HORA": "Fecha y hora",
            "PASAJEROS_REALES": "Pasajeros reales",
            columna_pred: f"Predicción {modelo_grafico}",
        })
        st.dataframe(tabla_serie, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Datos de pasajeros: resultados finales exportados desde el notebook del Grupo 13. "
    "Cartografía: Buenos Aires Data / Subterráneos de Buenos Aires (SBASE), licencia CC-BY-2.5-AR. "
    "Las predicciones corresponden al conjunto de prueba y no representan demanda en tiempo real."
)
