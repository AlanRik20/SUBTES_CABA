from __future__ import annotations

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

DATA_JSON = Path("dashboard_data.json")

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

# Equivalencias entre los nombres del GeoJSON y los usados en los molinetes.
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
# Carga de los datos
# =============================================================================

@st.cache_data(show_spinner="Cargando los resultados del dashboard...")
def cargar_datos_dashboard():
    if not DATA_JSON.exists():
        raise FileNotFoundError(f"No se encontró {DATA_JSON.name} en el directorio.")

    with open(DATA_JSON, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    df_estaciones = pd.DataFrame(datos["estaciones"])
    serie_diaria = datos["serie_diaria"]

    registros = []
    for est_id, valores in serie_diaria.items():
        est_info = df_estaciones[df_estaciones["id"] == int(est_id)].iloc[0]
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

    return pd.DataFrame(registros), datos

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

def vincular_estaciones(estaciones: pd.DataFrame, df_demanda: pd.DataFrame) -> pd.DataFrame:
    nombres_por_linea = (
        df_demanda[["LINEA", "ESTACION_BASE"]]
        .drop_duplicates()
        .groupby("LINEA")["ESTACION_BASE"]
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
    titulo_indicador: str,
    modo: str,
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
    escala.caption = titulo_indicador
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
            detalle = f"{valor_num:,.0f} pasajeros" if modo == "total" else f"{valor_num:,.1f} pasajeros"
        else:
            radio = 5
            detalle = "Sin registros para los filtros seleccionados"

        popup_html = f"""
        <div style='font-family:Arial; min-width:210px;'>
            <b>{fila['ESTACION_GEO']}</b><br>
            Línea: {fila['LINEA']}<br>
            {titulo_indicador}: {detalle}
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
st.title("🚇 Resultados del Modelo - Subte BA")
st.markdown("Exploración geográfica de los datos extraídos del modelo para el período de prueba de 2026.")

try:
    df_demanda, meta_datos = cargar_datos_dashboard()
except Exception as exc:
    st.error(f"Error cargando los datos del dashboard: {exc}")
    st.stop()

with st.sidebar:
    st.header("Información del Dataset")
    st.info(
        f"**Inicio Test:** {meta_datos.get('test_inicio', 'N/A')}\n\n"
        f"**Días Test:** {meta_datos.get('n_dias_test', 'N/A')}\n\n"
        f"**Horario Inicio:** {meta_datos.get('horario_inicio', 'N/A')}\n\n"
        f"**Total Slots:** {meta_datos.get('n_slots', 'N/A')}"
    )

    st.header("Filtros")
    lineas_disponibles = sorted(df_demanda["LINEA"].dropna().unique().tolist())
    lineas_seleccionadas = st.multiselect(
        "Líneas de subte",
        options=lineas_disponibles,
        default=lineas_disponibles,
        format_func=lambda x: f"Línea {x}",
    )

    modos = ["Demanda Total (Período)", "Demanda Promedio", "Por Slot Horario"]
    modo_elegido = st.radio("Tipo de visualización", modos, index=0)

    if modo_elegido == "Por Slot Horario":
        n_slots = meta_datos.get("n_slots", 1)
        slot_elegido = st.slider("Seleccionar Slot", 0, n_slots - 1, 0)
        demanda = df_demanda[["LINEA", "ESTACION_BASE"]].copy()
        demanda["VALOR_MAPA"] = df_demanda["SERIE"].apply(
            lambda x: x[slot_elegido] if slot_elegido < len(x) and x[slot_elegido] is not None else 0
        )
        modo_mapa = "slot"
        titulo_indicador = f"Demanda Estimada (Slot {slot_elegido})"
    elif modo_elegido == "Demanda Total (Período)":
        demanda = df_demanda[["LINEA", "ESTACION_BASE", "VALOR_TOTAL"]].rename(columns={"VALOR_TOTAL": "VALOR_MAPA"})
        modo_mapa = "total"
        titulo_indicador = "Total de pasajeros estimados"
    else:
        demanda = df_demanda[["LINEA", "ESTACION_BASE", "VALOR_PROMEDIO"]].rename(columns={"VALOR_PROMEDIO": "VALOR_MAPA"})
        modo_mapa = "promedio"
        titulo_indicador = "Promedio de pasajeros por registro"

if not lineas_seleccionadas:
    st.warning("Seleccioná al menos una línea en el panel lateral.")
    st.stop()


try:
    with st.spinner("Preparando las estaciones y recorridos oficiales..."):
        geo_estaciones = cargar_geojson(URL_ESTACIONES)
        geo_lineas = cargar_geojson(URL_LINEAS)
        estaciones = vincular_estaciones(extraer_estaciones(geo_estaciones), df_demanda)
except Exception as exc:
    st.error("No se pudieron obtener las capas geográficas oficiales del Subte.")
    st.stop()

# Indicadores generales
estaciones_vinculadas = estaciones[
    estaciones["LINEA"].isin(lineas_seleccionadas)
    & estaciones["ESTACION_BASE"].notna()
]
mapa_datos = estaciones[
    estaciones["LINEA"].isin(lineas_seleccionadas)
].merge(demanda, on=["LINEA", "ESTACION_BASE"], how="left")

k1, k2, k3 = st.columns(3)
k1.metric("Estaciones geográficas vinculadas", f"{len(estaciones_vinculadas)}")

if modo_mapa == "total":
    valor_kpi = float(demanda["VALOR_MAPA"].sum()) if not demanda.empty else 0.0
    k2.metric("Total acumulado", f"{valor_kpi:,.0f}")
else:
    valor_kpi = float(demanda["VALOR_MAPA"].mean()) if not demanda.empty else 0.0
    k2.metric("Promedio en pantalla", f"{valor_kpi:,.1f}")


st.subheader("Mapa de estaciones y demanda")
st.caption(f"{titulo_indicador} para el período seleccionado.")

mapa = construir_mapa(
    estaciones=estaciones,
    lineas_geojson=geo_lineas,
    demanda=demanda,
    lineas_seleccionadas=lineas_seleccionadas,
    titulo_indicador=titulo_indicador,
    modo=modo_mapa,
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
            "se pudieron asociar automáticamente con los datos cargados."
        )
        st.dataframe(
            sin_coincidencia[["LINEA", "ESTACION_GEO"]].sort_values(["LINEA", "ESTACION_GEO"]),
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