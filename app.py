import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
st.set_page_config(page_title="CLC Colchones", page_icon="🛏️", layout="wide")

for key in ['mensaje_toast', 'error_toast']:
    if key in st.session_state:
        st.toast(st.session_state[key], icon="✅" if "mensaje" in key else "🚨")
        del st.session_state[key]

# --- 2. BASE DE DATOS ---
try:
    DB_URL = st.secrets["DATABASE_URL"]
except Exception:
    st.error("🚨 Falta configurar DATABASE_URL en los Secrets.")
    st.stop()

engine = create_engine(DB_URL)
conn = psycopg2.connect(DB_URL)
conn.autocommit = True
c = conn.cursor()

# Creación de tablas e inserciones iniciales
c.execute("CREATE TABLE IF NOT EXISTS usuarios (cedula TEXT PRIMARY KEY, password TEXT, rol TEXT)")
c.execute('''CREATE TABLE IF NOT EXISTS traslados (
                id SERIAL PRIMARY KEY, pestana TEXT, hora TEXT, codigo_lamina TEXT, 
                descripcion TEXT, cantidad INTEGER, verificado BOOLEAN, creado_por TEXT)''')

# Migraciones
c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='usuarios'")
if 'password' not in [col[0] for col in c.fetchall()]:
    c.execute("ALTER TABLE usuarios ADD COLUMN password TEXT DEFAULT '123456'; UPDATE usuarios SET password = cedula") 

c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='traslados'")
if 'creado_por' not in [col[0] for col in c.fetchall()]:
    c.execute("ALTER TABLE traslados ADD COLUMN creado_por TEXT DEFAULT 'admin_legacy'")

c.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss'), ('admin', 'admin', 'administrador') ON CONFLICT DO NOTHING")

# --- 3. AUTENTICACIÓN ---
if 'usuario' not in st.session_state:
    st.session_state.update({"usuario": None, "rol": None})

def login():
    st.title("🛏️ CLC Colchones - Iniciar Sesión")
    st.info("💡 Consejo: Usa la tecla 'Tab' para pasar a la contraseña y 'Enter' para ingresar.")
    with st.form("login_form"):
        cedula, password = st.text_input("👤 Usuario (Cédula)"), st.text_input("🔑 Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
            if not cedula.strip() or not password.strip():
                st.error("Llena ambos campos.")
                return
            c.execute("SELECT rol, password FROM usuarios WHERE cedula=%s", (cedula.strip(),))
            res = c.fetchone()
            if res and res[1] == password.strip():
                st.session_state.update({"usuario": cedula.strip(), "rol": res[0]})
                st.rerun()
            else:
                st.error("Credenciales incorrectas o usuario inexistente.")

if not st.session_state.usuario:
    login()
    st.stop()

# --- 4. SIDEBAR ---
st.sidebar.title(f"👤 Usuario:\n{st.session_state.usuario}")
st.sidebar.subheader(f"🛡️ Rol: {st.session_state.rol.capitalize()}")
if st.session_state.rol == "boss": st.sidebar.success("👑 Nivel Boss")
if st.sidebar.button("🔒 Cerrar Sesión"):
    st.session_state.update({"usuario": None, "rol": None})
    st.rerun()

st.title("📦 Panel de Control CLC - Traslado de Láminas")
st.write("---")

# --- 5. FUNCIONES AUXILIARES ---
def query_db(q, params=()): c.execute(q, params)
def cargar_datos(pestana): return pd.read_sql_query(f"SELECT * FROM traslados WHERE pestana='{pestana}'", engine)
def generar_excel_perfecto(df, hoja):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name=hoja)
        if df.empty: return out.getvalue()
        ws = w.sheets[hoja]
        fill, font = PatternFill("solid", fgColor="1F4E79"), Font(color="FFFFFF", bold=True)
        borde = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        for cell in ws[1]: cell.fill, cell.font, cell.alignment, cell.border = fill, font, Alignment(horizontal="center", vertical="center"), borde
        for col in ws.columns:
            max_len = max([len(str(c.value)) for c in col if c.value] + [0])
            ws.column_dimensions[col[0].column_letter].width = max_len + 3
            for cell in col:
                cell.border = borde
                if cell.row > 1: cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.freeze_panes = "A2"
    return out.getvalue()

