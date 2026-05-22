import base64
import math
from datetime import datetime
from io import BytesIO
from pathlib import Path

import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak


# =========================================================
# CONFIGURACIÓN
# =========================================================
APP_DIR = Path(__file__).parent
LAYOUT_PATH = APP_DIR / "Layout_Almuerzo_v1.jpg"
POSICIONES_PATH = APP_DIR / "Posiciones_Mesas.csv"

SPREADSHEET_ID = "1-__QYpgasM2bHjK0amIgZIrDXlLLOGSf40yLUky3DUU"

HOJA_ASISTENTES = "Asistentes"
HOJA_MESAS = "Mesas"
HOJA_VERSIONES = "Versiones"
HOJA_ASIGNACIONES = "Asignaciones"

CAPACIDAD = 10

st.set_page_config(page_title="Asignación de mesas", layout="wide")


# =========================================================
# TEMA VISUAL AUTOMÁTICO
# =========================================================
def obtener_tipo_tema():
    try:
        theme_type = st.context.theme.type
        if theme_type in ["light", "dark"]:
            return theme_type
    except Exception:
        pass

    try:
        theme_base = st.get_option("theme.base")
        if theme_base in ["light", "dark"]:
            return theme_base
    except Exception:
        pass

    return "light"


TIPO_TEMA = obtener_tipo_tema()
TEXTO_TEMA = "white" if TIPO_TEMA == "dark" else "black"
FONDO_TEMA = "rgba(0,0,0,0)"


# =========================================================
# CONEXIÓN GOOGLE SHEETS
# =========================================================
def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if "gcp_service_account" not in st.secrets:
        st.error(
            "No están configuradas las credenciales de Google Sheets en Streamlit Secrets. "
            "Debes agregar el bloque [gcp_service_account]."
        )
        st.stop()

    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes,
    )

    client = gspread.authorize(credentials)
    return client.open_by_key(SPREADSHEET_ID)


@st.cache_resource
def obtener_spreadsheet():
    return conectar_google_sheets()


def worksheet_existe(nombre_hoja):
    spreadsheet = obtener_spreadsheet()
    try:
        spreadsheet.worksheet(nombre_hoja)
        return True
    except gspread.WorksheetNotFound:
        return False


def obtener_o_crear_worksheet(nombre_hoja, columnas):
    spreadsheet = obtener_spreadsheet()

    try:
        ws = spreadsheet.worksheet(nombre_hoja)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=nombre_hoja, rows=1000, cols=max(len(columnas), 10))
        ws.update(values=[columnas], range_name="A1")

    return ws


def leer_worksheet(nombre_hoja, columnas=None):
    if columnas is None:
        spreadsheet = obtener_spreadsheet()
        ws = spreadsheet.worksheet(nombre_hoja)
    else:
        ws = obtener_o_crear_worksheet(nombre_hoja, columnas)

    rows = ws.get_all_records()
    return pd.DataFrame(rows), ws


def limpiar_valores_para_sheet(df):
    df = df.copy()
    df = df.astype(object)
    df = df.where(pd.notna(df), "")
    return df


def escribir_worksheet(nombre_hoja, df, columnas):
    ws = obtener_o_crear_worksheet(nombre_hoja, columnas)

    df_limpio = limpiar_valores_para_sheet(df)

    for col in columnas:
        if col not in df_limpio.columns:
            df_limpio[col] = ""

    df_limpio = df_limpio[columnas]

    valores = [df_limpio.columns.tolist()] + df_limpio.astype(str).values.tolist()

    ws.clear()
    ws.update(values=valores, range_name="A1")


# =========================================================
# DATOS
# =========================================================
COLUMNAS_ASISTENTES = ["ID", "Mesa", "Asiento", "Nombre", "Cargo", "Empresa", "Confirmación"]
COLUMNAS_MESAS = ["MesaID", "NombreMesa", "Sector", "Tipo"]
COLUMNAS_VERSIONES = ["Version", "Nombre", "Activa", "Creada"]
COLUMNAS_ASIGNACIONES = ["Version", "ID", "Mesa", "Asiento"]


