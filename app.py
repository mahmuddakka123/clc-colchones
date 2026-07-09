import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

# 1. Configuración de la interfaz
st.set_page_config(
    page_title="CLC Colchones - Gestión", 
    page_icon="🛏️", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS limpio
st.markdown("""
    <style>
    .block-container { padding: 2rem 2rem !important; }
    h1 { font-size: 2.3rem !important; font-weight: 700; color: #1F4E79; }
    
    @media (max-width: 768px) {
        .block-container { padding: 1rem 0.5rem !important; }
        h1 { font-size: 1.6rem !important; text-align: center !important; }
    }
    </style>
""", unsafe_allow_html=True)

# 2. Alertas
if 'mensaje_toast' in st.session_state:
    st.toast(st.session_state.mensaje_toast, icon="✅")
    del st.session_state.mensaje_toast
if 'error_toast' in st.session_state:
    st.toast(st.session_state.error_toast, icon="🚨")
    del st.session_state.error_toast

# 3. Base de Datos
@st.cache_resource
def obtener_motor_bd():
    try:
        return create_engine(st.secrets["DATABASE_URL"])
    except KeyError:
        st.error("Error: DATABASE_URL no definida.")
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
                id SERIAL PRIMARY KEY, pestana TEXT, hora TEXT, codigo_lamina TEXT,
                descripcion TEXT, cantidad INTEGER, verificado BOOLEAN, creado_por TEXT,
                despacho INTEGER DEFAULT 0, pendientes INTEGER DEFAULT 0, parent_id INTEGER
            )
        """)
        cursor.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS despacho INTEGER DEFAULT 0;")
        cursor.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS pendientes INTEGER DEFAULT 0;")
        cursor.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS parent_id INTEGER;")
        
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss') ON CONFLICT (cedula) DO NOTHING")
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador') ON CONFLICT (cedula) DO NOTHING")
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('mod', 'mod123', 'moderador') ON CONFLICT (cedula) DO NOTHING")

# 4. Control de Sesión
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

if st.session_state.usuario is None:
    st.title("Iniciar Sesión — CLC Colchones")
    user_in = st.text_input("Usuario / Cédula").strip()
    pass_in = st.text_input("Contraseña", type="password").strip()
    if st.button("Acceder al Panel", type="primary", use_container_width=True):
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
                        st.error("Datos incorrectos.")
        else:
            st.error("Campos obligatorios.")
    st.stop()

# Menú lateral - Perfil de usuario
st.sidebar.markdown(f"**👤 Usuario:** {st.session_state.usuario}")
st.sidebar.markdown(f"**🛡️ Permisos:** {st.session_state.rol.upper()}")
if st.sidebar.button("Cerrar Sesión", use_container_width=True, type="secondary"):
    st.session_state.usuario = None
    st.session_state.rol = None
    st.rerun()

st.title("📦 Control de Traslado de Láminas")
st.write("---")

# 5. Funciones Core
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
                UPDATE traslados SET codigo_lamina=%s, descripcion=%s, cantidad=%s, pendientes=%s WHERE id=%s
            """, (codigo, descripcion, cantidad, calculo_pendiente, id_registro))

def remover_registro(id_registro):
    with conectar_bd() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("DELETE FROM traslados WHERE id=%s OR parent_id=%s", (id_registro, id_registro))

def exportar_excel(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=nombre_hoja)
        if df.empty: return output.getvalue()
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
            sheet.column_dimensions[col[0].column_letter].width = max_len + 3
            for cell in col:
                cell.border = thin_border
                if cell.row != 1: cell.alignment = Alignment(horizontal="left", vertical="center")
        sheet.freeze_panes = "A2"
    return output.getvalue()

# 6. MENÚ DE NAVEGACIÓN
lista_pestanas_base = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
pestanas_visibles = lista_pestanas_base.copy()
if st.session_state.rol in ["administrador", "boss"]:
    pestanas_visibles.append("Panel de Administrador")

st.sidebar.write("---")
st.sidebar.subheader("📌 Navegación de Áreas")
nombre_tab = st.sidebar.radio("Seleccione el espacio de trabajo:", pestanas_visibles)

