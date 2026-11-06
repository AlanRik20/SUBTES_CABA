from __future__ import annotations

import datetime
import difflib
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import folium
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

DASHBOARD_PATH = Path("dashboard_data.json")

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
# Carga del dashboard_data.json
# =============================================================================
@st.cache_data(show_spinner="Cargando los resultados del dashboard...")
def cargar_dashboard():
    if not DASHBOARD_PATH.exists():
        raise FileNotFoundError(f"No se encontró el archivo en: {DASHBOARD_PATH}")

    with open(DASHBOARD_PATH, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    estaciones = pd.DataFrame(datos["estaciones"])
    estaciones["nombre"] = estaciones["nombre"].astype(str).str.strip()
    estaciones["linea"] = estaciones["linea"].apply(normalizar_linea)

    registros = []
    for id_str, valores in datos["serie_diaria"].items():
        est_info = estaciones[estaciones["id"] == int(id_str)].iloc[0]
        valores_validos = [v for v in valores if v is not None]
        total = sum(valores_validos) if valores_validos else 0
        promedio = (total / len(valores_validos)) if valores_validos else 0

        registros.append({
            "LINEA": est_info["linea"],
            "ESTACION_BASE": est_info["nombre"],
            "VALOR_TOTAL": total,
            "VALOR_PROMEDIO": promedio,
            "SERIE": valores
        })

    df_demanda = pd.DataFrame(registros)
    return datos, estaciones, df_demanda

# =============================================================================
# Capas geográficas oficiales
# =============================================================================
@st.cache_data(ttl=24 * 60 * 60, show_spinner="Cargando el mapa oficial del Subte...")
def cargar_geojson(url: str) -> dict:
    respuesta = requests.get(url, timeout=35)
    respuesta.raise_for_status()
    return respuesta.json()

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
    estaciones["ESTACION_GEO_NORM"] = estaciones["ESTACION_GEO"].apply(normalizar_nombre)
    return estaciones

def encontrar_nombre_base(nombre_geo: str, linea: str, nombres_por_linea: dict) -> str | None:
    candidatos = nombres_por_linea.get(linea, [])
    if not candidatos: return None
    
    nombre_norm = normalizar_nombre(nombre_geo)
    por_normalizado = {normalizar_nombre(nombre): nombre for nombre in candidatos}
    
    if nombre_norm in por_normalizado: return por_normalizado[nombre_norm]
    for alias in ALIAS_ESTACIONES.get(nombre_norm, []):
        alias_norm = normalizar_nombre(alias)
        if alias_norm in por_normalizado: return por_normalizado[alias_norm]
    for clave_geo, alias_lista in ALIAS_ESTACIONES.items():
        if nombre_norm in [normalizar_nombre(a) for a in alias_lista]:
            clave_norm = normalizar_nombre(clave_geo)
            if clave_norm in por_normalizado: return por_normalizado[clave_norm]

    mejor_nombre, mejor_puntaje = None, 0.0
    for candidato in candidatos:
        puntaje = difflib.SequenceMatcher(None, nombre_norm, normalizar_nombre(candidato)).ratio()
        if puntaje > mejor_puntaje:
            mejor_puntaje, mejor_nombre = puntaje, candidato
    return mejor_nombre if mejor_puntaje >= 0.86 else None

def vincular_estaciones(estaciones: pd.DataFrame, df_demanda: pd.DataFrame) -> pd.DataFrame:
    nombres_por_linea = df_demanda.groupby("LINEA")["ESTACION_BASE"].apply(list).to_dict()
    resultado = estaciones.copy()
    resultado["ESTACION_BASE"] = resultado.apply(
        lambda fila: encontrar_nombre_base(fila["ESTACION_GEO"], fila["LINEA"], nombres_por_linea), axis=1
    )
    return resultado

def construir_mapa(estaciones, lineas_geojson, demanda, lineas_seleccionadas, etiqueta_metrica):
    # Uso de mapa libre OpenStreetMap para evitar requerimientos de API Key
    mapa = folium.Map(location=[-34.608, -58.425], zoom_start=12, tiles="OpenStreetMap")
    
    features_linea = []
    for f in lineas_geojson.get("features", []):
        match = re.search(r"([A-H])\s*$", str(f.get("properties", {}).get("nombre", "")).upper())
        if match and match.group(1) in lineas_seleccionadas:
            features_linea.append(f)

    folium.GeoJson(
        {"type": "FeatureCollection", "features": features_linea},
        style_function=lambda f: {
            "color": COLORES_LINEAS.get(re.search(r"([A-H])\s*$", str(f.get("properties", {}).get("nombre", "")).upper()).group(1) if re.search(r"([A-H])\s*$", str(f.get("properties", {}).get("nombre", "")).upper()) else "", "#555555"), 
            "weight": 5, 
            "opacity": 0.9
        }
    ).add_to(mapa)

    datos = estaciones[estaciones["LINEA"].isin(lineas_seleccionadas)].merge(demanda, on=["LINEA", "ESTACION_BASE"], how="left")
    valores = datos["VALOR_MAPA"].dropna()
    minimo, maximo = (max(0.0, float(valores.min())), float(valores.max())) if not valores.empty else (0.0, 1.0)
    if maximo <= minimo: maximo = minimo + 1.0

    escala = LinearColormap(colors=["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"], vmin=minimo, vmax=maximo)
    escala.caption = etiqueta_metrica
    escala.add_to(mapa)

    for _, fila in datos.iterrows():
        valor = fila.get("VALOR_MAPA")
        tiene_datos = pd.notna(valor)
        valor_num = max(float(valor), 0.0) if tiene_datos else 0.0
        color = escala(valor_num) if tiene_datos else "#9E9E9E"
        radio = 5 + 10 * math.sqrt(valor_num / maximo) if tiene_datos else 5
        detalle = f"{valor_num:,.0f} pasajeros estimados" if tiene_datos else "Sin registros"

        folium.CircleMarker(
            location=[fila["LATITUD"], fila["LONGITUD"]], radius=radio,
            color=COLORES_LINEAS.get(fila["LINEA"], "#444444"), weight=2,
            fill=True, fill_color=color, fill_opacity=0.9 if tiene_datos else 0.5,
            popup=f"<b>{fila['ESTACION_GEO']}</b><br>Línea {fila['LINEA']}<br>{detalle}"
        ).add_to(mapa)

    return mapa

# =============================================================================
# Interfaz principal
# =============================================================================
st.title("🚇 Demanda de pasajeros del Subte de Buenos Aires")
st.markdown("Exploración interactiva y serie temporal de la demanda estimada a partir de los datos procesados.")

try:
    meta_datos, estaciones_base, df_demanda = cargar_dashboard()
except Exception as exc:
    st.error(f"Error al cargar los datos: {exc}")
    st.stop()

# Manejo de fechas basadas en metadatos
fecha_inicio_str = meta_datos.get("horario_inicio", "2026-04-06")
try:
    fecha_inicio_obj = datetime.datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
except ValueError:
    fecha_inicio_obj = datetime.datetime(2026, 4, 6)

n_slots = meta_datos.get("n_slots", 1)
# Creamos la lista de horas sumando 1 hora por cada slot
fechas_slots = [fecha_inicio_obj + datetime.timedelta(hours=i) for i in range(n_slots)]

with st.sidebar:
    st.header("Filtros Globales")
    lineas_disponibles = sorted(df_demanda["LINEA"].unique())
    lineas_seleccionadas = st.multiselect("Líneas de subte", lineas_disponibles, default=lineas_disponibles)
    
    agregacion = st.radio("Cálculo para el mapa", ["Por Fecha y Hora", "Demanda Promedio", "Demanda Total Acumulada"])
    
    if agregacion == "Por Fecha y Hora":
        # Usamos select_slider para poder navegar por las fechas de manera intuitiva
        fecha_elegida = st.select_slider(
            "Seleccionar el momento específico:",
            options=fechas_slots,
            format_func=lambda x: x.strftime("%d/%m/%Y %H:00")
        )
        slot_elegido = fechas_slots.index(fecha_elegida)

if not lineas_seleccionadas:
    st.warning("Seleccioná al menos una línea.")
    st.stop()

if agregacion == "Por Fecha y Hora":
    demanda = df_demanda[["LINEA", "ESTACION_BASE"]].copy()
    demanda["VALOR_MAPA"] = df_demanda["SERIE"].apply(
        lambda x: x[slot_elegido] if slot_elegido < len(x) and x[slot_elegido] is not None else 0
    )
    etiqueta_metrica = f"Demanda el {fecha_elegida.strftime('%d/%m/%Y a las %H:00')}"
elif agregacion == "Demanda Total Acumulada":
    demanda = df_demanda[["LINEA", "ESTACION_BASE", "VALOR_TOTAL"]].rename(columns={"VALOR_TOTAL": "VALOR_MAPA"})
    etiqueta_metrica = "Demanda Total Acumulada en el período"
else:
    demanda = df_demanda[["LINEA", "ESTACION_BASE", "VALOR_PROMEDIO"]].rename(columns={"VALOR_PROMEDIO": "VALOR_MAPA"})
    etiqueta_metrica = "Demanda Promedio por hora"

try:
    with st.spinner("Preparando mapa..."):
        geo_estaciones = cargar_geojson(URL_ESTACIONES)
        geo_lineas = cargar_geojson(URL_LINEAS)
        estaciones = vincular_estaciones(extraer_estaciones(geo_estaciones), df_demanda)
except Exception as exc:
    st.error("No se pudieron obtener las capas geográficas.")
    st.stop()

pestana_mapa, pestana_serie = st.tabs(["🗺️ Mapa de demanda", "📈 Serie de Tiempo por Estación"])

with pestana_mapa:
    st.subheader("Visualización Geográfica")
    mapa = construir_mapa(estaciones, geo_lineas, demanda, lineas_seleccionadas, etiqueta_metrica)
    st_folium(mapa, width=None, height=690, returned_objects=[])

with pestana_serie:
    st.subheader("Evolución temporal de la demanda")
    st.caption("Los registros representan la evolución secuencial por hora desde el 6 de Abril de 2026.")
    
    df_lineas_filtradas = df_demanda[df_demanda["LINEA"].isin(lineas_seleccionadas)]
    estacion_grafico = st.selectbox("Seleccionar Estación", df_lineas_filtradas["ESTACION_BASE"].unique())
    
    datos_estacion = df_demanda[df_demanda["ESTACION_BASE"] == estacion_grafico].iloc[0]
    serie_valores = datos_estacion["SERIE"]
    
    # SOLUCIÓN: Generamos la cantidad exacta de fechas según el largo real de 'serie_valores'
    fechas_serie = [fecha_inicio_obj + datetime.timedelta(hours=i) for i in range(len(serie_valores))]
    
    # Preparamos el dataframe usando las fechas reales en el índice
    df_serie = pd.DataFrame({
        "Fecha y Hora": fechas_serie,
        "Pasajeros Estimados": serie_valores
    }).set_index("Fecha y Hora")
    
    st.line_chart(df_serie, height=450, use_container_width=True)

st.divider()
st.caption("Cartografía proporcionada por Buenos Aires Data / Subterráneos de Buenos Aires (SBASE).")