def normalizar_asistentes(asistentes):
    if asistentes.empty:
        asistentes = pd.DataFrame(columns=COLUMNAS_ASISTENTES)

    for col in COLUMNAS_ASISTENTES:
        if col not in asistentes.columns:
            asistentes[col] = ""

    asistentes["Mesa"] = pd.to_numeric(asistentes["Mesa"], errors="coerce").astype("Int64")
    asistentes["Asiento"] = pd.to_numeric(asistentes["Asiento"], errors="coerce").astype("Int64")
    asistentes["ID"] = asistentes["ID"].astype(str)

    return asistentes


def normalizar_mesas(mesas):
    if mesas.empty:
        mesas = pd.DataFrame(columns=COLUMNAS_MESAS)

    if "MesaID" not in mesas.columns:
        mesas["MesaID"] = range(1, len(mesas) + 1)

    if "NombreMesa" not in mesas.columns:
        mesas["NombreMesa"] = mesas["MesaID"].apply(lambda x: f"Mesa {x}")

    return mesas


def normalizar_versiones(versiones):
    if versiones.empty:
        versiones = pd.DataFrame([{
            "Version": 1,
            "Nombre": "Versión 1",
            "Activa": "Sí",
            "Creada": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }])

    for col in COLUMNAS_VERSIONES:
        if col not in versiones.columns:
            versiones[col] = ""

    versiones["Version"] = pd.to_numeric(versiones["Version"], errors="coerce").fillna(1).astype(int)

    if not (versiones["Activa"].astype(str).str.lower().isin(["sí", "si", "true", "1"])).any():
        versiones.loc[versiones.index[0], "Activa"] = "Sí"

    return versiones


def normalizar_asignaciones(asignaciones, asistentes):
    if asignaciones.empty:
        base = asistentes[["ID", "Mesa", "Asiento"]].copy()
        base = base[base["Mesa"].notna()]
        base.insert(0, "Version", 1)
        asignaciones = base

    for col in COLUMNAS_ASIGNACIONES:
        if col not in asignaciones.columns:
            asignaciones[col] = ""

    asignaciones["Version"] = pd.to_numeric(asignaciones["Version"], errors="coerce").fillna(1).astype(int)
    asignaciones["ID"] = asignaciones["ID"].astype(str)
    asignaciones["Mesa"] = pd.to_numeric(asignaciones["Mesa"], errors="coerce").astype("Int64")
    asignaciones["Asiento"] = pd.to_numeric(asignaciones["Asiento"], errors="coerce").astype("Int64")

    return asignaciones


def asegurar_hojas_versiones(asistentes):
    versiones, _ = leer_worksheet(HOJA_VERSIONES, COLUMNAS_VERSIONES)
    versiones = normalizar_versiones(versiones)
    escribir_worksheet(HOJA_VERSIONES, versiones, COLUMNAS_VERSIONES)

    asignaciones, _ = leer_worksheet(HOJA_ASIGNACIONES, COLUMNAS_ASIGNACIONES)
    asignaciones = normalizar_asignaciones(asignaciones, asistentes)
    escribir_worksheet(HOJA_ASIGNACIONES, asignaciones, COLUMNAS_ASIGNACIONES)

    return versiones, asignaciones


@st.cache_data(ttl=5)
def cargar_datos():
    asistentes, _ = leer_worksheet(HOJA_ASISTENTES, COLUMNAS_ASISTENTES)
    mesas, _ = leer_worksheet(HOJA_MESAS, COLUMNAS_MESAS)

    asistentes = normalizar_asistentes(asistentes)
    mesas = normalizar_mesas(mesas)

    versiones, asignaciones = asegurar_hojas_versiones(asistentes)

    return asistentes, mesas, versiones, asignaciones


def recargar_datos():
    st.cache_data.clear()
    st.session_state.asistentes, st.session_state.mesas, st.session_state.versiones, st.session_state.asignaciones = cargar_datos()


def guardar_versiones(versiones):
    escribir_worksheet(HOJA_VERSIONES, versiones, COLUMNAS_VERSIONES)
    st.cache_data.clear()