# Consulta global de SAP
df_sap_global = pd.read_sql_query("SELECT codigo_lamina, descripcion FROM traslados WHERE pestana='Códigos SAP'", engine)

st.subheader(f"📂 Área de Trabajo: {nombre_tab}")

# =========================================================
# PANEL DE ADMINISTRADOR
# =========================================================
if nombre_tab == "Panel de Administrador":
    st.write("⚙️ **Administración de Usuarios del Sistema**")
    df_usuarios = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios", engine)
    st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
    
    a_c1, a_c2 = st.columns(2)
    with a_c1:
        st.write("##### Crear / Editar Usuario")
        with st.form(key="form_adm_user", clear_on_submit=True):
            c_user = st.text_input("Usuario / Cédula").strip()
            p_user = st.text_input("Contraseña").strip()
            r_user = st.selectbox("Rol", ["administrador", "moderador", "boss"])
            if st.form_submit_button("Guardar Usuario", use_container_width=True):
                if c_user and p_user:
                    with conectar_bd() as conexion:
                        with conexion.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO usuarios (cedula, password, rol) VALUES (%s, %s, %s) 
                                ON CONFLICT (cedula) DO UPDATE SET password = EXCLUDED.password, rol = EXCLUDED.rol
                            """, (c_user, p_user, r_user))
                    st.session_state.mensaje_toast = "Usuario guardado."
                    st.rerun()
    
    with a_c2:
        if not df_usuarios.empty:
            st.write("##### Eliminar Usuario")
            with st.form(key="form_adm_del"):
                user_del = st.selectbox("Seleccionar usuario a eliminar:", df_usuarios['cedula'].tolist())
                if st.form_submit_button("Eliminar Usuario", type="primary", use_container_width=True):
                    with conectar_bd() as conexion:
                        with conexion.cursor() as cursor:
                            cursor.execute("DELETE FROM usuarios WHERE cedula=%s", (user_del,))
                    st.session_state.mensaje_toast = "Usuario eliminado."
                    st.rerun()

# =========================================================
# LÓGICA DE GESTIÓN DE LÁMINAS
# =========================================================
else:
    df_datos = obtener_registros(nombre_tab)
    df_pedidos_base = df_datos[df_datos['parent_id'].isna()] if not df_datos.empty else df_datos
    
    if nombre_tab == "Códigos SAP":
        st.metric("Total de Códigos Registrados", len(df_datos))
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total de Pedidos", len(df_pedidos_base))
        m2.metric("Unidades Solicitadas", int(df_pedidos_base['cantidad'].sum()) if not df_pedidos_base.empty else 0)
        m3.metric("Verificados", f"{int(df_pedidos_base['verificado'].sum()) if not df_pedidos_base.empty else 0} de {len(df_pedidos_base)}")
        
    st.write("---")
    
    # CONTROLES EXCLUSIVOS ADMINISTRADORES / BOSS
    if st.session_state.rol in ["administrador", "boss"]:
        c_add, c_edit, c_del = st.columns(3)
        
        with c_add:
            with st.expander("➕ Añadir Petición (Base)"):
                if nombre_tab != "Códigos SAP":
                    with st.form(key=f"form_add_{nombre_tab}", clear_on_submit=True):
                        if not df_sap_global.empty:
                            opciones_select_sap = df_sap_global.apply(lambda r: f"{r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                            seleccion_sap = st.selectbox("Seleccionar Artículo SAP:", options=opciones_select_sap)
                            cod_def = seleccion_sap.split(" - ")[0].strip()
                            desc_def = seleccion_sap.split(" - ")[1].strip()
                        else:
                            st.warning("Catálogo vacío.")
                            cod_def = st.text_input("Código").strip()
                            desc_def = st.text_input("Descripción").strip()
                        
                        cant_alta = st.number_input("Cantidad Solicitada", min_value=1, value=1)
                        
                        if st.form_submit_button("Registrar Petición", use_container_width=True, type="primary"):
                            if cod_def:
                                agregar_nuevo_registro(nombre_tab, cod_def, desc_def, cant_alta, st.session_state.usuario)
                                st.session_state.mensaje_toast = "Petición registrada."
                                st.rerun()
                else:
                    with st.form(key=f"form_add_sap_{nombre_tab}", clear_on_submit=True):
                        cod_sap_new = st.text_input("Código SAP").strip()
                        desc_sap_new = st.text_input("Descripción").strip()
                        if st.form_submit_button("Añadir a Catálogo"):
                            if cod_sap_new:
                                agregar_nuevo_registro("Códigos SAP", cod_sap_new, desc_sap_new, 1, st.session_state.usuario)
                                st.session_state.mensaje_toast = "Código SAP añadido."
                                st.rerun()
        
        with c_edit:
            with st.expander("📝 Modificar Petición"):
                if not df_pedidos_base.empty:
                    opciones_edicion = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                    seleccion_mod = st.selectbox("Elegir petición a editar:", opciones_edicion, key=f"select_edit_{nombre_tab}")
                    id_edit = int(seleccion_mod.split(" | ")[0].replace("ID: ", ""))
                    fila_original = df_pedidos_base[df_pedidos_base['id'] == id_edit].iloc[0]
                    
                    with st.form(key=f"form_edit_{nombre_tab}"):
                        c_actualizado = st.text_input("Código", value=str(fila_original['codigo_lamina']))
                        d_actualizada = st.text_input("Descripción", value=str(fila_original['descripcion']))
                        q_actualizada = st.number_input("Cantidad", min_value=1, value=int(fila_original['cantidad'])) if nombre_tab != "Códigos SAP" else 1
                        
                        if st.form_submit_button("Guardar Cambios", use_container_width=True):
                            modificar_registro_existente(id_edit, c_actualizado, d_actualizada, q_actualizada)
                            st.session_state.mensaje_toast = "Modificado correctamente."
                            st.rerun()
                else:
                    st.info("No existen registros.")

        with c_del:
            with st.expander("🗑️ Eliminar Petición"):
                if not df_pedidos_base.empty:
                    with st.form(key=f"form_del_{nombre_tab}"):
                        opciones_borrado = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                        seleccion_bajas = st.multiselect("Seleccionar peticiones a remover:", opciones_borrado)
                        
                        if st.form_submit_button("Ejecutar Eliminación", type="primary"):
                            for item in seleccion_bajas:
                                remover_registro(int(item.split(" | ")[0].replace("ID: ", "")))
                            st.session_state.mensaje_toast = "Registros eliminados."
                            st.rerun()

    # FLUJO EXCLUSIVO PARA MODERADORES (DESPACHO)
    if st.session_state.rol == "moderador" and nombre_tab != "Códigos SAP":
        st.write("#### 🚚 Panel de Despachos")
        df_pendientes = df_pedidos_base[df_pedidos_base['pendientes'] > 0]
        
        if not df_pendientes.empty:
            opciones_despacho = df_pendientes.apply(lambda r: f"Petición ID: {r['id']} | Cód: {r['codigo_lamina']} | Cantidad Pendiente: {r['pendientes']}", axis=1).tolist()
            seleccion_pet = st.selectbox("Seleccione la petición que desea despachar:", opciones_despacho, key=f"sel_despacho_{nombre_tab}")
            
            id_pet_seleccionada = int(seleccion_pet.split(" | ")[0].replace("Petición ID: ", ""))
            max_disponible = int(seleccion_pet.split("Cantidad Pendiente: ")[1])
            
            with st.form(key=f"form_despachar_{nombre_tab}"):
                cant_a_despachar = st.number_input("Indique la cantidad a despachar ahora:", min_value=1, max_value=max_disponible, value=1)
                
                if st.form_submit_button("✅ Confirmar Despacho", use_container_width=True, type="primary"):
                    nuevo_saldo_pendiente = max_disponible - cant_a_despachar
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    with conectar_bd() as conexion:
                        with conexion.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id)
                                VALUES (%s, %s, '=', '=', 0, False, %s, %s, %s, %s)
                            """, (nombre_tab, timestamp, st.session_state.usuario, cant_a_despachar, nuevo_saldo_pendiente, id_pet_seleccionada))
                            
                            cursor.execute("UPDATE traslados SET pendientes=%s WHERE id=%s", (nuevo_saldo_pendiente, id_pet_seleccionada))
                    
                    st.session_state.mensaje_toast = "Despacho ejecutado y registrado."
                    st.rerun()
        else:
            st.success("🎉 No hay peticiones pendientes de despacho en esta pestaña.")

    st.write("#### 📊 Hoja de Trabajo Activa")
    
    # === CORRECCIÓN DEL ERROR AQUÍ ===
    # Variables globales de permisos reubicadas para que siempre existan
    es_readonly_general = (st.session_state.rol == "moderador")
    permiso_verificar = st.session_state.rol in ["administrador", "boss"]
    # =================================
    
    # RENDERIZADO DE LA TABLA
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
            
            mascara_sub = df_tabla['parent_id'].notna()
            df_tabla.loc[mascara_sub, 'codigo_lamina'] = "="
            df_tabla.loc[mascara_sub, 'descripcion'] = "="
            df_tabla.loc[mascara_sub, 'cantidad'] = "="

        columnas_config = {
            "id": None, 
            "parent_id": None,
            "hora": st.column_config.TextColumn("Fecha", disabled=True),
            "codigo_lamina": st.column_config.TextColumn("Código", disabled=True),
            "descripcion": st.column_config.TextColumn("Descripción", disabled=True),
            "cantidad": st.column_config.TextColumn("Cant. Solicitada", disabled=True),
            "creado_por": st.column_config.TextColumn("Autor", disabled=True),
            "verificado": st.column_config.CheckboxColumn("Verificado", disabled=not permiso_verificar),
            "despacho": st.column_config.NumberColumn("Despacho", disabled=True),
            "pendientes": st.column_config.NumberColumn("Pendiente", disabled=True),
        }

    editor_key = f"grid_{nombre_tab}"
    tabla_editada = st.data_editor(
        df_tabla,
        column_config=columnas_config,
        hide_index=True,
        use_container_width=True,
        height=400,
        disabled=es_readonly_general, 
        key=editor_key
    )
    
    if nombre_tab != "Códigos SAP" and not df_datos.empty and st.session_state.rol in ["administrador", "boss"]:
        if st.button("Guardar Verificaciones de Tabla", key=f"save_btn_{nombre_tab}"):
            cambios = st.session_state[editor_key].get("edited_rows", {})
            if cambios:
                with conectar_bd() as conexion:
                    with conexion.cursor() as cursor:
                        for idx_str, data_cambio in cambios.items():
                            if "verificado" in data_cambio:
                                id_db = int(df_datos.iloc[int(idx_str)]['id'])
                                cursor.execute("UPDATE traslados SET verificado=%s WHERE id=%s", (bool(data_cambio["verificado"]), id_db))
                st.session_state.mensaje_toast = "Verificaciones guardadas."
                st.rerun()

    st.write("---")
    
    # IMPORTACIÓN Y EXPORTACIÓN
    b_import, b_export = st.columns(2)
    if st.session_state.rol in ["administrador", "boss"]:
        with b_import:
            with st.form(key=f"form_up_{nombre_tab}"):
                archivo_carga = st.file_uploader("Carga Masiva (.xlsx)", type=["xlsx"])
                if st.form_submit_button("Subir Archivo"):
                    if archivo_carga:
                        try:
                            df_excel = pd.read_excel(archivo_carga)
                            df_excel.columns = [str(c).lower().strip() for c in df_excel.columns]
                            for _, row_ex in df_excel.iterrows():
                                c_excel = str(row_ex.get('codigo_lamina', row_ex.get('código', row_ex.get('codigo', 'N/A')))).strip()
                                d_excel = str(row_ex.get('descripcion', row_ex.get('descripción', 'N/A'))).strip()
                                try: q_excel = int(float(row_ex.get('cantidad', 1)))
                                except: q_excel = 1
                                agregar_nuevo_registro(nombre_tab, c_excel, d_excel, q_excel, st.session_state.usuario)
                            st.session_state.mensaje_toast = "Base cargada."
                            st.rerun()
                        except:
                            st.error("Error leyendo Excel.")

    with b_export:
        df_salida = df_tabla.drop(columns=['id', 'parent_id'], errors='ignore') if not df_tabla.empty else df_tabla
        st.download_button(
            label="📥 Descargar Reporte Excel", 
            data=exportar_excel(df_salida, nombre_tab), 
            file_name=f"Reporte_{nombre_tab}.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            key=f"dw_{nombre_tab}", type="primary", use_container_width=True
        )
