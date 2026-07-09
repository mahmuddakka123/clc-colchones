import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

st.set_page_config(
    page_title="CLC Colchones - Gestión", 
    page_icon="🛏️", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    .block-container {
        padding: 2rem 2rem !important;
    }
    h1 { font-size: 2.3rem !important; font-weight: 700; color: #1F4E79; }
    h4 { font-size: 1.3rem !important; font-weight: 600; margin-top: 1rem; }
    
    @media (max-width: 768px) {
        .block-container {
            padding: 1rem 0.5rem !important;
        }
        h1 { font-size: 1.6rem !important; text-align: center !important; }
        h2, h3, h4 { font-size: 1.15rem !important; }
        div[data-testid="stTabs"] button {
            font-size: 12px !important; padding: 6px 10px !important;
        }
        div[data-testid="stMetricValue"] { font-size: 1.3rem !important; }
        button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-primary"] {
            padding: 10px 8px !important; font-size: 14px !important; min-height: 42px !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

if 'mensaje_toast' in st.session_state:
    st.toast(st.session_state.mensaje_toast, icon="✅")
    del st.session_state.mensaje_toast
if 'error_toast' in st.session_state:
    st.toast(st.session_state.error_toast, icon="🚨")
    del st.session_state.error_toast

@st.cache_resource
def obtener_motor_bd():
    try:
        return create_engine(st.secrets["DATABASE_URL"])
    except KeyError:
        st.error("Error: La credencial DATABASE_URL no está definida en los Secrets de la plataforma.")
        st.stop()

engine = obtener_motor_bd()

def conectar_bd():
    conn = psycopg2.connect(st.secrets["DATABASE_URL"])
    conn.autocommit = True
    return conn

with conectar_bd() as conexion:
    with conexion.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (cedula TEXT PRIMARY KEY, password TEXT, rol TEXT)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traslados (
                id SERIAL PRIMARY KEY,
                pestana TEXT,
                hora TEXT,
                codigo_lamina TEXT,
                descripcion TEXT,
                cantidad INTEGER,
                verificado BOOLEAN,
                creado_por TEXT,
                despacho INTEGER DEFAULT 0,
                pendientes INTEGER DEFAULT 0,
                parent_id INTEGER
            )
        """)
        cursor.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS despacho INTEGER DEFAULT 0;")
        cursor.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS pendientes INTEGER DEFAULT 0;")
        cursor.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS parent_id INTEGER;")
        
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss') ON CONFLICT (cedula) DO NOTHING")
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador') ON CONFLICT (cedula) DO NOTHING")

if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

if st.session_state.usuario is None:
    st.title("Iniciar Sesión — CLC Colchones")
    with st.form("login_system"):
        user_in = st.text_input("Usuario / Cédula").strip()
        pass_in = st.text_input("Contraseña", type="password").strip()
        if st.form_submit_button("Acceder al Panel", type="primary", use_container_width=True):
            if user_in and pass_in:
                with conectar_bd() as conexion:
                    with conexion.cursor() as cursor:
                        cursor.execute("SELECT rol, password FROM usuarios WHERE cedula=%s", (user_in,))
                        usuario_registrado = cursor.fetchone()
                        if usuario_registrado and usuario_registrado[1] == pass_in:
                            st.session_state.usuario = user_in
                            st.session_state.rol = usuario_registrado[0]
                            st.rerun()
                        else:
                            st.error("Los datos ingresados son incorrectos.")
            else:
                st.error("Todos los campos de acceso son obligatorios.")
    st.stop()

st.sidebar.markdown(f"**Usuario:** {st.session_state.usuario}")
st.sidebar.markdown(f"**Permisos:** {st.session_state.rol.upper()}")
if st.sidebar.button("Cerrar Sesión", use_container_width=True, type="secondary"):
    st.session_state.usuario = None
    st.session_state.rol = None
    st.rerun()

st.title("Control de Traslado de Láminas")
st.write("")

def obtener_registros(pestana):
    query = f"""
        SELECT id, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, 
        despacho, pendientes, parent_id 
        FROM traslados WHERE pestana='{pestana}'
        ORDER BY COALESCE(parent_id, id) ASC, parent_id IS NOT NULL ASC, id ASC
    """
    df = pd.read_sql_query(query, engine)
    if not df.empty:
        df['despacho'] = df['despacho'].fillna(0).astype(int)
        df['pendientes'] = df['pendientes'].fillna(0).astype(int)
    return df

def agregar_nuevo_registro(pestana, codigo, descripcion, cantidad, autor):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inicial_pendiente = cantidad if pestana != "Códigos SAP" else 0
    with conectar_bd() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, NULL)
            """, (pestana, timestamp, codigo, descripcion, cantidad, False, autor, inicial_pendiente))

def modificar_registro_existente(id_registro, codigo, descripcion, cantidad):
    with conectar_bd() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(despacho), 0) FROM traslados WHERE parent_id=%s", (id_registro,))
            acumulado_despachado = int(cursor.fetchone()[0])
            calculo_pendiente = max(0, cantidad - acumulado_despachado)
            cursor.execute("""
                UPDATE traslados 
                SET codigo_lamina=%s, descripcion=%s, cantidad=%s, pendientes=%s 
                WHERE id=%s
            """, (codigo, descripcion, cantidad, calculo_pendiente, id_registro))

def remover_registro(id_registro):
    with conectar_bd() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("DELETE FROM traslados WHERE id=%s OR parent_id=%s", (id_registro, id_registro))

def exportar_excel(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=nombre_hoja)
        if df.empty: 
            return output.getvalue()
        sheet = writer.sheets[nombre_hoja]
        fill_header = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        font_header = Font(color="FFFFFF", bold=True)
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        
        for cell in sheet[1]:
            cell.fill = fill_header
            cell.font = font_header
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
            
        for col in sheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            sheet.column_dimensions[col_letter].width = max_len + 3
            for cell in col:
                cell.border = thin_border
                if cell.row != 1: 
                    cell.alignment = Alignment(horizontal="left", vertical="center")
        sheet.freeze_panes = "A2"
    return output.getvalue()

lista_pestanas_base = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
pestanas_visibles = lista_pestanas_base.copy()
if st.session_state.rol in ["administrador", "boss"]:
    pestanas_visibles.append("Panel de Administrador")

tabs = st.tabs(pestanas_visibles)
df_sap_global = pd.read_sql_query("SELECT codigo_lamina, descripcion FROM traslados WHERE pestana='Códigos SAP'", engine)

for idx, nombre_tab in enumerate(lista_pestanas_base):
    with tabs[idx]:
        df_datos = obtener_registros(nombre_tab)
        df_pedidos_base = df_datos[df_datos['parent_id'].isna()] if not df_datos.empty else df_datos
        
        if nombre_tab == "Códigos SAP":
            st.metric("Total de Códigos Registrados", len(df_datos))
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total de Pedidos Base", len(df_pedidos_base))
            m2.metric("Unidades Solicitadas", int(df_pedidos_base['cantidad'].sum()) if not df_pedidos_base.empty else 0)
            m3.metric("Verificados", f"{int(df_pedidos_base['verificado'].sum()) if not df_pedidos_base.empty else 0} de {len(df_pedidos_base)}")
            
        st.write("---")
        
        if st.session_state.rol in ["administrador", "moderador", "boss"]:
            c_add, c_edit, c_del = st.columns(3)
            
            with c_add:
                with st.expander("Añadir Registro Manual"):
                    if nombre_tab != "Códigos SAP":
                        if not df_sap_global.empty:
                            opciones_select_sap = df_sap_global.apply(lambda r: f"{r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                            seleccion_sap = st.selectbox("Seleccionar Artículo SAP:", options=opciones_select_sap, key=f"sap_menu_{nombre_tab}")
                            cod_def = seleccion_sap.split(" - ")[0].strip()
                            desc_def = seleccion_sap.split(" - ")[1].strip()
                        else:
                            st.warning("El catálogo de códigos SAP se encuentra vacío.")
                            cod_def = st.text_input("Código de Lámina", key=f"input_cod_manual_{nombre_tab}").strip()
                            desc_def = st.text_input("Descripción", key=f"input_desc_manual_{nombre_tab}").strip()
                        
                        with st.form(key=f"form_alta_{nombre_tab}", clear_on_submit=True):
                            cant_alta = st.number_input("Cantidad Solicitada", min_value=1, value=1)
                            if st.form_submit_button("Registrar en Historial", use_container_width=True, type="primary"):
                                if cod_def:
                                    agregar_nuevo_registro(nombre_tab, cod_def, desc_def, cant_alta, st.session_state.usuario)
                                    st.session_state.mensaje_toast = "Registro indexado exitosamente."
                                    st.rerun()
                    else:
                        with st.form(key="form_alta_sap_maestro", clear_on_submit=True):
                            cod_sap_new = st.text_input("Código SKU / SAP").strip()
                            desc_sap_new = st.text_input("Descripción del Material").strip()
                            if st.form_submit_button("Registrar Código", use_container_width=True):
                                if cod_sap_new:
                                    agregar_nuevo_registro("Códigos SAP", cod_sap_new, desc_sap_new, 1, st.session_state.usuario)
                                    st.session_state.mensaje_toast = "Código SAP añadido al catálogo."
                                    st.rerun()
            
            with c_edit:
                with st.expander("Modificar Registro Existente"):
                    if not df_pedidos_base.empty:
                        opciones_edicion = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                        seleccion_mod = st.selectbox("Elegir registro a editar:", opciones_edicion, key=f"select_edit_{nombre_tab}")
                        id_edit = int(seleccion_mod.split(" | ")[0].replace("ID: ", ""))
                        fila_original = df_pedidos_base[df_pedidos_base['id'] == id_edit].iloc[0]
                        
                        with st.form(key=f"form_modificacion_{nombre_tab}"):
                            c_actualizado = st.text_input("Código", value=str(fila_original['codigo_lamina']))
                            d_actualizada = st.text_input("Descripción", value=str(fila_original['descripcion']))
                            q_actualizada = st.number_input("Cantidad", min_value=1, value=int(fila_original['cantidad'])) if nombre_tab != "Códigos SAP" else 1
                            if st.form_submit_button("Actualizar Base de Datos", use_container_width=True):
                                modificar_registro_existente(id_edit, c_actualizado, d_actualizada, q_actualizada)
                                st.session_state.mensaje_toast = "Información modificada correctamente."
                                st.rerun()
                    else:
                        st.info("No existen registros base editables en esta pestaña.")

            with c_del:
                with st.expander("Eliminación de Filas"):
                    if not df_pedidos_base.empty:
                        opciones_borrado = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                        seleccion_bajas = st.multiselect("Seleccionar elementos a remover:", opciones_borrado, key=f"select_del_{nombre_tab}")
                        if st.button("Confirmar Eliminación", key=f"btn_baja_{nombre_tab}", type="primary", use_container_width=True):
                            for item in seleccion_bajas:
                                id_del = int(item.split(" | ")[0].replace("ID: ", ""))
                                remover_registro(id_del)
                            st.session_state.mensaje_toast = "Removido del registro histórico."
                            st.rerun()
        
        st.write("#### Hoja de Trabajo Activa")
        
        if nombre_tab == "Códigos SAP":
            df_tabla = df_datos[['id', 'codigo_lamina', 'descripcion']].copy() if not df_datos.empty else df_datos
            columnas_config = {
                "id": None,
                "codigo_lamina": st.column_config.TextColumn("Código SAP", disabled=True),
                "descripcion": st.column_config.TextColumn("Descripción de Material", disabled=True)
            }
        else:
            df_tabla = df_datos.copy()
            if not df_tabla.empty:
                df_tabla['verificado'] = df_tabla['verificado'].astype(bool)
                df_tabla['hora'] = pd.to_datetime(df_tabla['hora'], errors='coerce').dt.strftime('%d/%m/%Y %H:%M')
                
                df_tabla['codigo_lamina'] = df_tabla['codigo_lamina'].astype(str)
                df_tabla['descripcion'] = df_tabla['descripcion'].astype(str)
                df_tabla['cantidad'] = df_tabla['cantidad'].astype(str)
                
                mascara_sublineas = df_tabla['parent_id'].notna()
                df_tabla.loc[mascara_sublineas, 'codigo_lamina'] = "="
                df_tabla.loc[mascara_sublineas, 'descripcion'] = "="
                df_tabla.loc[mascara_sublineas, 'cantidad'] = "="

            permiso_verificar = st.session_state.rol in ["administrador", "boss"]
            permiso_despachar = (st.session_state.rol == "moderador")
            
            columnas_config = {
                "id": None, 
                "parent_id": None,
                "hora": st.column_config.TextColumn("Fecha", disabled=True),
                "codigo_lamina": st.column_config.TextColumn("Código", disabled=True),
                "descripcion": st.column_config.TextColumn("Descripción", disabled=True),
                "cantidad": st.column_config.TextColumn("Cantidad Inicial", disabled=True),
                "creado_por": st.column_config.TextColumn("Registrado Por", disabled=True),
                "verificado": st.column_config.CheckboxColumn("Verificado", disabled=not permiso_verificar),
                "despacho": st.column_config.NumberColumn("Despacho Actual", disabled=not permiso_despachar, min_value=0),
                "pendientes": st.column_config.NumberColumn("Saldo Pendiente", disabled=True),
            }

        editor_key = f"grid_editor_{nombre_tab}"
        tabla_editada = st.data_editor(
            df_tabla,
            column_config=columnas_config,
            hide_index=True,
            use_container_width=True,
            height=360,
            key=editor_key
        )
        
        if nombre_tab != "Códigos SAP" and not df_datos.empty:
            if st.button("Guardar Cambios de la Hoja", key=f"save_grid_btn_{nombre_tab}"):
                cambios_filas = st.session_state[editor_key].get("edited_rows", {})
                if cambios_filas:
                    hubo_cambios = False
                    with conectar_bd() as conexion:
                        with conexion.cursor() as cursor:
                            for idx_str, cambios in cambios_filas.items():
                                fila_pos = int(idx_str)
                                fila_data = df_datos.iloc[fila_pos]
                                id_db = int(fila_data['id'])
                                es_sublinea = pd.notna(fila_data['parent_id'])
                                
                                if "verificado" in cambios and permiso_verificar:
                                    cursor.execute("UPDATE traslados SET verificado=%s WHERE id=%s", (bool(cambios["verificado"]), id_db))
                                    hubo_cambios = True
                                
                                if "despacho" in cambios and permiso_despachar and not es_sublinea:
                                    cant_despacho = int(cambios["despacho"])
                                    if cant_despacho > 0:
                                        saldo_anterior = int(fila_data['pendientes'])
                                        nuevo_saldo = max(0, saldo_anterior - cant_despacho)
                                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        
                                        cursor.execute("""
                                            INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id)
                                            VALUES (%s, %s, %s, %s, 0, False, %s, %s, %s, %s)
                                        """, (nombre_tab, timestamp, '=', '=', st.session_state.usuario, cant_despacho, nuevo_saldo, id_db))
                                        
                                        cursor.execute("UPDATE traslados SET pendientes=%s WHERE id=%s", (nuevo_saldo, id_db))
                                        hubo_cambios = True
                    if hubo_cambios:
                        st.session_state.mensaje_toast = "Hoja de trabajo actualizada e indexada."
                        st.rerun()
                else:
                    st.info("No se han detectado modificaciones sin guardar en la tabla.")

        st.write("---")
        b_import, b_export = st.columns(2)
        
        if st.session_state.rol in ["administrador", "boss"]:
            with b_import:
                st.subheader("Carga Masiva (Excel)")
                archivo_carga = st.file_uploader("Subir libro .xlsx", type=["xlsx"], key=f"uploader_{nombre_tab}")
                if archivo_carga is not None:
                    try:
                        df_excel = pd.read_excel(archivo_carga)
                        df_excel.columns = [str(c).lower().strip() for c in df_excel.columns]
                        for _, row_ex in df_excel.iterrows():
                            c_excel = str(row_ex.get('codigo_lamina', row_ex.get('código', row_ex.get('codigo', 'N/A')))).strip()
                            d_excel = str(row_ex.get('descripcion', row_ex.get('descripción', 'N/A'))).strip()
                            try: 
                                q_excel = int(float(row_ex.get('cantidad', 1)))
                            except: 
                                q_excel = 1
                            agregar_nuevo_registro(nombre_tab, c_excel, d_excel, q_excel, st.session_state.usuario)
                        st.session_state.mensaje_toast = "Registros cargados de forma masiva."
                        st.rerun()
                    except Exception:
                        st.error("Error al procesar el archivo. Verifique el formato e inténtelo de nuevo.")

        with b_export:
            st.subheader("Exportación de Datos")
            df_salida = df_tabla.drop(columns=['id', 'parent_id'], errors='ignore') if not df_tabla.empty else df_tabla
            datos_excel = exportar_excel(df_salida, nombre_tab)
            st.download_button(
                label="Descargar Reporte Excel", 
                data=datos_excel, 
                file_name=f"Reporte_CLC_{nombre_tab}_{datetime.date.today()}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                key=f"download_btn_{nombre_tab}", 
                type="primary", 
                use_container_width=True
            )

if st.session_state.rol in ["administrador", "boss"]:
    with tabs[4]: 
        st.header("Administración Global de Usuarios")
        df_usuarios = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios", engine)
        st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
        
        adm_c1, adm_c2 = st.columns(2)
        with adm_c1:
            with st.form("form_alta_usuarios", clear_on_submit=True):
                st.subheader("Crear o Modificar Credenciales")
                c_user = st.text_input("Cédula / Identificador").strip()
                p_user = st.text_input("Contraseña de Acceso").strip()
                r_user = st.selectbox("Rol Asignado", ["administrador", "moderador", "visualizador", "boss"])
                if st.form_submit_button("Guardar Configuración", use_container_width=True):
                    if c_user and p_user:
                        with conectar_bd() as conexion:
                            with conexion.cursor() as cursor:
                                cursor.execute("""
                                    INSERT INTO usuarios (cedula, password, rol) VALUES (%s, %s, %s) 
                                    ON CONFLICT (cedula) DO UPDATE SET password = EXCLUDED.password, rol = EXCLUDED.rol
                                """, (c_user, p_user, r_user))
                        st.session_state.mensaje_toast = f"Usuario {c_user} actualizado en el sistema."
                        st.rerun()
        
        with adm_c2:
            if not df_usuarios.empty:
                with st.form("form_baja_usuarios"):
                    st.subheader("Dar de Baja Cuenta")
                    user_del = st.selectbox("Seleccionar cuenta a remover:", df_usuarios['cedula'].tolist())
                    if st.form_submit_button("Eliminar Cuenta Definitivamente", type="primary", use_container_width=True):
                        with conectar_bd() as conexion:
                            with conexion.cursor() as cursor:
                                cursor.execute("DELETE FROM usuarios WHERE cedula=%s", (user_del,))
                        st.session_state.mensaje_toast = f"El usuario {user_del} ha sido removido."
                        st.rerun()