def guardar_asignaciones(asignaciones):
    escribir_worksheet(HOJA_ASIGNACIONES, asignaciones, COLUMNAS_ASIGNACIONES)
    st.cache_data.clear()


if "asistentes" not in st.session_state:
    st.session_state.asistentes, st.session_state.mesas, st.session_state.versiones, st.session_state.asignaciones = cargar_datos()

asistentes = st.session_state.asistentes
mesas = st.session_state.mesas
versiones = st.session_state.versiones
asignaciones = st.session_state.asignaciones


def version_activa():
    global versiones

    mask = versiones["Activa"].astype(str).str.lower().isin(["sí", "si", "true", "1"])
    if mask.any():
        return int(versiones.loc[mask, "Version"].iloc[0])

    return int(versiones["Version"].min())


def nombre_version(v):
    fila = versiones[versiones["Version"] == v]
    if len(fila):
        return str(fila.iloc[0]["Nombre"])
    return f"Versión {v}"


def set_version_activa(v):
    global versiones

    versiones = versiones.copy()
    versiones["Activa"] = "No"
    versiones.loc[versiones["Version"] == int(v), "Activa"] = "Sí"
    st.session_state.versiones = versiones
    guardar_versiones(versiones)


def crear_version_desde_cero():
    global versiones, asignaciones

    nueva = int(versiones["Version"].max()) + 1 if len(versiones) else 1

    nueva_fila = pd.DataFrame([{
        "Version": nueva,
        "Nombre": f"Versión {nueva}",
        "Activa": "Sí",
        "Creada": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }])

    versiones = versiones.copy()
    versiones["Activa"] = "No"
    versiones = pd.concat([versiones, nueva_fila], ignore_index=True)

    asignaciones = asignaciones.copy()
    asignaciones = asignaciones[asignaciones["Version"] != nueva]

    st.session_state.versiones = versiones
    st.session_state.asignaciones = asignaciones

    guardar_versiones(versiones)
    guardar_asignaciones(asignaciones)

    return nueva


def crear_version_copia(version_origen):
    global versiones, asignaciones

    nueva = int(versiones["Version"].max()) + 1 if len(versiones) else 1

    nueva_fila = pd.DataFrame([{
        "Version": nueva,
        "Nombre": f"Versión {nueva}",
        "Activa": "Sí",
        "Creada": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }])

    copia = asignaciones[asignaciones["Version"] == int(version_origen)].copy()
    copia["Version"] = nueva

    versiones = versiones.copy()
    versiones["Activa"] = "No"
    versiones = pd.concat([versiones, nueva_fila], ignore_index=True)

    asignaciones = pd.concat([asignaciones, copia], ignore_index=True)

    st.session_state.versiones = versiones
    st.session_state.asignaciones = asignaciones

    guardar_versiones(versiones)
    guardar_asignaciones(asignaciones)

    return nueva


def df_asistentes_version(v):
    base = asistentes.drop(columns=["Mesa", "Asiento"], errors="ignore").copy()
    asign = asignaciones[asignaciones["Version"] == int(v)][["ID", "Mesa", "Asiento"]].copy()

    base["ID"] = base["ID"].astype(str)
    asign["ID"] = asign["ID"].astype(str)

    df = base.merge(asign, on="ID", how="left")
    df["Mesa"] = pd.to_numeric(df["Mesa"], errors="coerce").astype("Int64")
    df["Asiento"] = pd.to_numeric(df["Asiento"], errors="coerce").astype("Int64")

    return df


VERSION_ACTIVA = version_activa()
asistentes_v = df_asistentes_version(VERSION_ACTIVA)