# --- 6. PESTAÑAS DE TRABAJO ---
nombres = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
tabs = st.tabs(nombres + ["Panel de Administrador"] if st.session_state.rol in ["administrador", "boss"] else nombres)
permiso_edicion = st.session_state.rol in ["administrador", "boss"]

for i, tab_name in enumerate(nombres):
    with tabs[i]:
        es_sap = (tab_name == "Códigos SAP")
        df = cargar_datos(tab_name)
        df_editable = df[df['creado_por'] == st.session_state.usuario] if st.session_state.rol == "moderador" else df
        tot_regs = len(df)
        
        # Métricas
        if es_sap:
            st.metric("📄 Total de Códigos Registrados", tot_regs)
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("📄 Registros", tot_regs)
            c2.metric("📦 Unidades", df['cantidad'].sum() if tot_regs else 0)
            c3.metric("✅ Verificadas", f"{df['verificado'].sum() if tot_regs else 0} de {tot_regs}")
        st.write("---")
        
        # Paneles de Edición (Ocultos para visualizadores)
        if st.session_state.rol != "visualizador":
            c1, c2, c3 = st.columns(3)
            with c1.expander(f"➕ Agregar {'Código' if es_sap else 'traslado'}"):
                with st.form(f"add_{tab_name}", clear_on_submit=True):
                    n_cod, n_desc = st.text_input("Código"), st.text_input("Descripción")
                    n_cant = 1 if es_sap else st.number_input("Cantidad", min_value=1, value=1)
                    if st.form_submit_button("Agregar", use_container_width=True):
                        if n_cod:
                            hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            query_db("INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                                     (tab_name, hora, n_cod, n_desc, n_cant, False, st.session_state.usuario))
                            st.session_state.mensaje_toast = "Añadido con éxito."
                            st.rerun()
                        else: st.error("El código es obligatorio.")

            with c2.expander(f"📝 Modificar {'Código' if es_sap else 'artículo'}"):
                if not df_editable.empty:
                    opts = df_editable.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                    sel = st.selectbox("Selecciona registro:", opts, key=f"sel_{tab_name}")
                    id_mod = int(sel.split(" | ")[0].replace("ID: ", ""))
                    fila = df_editable[df_editable['id'] == id_mod].iloc[0]
                    
                    with st.form(f"edit_{tab_name}_{id_mod}"):
                        m_cod, m_desc = st.text_input("Código", str(fila['codigo_lamina'])), st.text_input("Descripción", str(fila['descripcion']))
                        m_cant = int(fila['cantidad']) if es_sap else st.number_input("Cantidad", min_value=1, value=max(1, int(fila['cantidad'])))
                        if st.form_submit_button("💾 Guardar", use_container_width=True):
                            query_db("UPDATE traslados SET codigo_lamina=%s, descripcion=%s, cantidad=%s WHERE id=%s", (m_cod, m_desc, m_cant, id_mod))
                            st.session_state.mensaje_toast = "Actualizado."
                            st.rerun()
                else: st.info("No hay datos modificables.")

            with c3.expander(f"🗑️ Eliminar {'Código' if es_sap else 'artículos'}"):
                if not df_editable.empty:
                    opts_del = df_editable.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                    sel_del = st.multiselect("Borrar registros:", opts_del, key=f"del_{tab_name}")
                    if st.button("⚠️ Eliminar Seleccionados", type="primary", use_container_width=True, key=f"btn_del_{tab_name}"):
                        for item in sel_del: query_db("DELETE FROM traslados WHERE id=%s", (int(item.split(" | ")[0].replace("ID: ", "")),))
                        if sel_del: st.session_state.mensaje_toast = "Eliminados."; st.rerun()
                else: st.info("No hay datos para eliminar.")

        # Tabla Principal
        st.write("#### 📊 Hoja de Trabajo")
        if not df.empty:
            df['verificado'] = df['verificado'].astype(bool)
            df['hora'] = pd.to_datetime(df['hora']).dt.strftime('%d/%m/%Y %H:%M')

        cols_config = {
            "id": None, 
            "hora": None if es_sap else st.column_config.TextColumn("📅 Fecha", disabled=True),
            "codigo_lamina": st.column_config.TextColumn("🏷️ Código", disabled=True),
            "descripcion": st.column_config.TextColumn("📝 Descripción", disabled=True),
            "cantidad": None if es_sap else st.column_config.NumberColumn("🔢 Cantidad", disabled=True),
            "creado_por": None if es_sap else st.column_config.TextColumn("👤 Autor", disabled=True),
            "verificado": None if es_sap else st.column_config.CheckboxColumn("✅ ¿Verificado?", disabled=not permiso_edicion)
        }

        edited_df = st.data_editor(df, column_config=cols_config, hide_index=True, use_container_width=True, height=400, key=f"tbl_{tab_name}")
        
        if permiso_edicion and not df.empty and not es_sap:
            for idx, r in edited_df.iterrows():
                if r['verificado'] != df.loc[idx, 'verificado']:
                    query_db("UPDATE traslados SET verificado=%s WHERE id=%s", (r['verificado'], r['id']))
                    st.rerun()

        st.write("---")
        
        # Importar y Exportar
        c_down1, c_down2 = st.columns(2)
        if permiso_edicion:
            with c_down1:
                st.subheader("📥 Importar Excel")
                up_file = st.file_uploader("Sube .xlsx", type=["xlsx"], key=f"up_{tab_name}")
                if up_file:
                    try:
                        df_imp = pd.read_excel(up_file)
                        hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        for _, row in df_imp.iterrows():
                            # Lector de Excel posicional simplificado (Ignora nombres de columna, usa posición 1, 2, 3)
                            cod = str(row.iloc[0]).strip() if len(row)>0 and pd.notna(row.iloc[0]) else "N/A"
                            desc = str(row.iloc[1]).strip() if len(row)>1 and pd.notna(row.iloc[1]) else "N/A"
                            cant = max(1, int(float(row.iloc[2]))) if len(row)>2 and pd.notna(row.iloc[2]) else 1
                            query_db("INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                     (tab_name, hora, cod, desc, cant, False, st.session_state.usuario))
                        st.session_state.mensaje_toast = "Excel importado."
                        st.rerun()
                    except Exception: st.error("🚨 Archivo inválido.")

        with c_down2:
            st.subheader("📤 Exportar")
            df_export = df[['codigo_lamina', 'descripcion']] if es_sap else df.drop(columns=['id'], errors='ignore')
            st.download_button("📊 Descargar Excel", generar_excel_perfecto(df_export, tab_name), f"CLC_{tab_name}_{datetime.date.today()}.xlsx", type="primary", key=f"dl_{tab_name}")

# --- 7. PANEL DE CONTROL (ADMIN) ---
if permiso_edicion:
    with tabs[4]: 
        st.header("⚙️ Usuarios")
        df_users = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios" + ("" if st.session_state.rol == "boss" else " WHERE rol != 'boss'"), engine)
        st.dataframe(df_users, use_container_width=True, hide_index=True)
        st.write("---")
        
        ca1, ca2 = st.columns(2)
        with ca1.form("form_users", clear_on_submit=True):
            st.subheader("➕ Crear / Editar")
            n_ced, n_pass = st.text_input("Cédula"), st.text_input("Contraseña")
            roles = ["administrador", "moderador", "visualizador"] + (["boss"] if st.session_state.rol == "boss" else [])
            n_rol = st.selectbox("Rol", roles)
            if st.form_submit_button("Guardar"):
                if n_ced and n_pass:
                    c.execute("SELECT rol FROM usuarios WHERE cedula=%s", (n_ced.strip(),))
                    rol_exist = c.fetchone()
                    if rol_exist and rol_exist[0] == "boss" and st.session_state.rol != "boss":
                        st.session_state.error_toast = "❌ Sin permisos."
                    else:
                        query_db("INSERT INTO usuarios (cedula, password, rol) VALUES (%s, %s, %s) ON CONFLICT (cedula) DO UPDATE SET password=EXCLUDED.password, rol=EXCLUDED.rol", (n_ced.strip(), n_pass.strip(), n_rol))
                        st.session_state.mensaje_toast = "Usuario configurado."
                    st.rerun()
                else: st.error("Llena todo.")
        
        with ca2.form("form_del_user"):
            st.subheader("🗑️ Eliminar")
            usr_del = st.selectbox("Usuario a eliminar", df_users['cedula'].tolist())
            if st.form_submit_button("Eliminar", type="primary"):
                query_db("DELETE FROM usuarios WHERE cedula=%s", (usr_del,))
                if usr_del == st.session_state.usuario: st.session_state.update({"usuario": None, "rol": None})
                st.session_state.mensaje_toast = "Usuario eliminado."
                st.rerun()

conn.close()