# =========================================================
# UTILIDADES DE IMAGEN / POSICIONES
# =========================================================
def imagen_a_base64(path):
    img = Image.open(path).convert("RGB")
    buffer = BytesIO()
    img.save(buffer, format="JPEG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{encoded}", img.size


def numero_mesa(valor):
    texto = str(valor).strip().replace("Mesa", "").replace("mesa", "").strip()
    return int(float(texto))


@st.cache_data
def cargar_posiciones():
    try:
        posiciones = pd.read_csv(POSICIONES_PATH, sep=";")
        if len(posiciones.columns) == 1:
            posiciones = pd.read_csv(POSICIONES_PATH)
    except Exception:
        posiciones = pd.read_csv(POSICIONES_PATH)

    posiciones.columns = [str(c).strip() for c in posiciones.columns]

    if not {"Mesa", "X", "Y"}.issubset(set(posiciones.columns)):
        raise ValueError("El CSV de posiciones debe tener las columnas: Mesa, X, Y")

    posiciones["MesaN"] = posiciones["Mesa"].apply(numero_mesa)
    posiciones["X"] = pd.to_numeric(posiciones["X"], errors="coerce")
    posiciones["Y"] = pd.to_numeric(posiciones["Y"], errors="coerce")
    posiciones = posiciones.dropna(subset=["MesaN", "X", "Y"])

    return posiciones[["MesaN", "X", "Y"]]


def obtener_posiciones_sobre_imagen():
    posiciones = cargar_posiciones()

    if not LAYOUT_PATH.exists():
        raise FileNotFoundError("No se encontró Layout_Almuerzo_v1.jpg")

    _, (img_w, img_h) = imagen_a_base64(LAYOUT_PATH)

    min_x = float(posiciones["X"].min())
    max_x = float(posiciones["X"].max())
    min_y = float(posiciones["Y"].min())
    max_y = float(posiciones["Y"].max())

    target_min_x = img_w * 0.19
    target_max_x = img_w * 0.77
    target_min_y = img_h * 0.37
    target_max_y = img_h * 0.68

    necesita_ajuste_x = max_x > img_w or min_x > img_w * 0.50
    necesita_ajuste_y = max_y > img_h or min_y > img_h * 0.20

    posiciones = posiciones.copy()

    if necesita_ajuste_x:
        posiciones["X_plot"] = target_min_x + (
            (posiciones["X"] - min_x) / max((max_x - min_x), 1)
        ) * (target_max_x - target_min_x)
    else:
        posiciones["X_plot"] = posiciones["X"]

    if necesita_ajuste_y:
        posiciones["Y_plot"] = target_min_y + (
            (posiciones["Y"] - min_y) / max((max_y - min_y), 1)
        ) * (target_max_y - target_min_y)
    else:
        posiciones["Y_plot"] = posiciones["Y"]

    return {
        int(row["MesaN"]): (float(row["X_plot"]), float(row["Y_plot"]))
        for _, row in posiciones.iterrows()
    }


# =========================================================
# FUNCIONES VISUALES
# =========================================================
def conteo_mesa(n):
    return int((asistentes_v["Mesa"] == n).sum())


def estado_mesa(n):
    c = conteo_mesa(n)

    if c == CAPACIDAD:
        return "Completa"

    if c == 0:
        return "Vacía"

    return "Incompleta"


def color_mesa(n):
    estado = estado_mesa(n)

    if estado == "Completa":
        return "#2ca02c"

    if estado == "Incompleta":
        return "#f2c94c"

    return "#bdbdbd"


def figura_plano():
    imagen_b64, (img_w, img_h) = imagen_a_base64(LAYOUT_PATH)
    posiciones = obtener_posiciones_sobre_imagen()

    xs, ys, labels, colors, custom = [], [], [], [], []

    for n in range(1, 31):
        if n not in posiciones:
            continue

        x, y = posiciones[n]
        c = conteo_mesa(n)

        xs.append(x)
        ys.append(y)
        labels.append(str(n))
        colors.append(color_mesa(n))
        custom.append([n, c, estado_mesa(n)])

    fig = go.Figure()

    fig.add_layout_image(
        dict(
            source=imagen_b64,
            xref="x",
            yref="y",
            x=0,
            y=0,
            sizex=img_w,
            sizey=img_h,
            sizing="stretch",
            opacity=1,
            layer="below",
        )
    )

    fig.add_trace(go.Scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        marker=dict(
            size=36,
            color=colors,
            opacity=0.88,
            line=dict(width=2, color="#222222")
        ),
        text=labels,
        textposition="middle center",
        textfont=dict(size=14, color="black", family="Arial Black"),
        customdata=custom,
        hovertemplate=(
            "Mesa %{customdata[0]}<br>"
            "Asignados: %{customdata[1]}/10<br>"
            "%{customdata[2]}"
            "<extra></extra>"
        ),
    ))

    fig.update_xaxes(visible=False, range=(0, img_w), constrain="domain")
    fig.update_yaxes(visible=False, range=(img_h, 0), scaleanchor="x", scaleratio=1)

    fig.update_layout(
        height=720,
        margin=dict(l=0, r=0, t=0, b=0),
        clickmode="event+select",
        showlegend=False,
        paper_bgcolor=FONDO_TEMA,
        plot_bgcolor=FONDO_TEMA,
        font=dict(color=TEXTO_TEMA),
    )

    return fig


def figura_mesa(n):
    invitados = asistentes_v[asistentes_v["Mesa"] == n].copy()
    invitados = invitados.sort_values("Asiento", na_position="last")

    datos_por_asiento = {}

    for asiento in range(1, CAPACIDAD + 1):
        fila = invitados[invitados["Asiento"] == asiento]

        if len(fila) > 0:
            r = fila.iloc[0]

            datos_por_asiento[asiento] = {
                "nombre": str(r.get("Nombre", "")),
                "cargo": str(r.get("Cargo", "")),
                "empresa": str(r.get("Empresa", "")),
                "id": str(r.get("ID", "")),
            }

        else:
            datos_por_asiento[asiento] = {
                "nombre": "Disponible",
                "cargo": "",
                "empresa": "",
                "id": "",
            }

    fig = go.Figure()

    fig.add_shape(
        type="circle",
        x0=-0.45,
        y0=-0.45,
        x1=0.45,
        y1=0.45,
        fillcolor="#5b9bd5",
        line=dict(color="#2f5597", width=2)
    )

    fig.add_annotation(
        x=0,
        y=0,
        text=f"MESA {n}",
        showarrow=False,
        font=dict(color="white", size=18)
    )

    xs, ys, textos, custom = [], [], [], []

    for asiento in range(1, CAPACIDAD + 1):
        ang = math.pi / 2 - 2 * math.pi * (asiento - 1) / CAPACIDAD

        x = 1.35 * math.cos(ang)
        y = 1.35 * math.sin(ang)

        d = datos_por_asiento[asiento]

        xs.append(x)
        ys.append(y)
        textos.append(f"{asiento}. {d['nombre']}")
        custom.append([asiento, d["id"], d["nombre"], d["cargo"], d["empresa"]])

    fig.add_trace(go.Scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        marker=dict(size=12, color="rgba(0,0,0,0)"),
        text=textos,
        textposition="middle center",
        textfont=dict(size=12, color=TEXTO_TEMA),
        customdata=custom,
        hovertemplate=(
            "Asiento %{customdata[0]}<br>"
            "ID: %{customdata[1]}<br>"
            "Nombre: %{customdata[2]}<br>"
            "Cargo: %{customdata[3]}<br>"
            "Empresa: %{customdata[4]}"
            "<extra></extra>"
        ),
    ))

    fig.update_xaxes(visible=False, range=(-2.2, 2.2))
    fig.update_yaxes(visible=False, range=(-1.9, 1.9), scaleanchor="x", scaleratio=1)

    fig.update_layout(
        height=430,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        paper_bgcolor=FONDO_TEMA,
        plot_bgcolor=FONDO_TEMA,
        font=dict(color=TEXTO_TEMA),
    )

    return fig


# =========================================================
# PDF
# =========================================================
def texto_seguro(valor):
    if pd.isna(valor):
        return ""
    return str(valor)


def datos_mesa_para_pdf(n):
    df = asistentes_v[asistentes_v["Mesa"] == n].copy()
    df = df.sort_values("Asiento", na_position="last")

    filas = []
    for asiento in range(1, CAPACIDAD + 1):
        fila = df[df["Asiento"] == asiento]

        if len(fila):
            r = fila.iloc[0]
            filas.append([
                asiento,
                texto_seguro(r.get("Nombre", "")),
                texto_seguro(r.get("Cargo", "")),
                texto_seguro(r.get("Empresa", "")),
            ])
        else:
            filas.append([asiento, "Disponible", "", ""])

    return filas


def crear_pdf_asignacion():
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.0 * cm,
    )

    styles = getSampleStyleSheet()
    elementos = []

    titulo = f"Asignación de mesas - {nombre_version(VERSION_ACTIVA)}"
    elementos.append(Paragraph(titulo, styles["Title"]))
    elementos.append(Paragraph(datetime.now().strftime("Generado el %d-%m-%Y %H:%M"), styles["Normal"]))
    elementos.append(Spacer(1, 0.3 * cm))

    mesas_por_pagina = 0

    for n in range(1, 31):
        if mesas_por_pagina == 2:
            elementos.append(PageBreak())
            mesas_por_pagina = 0

        elementos.append(Paragraph(f"Mesa {n}", styles["Heading2"]))

        data = [["Asiento", "Nombre", "Cargo", "Empresa"]] + datos_mesa_para_pdf(n)

        table = Table(
            data,
            colWidths=[1.6 * cm, 6.2 * cm, 4.8 * cm, 5.2 * cm],
            repeatRows=1,
        )

        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))

        elementos.append(table)
        elementos.append(Spacer(1, 0.4 * cm))

        mesas_por_pagina += 1

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


# =========================================================
# INTERFAZ
# =========================================================
st.title("Asignación de mesas - Almuerzo protocolar")

col_a, col_b = st.columns([2, 1])

with col_a:
    opciones_version = {
        f"{int(row['Version'])} - {row['Nombre']}": int(row["Version"])
        for _, row in versiones.sort_values("Version").iterrows()
    }

    etiqueta_actual = None
    for etiqueta, valor in opciones_version.items():
        if valor == VERSION_ACTIVA:
            etiqueta_actual = etiqueta
            break

    seleccion_version = st.selectbox(
        "Versión de asignación activa",
        list(opciones_version.keys()),
        index=list(opciones_version.keys()).index(etiqueta_actual) if etiqueta_actual else 0,
    )

    version_elegida = opciones_version[seleccion_version]

    if version_elegida != VERSION_ACTIVA:
        set_version_activa(version_elegida)
        recargar_datos()
        st.rerun()

with col_b:
    if st.button("Recargar datos desde Google Sheets"):
        recargar_datos()
        st.rerun()

st.caption(f"Estás trabajando en: **{nombre_version(VERSION_ACTIVA)}**")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Plano general",
    "Detalle de mesa",
    "Asistentes sin mesa",
    "Editar base completa",
    "Versiones",
    "PDF"
])


with tab1:
    st.subheader("Plano general de mesas")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Asistentes totales", len(asistentes_v))
    c2.metric("Asignados", int(asistentes_v["Mesa"].notna().sum()))
    c3.metric("Sin mesa", int(asistentes_v["Mesa"].isna().sum()))
    c4.metric("Mesas completas", sum(estado_mesa(n) == "Completa" for n in range(1, 31)))

    st.caption("Toca/clickea una mesa sobre el plano o selecciona una mesa manualmente.")

    evento = st.plotly_chart(
        figura_plano(),
        use_container_width=True,
        on_select="rerun",
        selection_mode="points"
    )

    mesa_click = None

    try:
        if evento and evento.selection and evento.selection.points:
            mesa_click = int(evento.selection.points[0]["customdata"][0])
    except Exception:
        mesa_click = None

    mesa_manual = st.selectbox("Seleccionar mesa", list(range(1, 31)), index=0)

    if mesa_click:
        st.session_state.mesa_seleccionada = mesa_click
        st.success(f"Mesa seleccionada desde el plano: Mesa {mesa_click}")

    elif "mesa_seleccionada" not in st.session_state:
        st.session_state.mesa_seleccionada = mesa_manual

    if st.button("Abrir mesa seleccionada"):
        st.session_state.mesa_seleccionada = mesa_manual
        st.rerun()


with tab2:
    n = st.session_state.get("mesa_seleccionada", 1)

    st.subheader(f"Mesa {n}")

    st.plotly_chart(figura_mesa(n), use_container_width=True)

    st.caption("Pasa el mouse sobre cada nombre para ver ID, cargo y empresa.")

    if st.button("Mostrar / ocultar detalle de invitados de esta mesa"):
        st.session_state[f"mostrar_detalle_mesa_{n}"] = not st.session_state.get(
            f"mostrar_detalle_mesa_{n}",
            False
        )

    if st.session_state.get(f"mostrar_detalle_mesa_{n}", False):
        detalle = asistentes_v[asistentes_v["Mesa"] == n].copy()

        if len(detalle) == 0:
            st.info("Esta mesa todavía no tiene invitados asignados.")

        else:
            detalle = detalle.sort_values("Asiento")

            st.dataframe(
                detalle[["Asiento", "ID", "Nombre", "Cargo", "Empresa", "Confirmación"]],
                use_container_width=True,
                hide_index=True
            )

    st.markdown("### Asignar invitados a esta mesa")

    st.caption(
        "Cada asiento puede tener un invitado. "
        "Los invitados que ya están en otra mesa no aparecen disponibles, "
        "salvo los que ya pertenecen a esta mesa."
    )

    actuales = asistentes_v[asistentes_v["Mesa"] == n].copy()

    disponibles = asistentes_v[
        asistentes_v["Mesa"].isna() | (asistentes_v["Mesa"] == n)
    ].copy()

    disponibles["Etiqueta"] = disponibles["ID"].astype(str) + " - " + disponibles["Nombre"].astype(str)

    opciones = {"Disponible / Sin asignar": None}

    disponibles["ID_orden"] = pd.to_numeric(disponibles["ID"], errors="coerce")
    disponibles = disponibles.sort_values(["ID_orden", "ID"], na_position="last")

    for _, row in disponibles.iterrows():
        opciones[row["Etiqueta"]] = row["ID"]

    asignaciones_nuevas = {}

    for asiento in range(1, CAPACIDAD + 1):
        fila = actuales[actuales["Asiento"] == asiento]

        actual_id = str(fila.iloc[0]["ID"]) if len(fila) else None

        index_default = 0
        etiquetas = list(opciones.keys())

        for i, et in enumerate(etiquetas):
            if opciones[et] is not None and str(opciones[et]) == actual_id:
                index_default = i
                break

        elegido = st.selectbox(
            f"Asiento {asiento}",
            etiquetas,
            index=index_default,
            key=f"mesa_{n}_version_{VERSION_ACTIVA}_asiento_{asiento}"
        )

        asignaciones_nuevas[asiento] = opciones[elegido]

    if st.button("Guardar asignación de esta mesa", type="primary"):
        ids_elegidos = [str(v) for v in asignaciones_nuevas.values() if v is not None]

        if len(ids_elegidos) != len(set(ids_elegidos)):
            st.error("Hay un invitado repetido en más de un asiento. Corrige antes de guardar.")

        elif len(ids_elegidos) > CAPACIDAD:
            st.error("Esta mesa supera los 10 invitados.")

        else:
            df_asig = asignaciones.copy()

            mask_version_mesa = (df_asig["Version"] == VERSION_ACTIVA) & (df_asig["Mesa"] == n)
            df_asig = df_asig[~mask_version_mesa].copy()

            nuevas_filas = []

            for asiento, invitado_id in asignaciones_nuevas.items():
                if invitado_id is not None:
                    nuevas_filas.append({
                        "Version": VERSION_ACTIVA,
                        "ID": str(invitado_id),
                        "Mesa": n,
                        "Asiento": asiento,
                    })

            # Si algún invitado seleccionado estaba asignado a otra mesa en la misma versión,
            # se elimina su asignación anterior antes de guardar la nueva.
            ids_nuevos = [str(f["ID"]) for f in nuevas_filas]
            df_asig = df_asig[
                ~(
                    (df_asig["Version"] == VERSION_ACTIVA)
                    & (df_asig["ID"].astype(str).isin(ids_nuevos))
                )
            ].copy()

            if nuevas_filas:
                df_asig = pd.concat([df_asig, pd.DataFrame(nuevas_filas)], ignore_index=True)

            guardar_asignaciones(df_asig)
            recargar_datos()

            st.success("Asignación guardada en Google Sheets.")
            st.rerun()


with tab3:
    st.subheader("Asistentes sin mesa")

    sin_mesa = asistentes_v[asistentes_v["Mesa"].isna()].copy()

    st.write(f"Total sin mesa: **{len(sin_mesa)}**")

    st.dataframe(
        sin_mesa[["ID", "Nombre", "Cargo", "Empresa", "Confirmación"]],
        use_container_width=True,
        hide_index=True
    )


with tab4:
    st.subheader("Editar base completa")

    st.warning("Esta edición cambia solo la asignación de mesas de la versión activa.")

    editado = st.data_editor(
        asistentes_v,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Mesa": st.column_config.NumberColumn(
                "Mesa",
                min_value=1,
                max_value=30,
                step=1
            ),
            "Asiento": st.column_config.NumberColumn(
                "Asiento",
                min_value=1,
                max_value=10,
                step=1
            ),
        }
    )

    if st.button("Validar y guardar cambios manuales"):
        errores = []

        temp = editado.copy()

        temp["Mesa"] = pd.to_numeric(temp["Mesa"], errors="coerce").astype("Int64")
        temp["Asiento"] = pd.to_numeric(temp["Asiento"], errors="coerce").astype("Int64")

        for mesa in range(1, 31):
            sub = temp[temp["Mesa"] == mesa]

            if len(sub) > CAPACIDAD:
                errores.append(f"Mesa {mesa}: tiene {len(sub)} asistentes, supera el máximo de 10.")

            duplicados = sub["Asiento"].dropna().duplicated().sum()

            if duplicados > 0:
                errores.append(f"Mesa {mesa}: hay asientos repetidos.")

        if errores:
            st.error("No se guardó porque hay errores:")

            for e in errores:
                st.write("- " + e)

        else:
            df_asig = asignaciones.copy()
            df_asig = df_asig[df_asig["Version"] != VERSION_ACTIVA].copy()

            nuevas = temp[temp["Mesa"].notna()][["ID", "Mesa", "Asiento"]].copy()
            nuevas.insert(0, "Version", VERSION_ACTIVA)

            df_asig = pd.concat([df_asig, nuevas[COLUMNAS_ASIGNACIONES]], ignore_index=True)

            guardar_asignaciones(df_asig)
            recargar_datos()

            st.success("Cambios guardados en Google Sheets.")
            st.rerun()


with tab5:
    st.subheader("Versiones de asignación")

    st.dataframe(
        versiones.sort_values("Version"),
        use_container_width=True,
        hide_index=True
    )

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### Crear versión desde cero")
        st.caption("Crea una versión nueva sin invitados asignados.")
        if st.button("Crear nueva versión vacía"):
            nueva = crear_version_desde_cero()
            recargar_datos()
            st.success(f"Se creó la Versión {nueva}.")
            st.rerun()

    with c2:
        st.markdown("### Crear copia de la versión activa")
        st.caption("Duplica la asignación actual para probar otra distribución.")
        if st.button("Crear copia de esta versión"):
            nueva = crear_version_copia(VERSION_ACTIVA)
            recargar_datos()
            st.success(f"Se creó la Versión {nueva} como copia.")
            st.rerun()


with tab6:
    st.subheader("Exportar PDF")

    st.write(
        "Genera un PDF tamaño carta con la asignación de la versión activa. "
        "El documento incluye dos mesas por página."
    )

    pdf_bytes = crear_pdf_asignacion()

    st.download_button(
        label="Descargar PDF de asignación",
        data=pdf_bytes,
        file_name=f"asignacion_mesas_{nombre_version(VERSION_ACTIVA).replace(' ', '_')}.pdf",
        mime="application/pdf",
        type="primary",
    )


st.divider()

st.caption(
    "Base de datos: Google Sheets. "
    "Las versiones se guardan en las hojas Versiones y Asignaciones. "
    "El PDF se genera en tamaño carta con dos mesas por página."
)
