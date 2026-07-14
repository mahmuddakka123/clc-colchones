import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io

# 1. Configuración de página y CSS Anti-Colapso
st.set_page_config(page_title="CLC Colchones", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    /* Evita que las pestañas se muestren una debajo de la otra */
    div[data-testid="stTabs"] [data-testid="stTabContent"] { display: none; }
    div[data-testid="stTabs"] [data-testid="stTabContent"][aria-hidden="false"] { display: block; }
    .block-container { padding: 2rem 2rem !important; }
    </style>
""", unsafe_allow_html=True)

# 2. Funciones de Utilidad (Hora de Venezuela)
def obtener_hora_venezuela():
    zona_horaria_vzla = datetime.timezone(datetime.timedelta(hours=-4))
    return datetime.datetime.now(zona_horaria_vzla).strftime("%Y-%m-%d %H:%M:%S")

# 3. Alertas y Base de Datos
if 'mensaje_toast' in st.session_state:
    st.toast(st.session_state.mensaje_toast, icon="✅")
    del st.session_state.mensaje_toast
if 'error_toast' in st.session_state:
    st.toast(st.session_state.error_toast, icon="🚨")
    del st.session_state.error_toast

@st.cache_resource
def obtener_motor_bd():
    return create_engine(st.secrets["DATABASE_URL"])

engine = obtener_motor_bd()

def conectar_bd():
    conn = psycopg2.connect(st.secrets["DATABASE_URL"])
    conn.autocommit = True
    return conn

# Creación de tablas
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
        # Usuarios por defecto
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss') ON CONFLICT (cedula) DO NOTHING")
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador') ON CONFLICT (cedula) DO NOTHING")
        cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('mod', 'mod123', 'moderador') ON CONFLICT (cedula) DO NOTHING")

# 4. Control de Sesión (Login con Enter)
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

if st.session_state.usuario is None:
    st.title("Iniciar Sesión — CLC Colchones")
    with st.form("login_form"):
        user_in = st.text_input("Usuario / Cédula").strip()
        pass_in = st.text_input("Contraseña", type="password").strip()
        submit_login = st.form_submit_button("Acceder al Panel", type="primary", use_container_width=True)
        
        if submit_login:
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

st.sidebar.markdown(f"**👤 Usuario:** {st.session_state.usuario}")
st.sidebar.markdown(f"**🛡️ Permisos:** {st.session_state.rol.upper()}")
if st.sidebar.button("Cerrar Sesión", use_container_width=True, type="secondary"):
    st.session_state.usuario = None
    st.session_state.rol = None
    st.rerun()

st.title("📦 Control de Traslado de Láminas")
st.write("---")

# 5. Funciones DB Core
def obtener_registros(pestana):
    query = f"SELECT * FROM traslados WHERE pestana='{pestana}' ORDER BY COALESCE(parent_id, id) ASC, parent_id IS NOT NULL ASC, id ASC"
    df = pd.read_sql_query(query, engine)
    if not df.empty:
        df['despacho'] = df['despacho'].fillna(0).astype(int)
        df['pendientes'] = df['pendientes'].fillna(0).astype(int)
    return df

def agregar_nuevo_registro(pestana, codigo, descripcion, cantidad, autor):
    timestamp = obtener_hora_venezuela()
    inicial_pendiente = cantidad if pestana != "Códigos SAP" else 0
    with conectar_bd() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("""
                INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s)
            """, (pestana, timestamp, codigo, descripcion, cantidad, False, autor, inicial_pendiente))

def modificar_despacho_db(id_despacho, nueva_cantidad):
    with conectar_bd() as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT despacho, parent_id FROM traslados WHERE id=%s", (id_despacho,))
            info = cursor.fetchone()
            if not info: return False, "Error: Despacho no existe."
            cant_vieja, parent_id = info
            
            cursor.execute("SELECT pendientes FROM traslados WHERE id=%s", (parent_id,))
            padre_info = cursor.fetchone()
            if not padre_info: return False, "Error: Pedido base eliminado."
            pendientes_actuales = padre_info[0]
            
            diferencia = nueva_cantidad - cant_vieja
            
            if nueva_cantidad == 0:
                cursor.execute("UPDATE traslados SET pendientes = pendientes + %s WHERE id=%s", (cant_vieja, parent_id))
                cursor.execute("DELETE FROM traslados WHERE id=%s", (id_despacho,))
                return True, "Despacho eliminado. Láminas devueltas a Pendientes."
            else:
                if diferencia > 0 and pendientes_actuales < diferencia:
                    return False, "No hay suficientes láminas pendientes para aumentar el despacho."
                
                cursor.execute("UPDATE traslados SET despacho=%s WHERE id=%s", (nueva_cantidad, id_despacho))
                cursor.execute("UPDATE traslados SET pendientes = pendientes - %s WHERE id=%s", (diferencia, parent_id))
                return True, "Despacho actualizado correctamente."

# 6. Renderizado de Pestañas y Contenedores
lista_pestanas_base = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
pestanas_visibles = lista_pestanas_base.copy()
if st.session_state.rol in ["administrador", "boss"]: pestanas_visibles.append("Admin")

tabs = st.tabs(pestanas_visibles)
df_sap_global = pd.read_sql_query("SELECT codigo_lamina, descripcion FROM traslados WHERE pestana='Códigos SAP'", engine)

for idx, nombre_tab in enumerate(lista_pestanas_base):
    with tabs[idx]:
        with st.container():
            df_datos = obtener_registros(nombre_tab)
            df_pedidos_base = df_datos[df_datos['parent_id'].isna()] if not df_datos.empty else df_datos
            
            if st.session_state.rol in ["administrador", "boss"]:
                c_add, c_edit, c_del = st.columns(3)
                with c_add:
                    with st.expander("➕ Añadir Petición"):
                        if nombre_tab != "Códigos SAP":
                            if not df_sap_global.empty:
                                opts = df_sap_global.apply(lambda r: f"{r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                                sel_sap = st.selectbox("Buscar en SAP:", options=opts, key=f"sel_sap_add_{nombre_tab}")
                                def_cod, def_desc = sel_sap.split(" - ")[0].strip(), sel_sap.split(" - ")[1].strip()
                            else:
                                st.warning("SAP Vacío")
                                def_cod, def_desc = "", ""
                            
                            with st.form(f"form_add_pet_{nombre_tab}", clear_on_submit=True):
                                c_fin = st.text_input("Código", value=def_cod)
                                d_fin = st.text_input("Descripción", value=def_desc)
                                q_fin = st.number_input("Cantidad", min_value=1, value=1, step=1)
                                if st.form_submit_button("Registrar (Presione Enter)", type="primary"):
                                    if c_fin:
                                        agregar_nuevo_registro(nombre_tab, c_fin, d_fin, q_fin, st.session_state.usuario)
                                        st.session_state.mensaje_toast = "Registrado."
                                        st.rerun()
                        else:
                            with st.form(f"form_add_sap_{nombre_tab}", clear_on_submit=True):
                                c_s = st.text_input("Código SAP")
                                d_s = st.text_input("Descripción")
                                if st.form_submit_button("Añadir a SAP"):
                                    if c_s:
                                        agregar_nuevo_registro("Códigos SAP", c_s, d_s, 1, st.session_state.usuario)
                                        st.session_state.mensaje_toast = "SAP Actualizado."
                                        st.rerun()
                with c_edit:
                    with st.expander("📝 Modificar Petición"):
                        if not df_pedidos_base.empty:
                            opts_mod = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                            sel_mod = st.selectbox("Elegir:", opts_mod, key=f"sel_mod_{nombre_tab}")
                            id_mod = int(sel_mod.split(" | ")[0].replace("ID: ", ""))
                            fila_m = df_pedidos_base[df_pedidos_base['id'] == id_mod].iloc[0]
                            
                            with st.form(f"form_mod_pet_{nombre_tab}"):
                                c_upd = st.text_input("Código", value=str(fila_m['codigo_lamina']))
                                d_upd = st.text_input("Descripción", value=str(fila_m['descripcion']))
                                q_upd = st.number_input("Cantidad", min_value=1, value=int(fila_m['cantidad'])) if nombre_tab != "Códigos SAP" else 1
                                if st.form_submit_button("Actualizar Petición"):
                                    with conectar_bd() as cx:
                                        with cx.cursor() as cu:
                                            cu.execute("SELECT COALESCE(SUM(despacho),0) FROM traslados WHERE parent_id=%s", (id_mod,))
                                            despachado_total = int(cu.fetchone()[0])
                                            nuevo_pendiente = max(0, q_upd - despachado_total)
                                            cu.execute("UPDATE traslados SET codigo_lamina=%s, descripcion=%s, cantidad=%s, pendientes=%s WHERE id=%s", 
                                                       (c_upd, d_upd, q_upd, nuevo_pendiente, id_mod))
                                    st.session_state.mensaje_toast = "Modificado."
                                    st.rerun()

                with c_del:
                    with st.expander("🗑️ Eliminar Petición"):
                        if not df_pedidos_base.empty:
                            with st.form(f"form_del_pet_{nombre_tab}"):
                                opts_del = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                                items_del = st.multiselect("Remover:", opts_del)
                                if st.form_submit_button("Eliminar Seleccionados", type="primary"):
                                    with conectar_bd() as cx:
                                        with cx.cursor() as cu:
                                            for item in items_del:
                                                i_d = int(item.split(" | ")[0].replace("ID: ", ""))
                                                cu.execute("DELETE FROM traslados WHERE id=%s OR parent_id=%s", (i_d, i_d))
                                    st.session_state.mensaje_toast = "Eliminados."
                                    st.rerun()

            if st.session_state.rol == "moderador" and nombre_tab != "Códigos SAP":
                st.subheader("🚚 Panel de Moderación y Despachos")
                c_mod1, c_mod2 = st.columns(2)
                with c_mod1:
                    with st.expander("✅ Registrar Nuevo Despacho", expanded=True):
                        df_pendientes = df_pedidos_base[df_pedidos_base['pendientes'] > 0]
                        if not df_pendientes.empty:
                            opts_desp = df_pendientes.apply(lambda r: f"Petición ID: {r['id']} | Cód: {r['codigo_lamina']} | Pendiente: {r['pendientes']}", axis=1).tolist()
                            sel_pet_desp = st.selectbox("Petición:", opts_desp, key=f"sel_pet_desp_{nombre_tab}")
                            id_padre = int(sel_pet_desp.split(" | ")[0].replace("Petición ID: ", ""))
                            max_disp = int(sel_pet_desp.split("Pendiente: ")[1])
                            
                            with st.form(f"form_new_despacho_{nombre_tab}", clear_on_submit=True):
                                q_despacho = st.number_input("Cantidad a despachar:", min_value=1, max_value=max_disp, value=1, step=1)
                                if st.form_submit_button("Confirmar Despacho (Enter)", type="primary"):
                                    timestamp = obtener_hora_venezuela()
                                    nuevo_pend = max_disp - q_despacho
                                    with conectar_bd() as cx:
                                        with cx.cursor() as cu:
                                            cu.execute("""
                                                INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id)
                                                VALUES (%s, %s, '=', '=', 0, False, %s, %s, %s, %s)
                                            """, (nombre_tab, timestamp, st.session_state.usuario, q_despacho, nuevo_pend, id_padre))
                                            cu.execute("UPDATE traslados SET pendientes=%s WHERE id=%s", (nuevo_pend, id_padre))
                                    st.session_state.mensaje_toast = "Despacho exitoso."
                                    st.rerun()
                        else:
                            st.info("No hay láminas pendientes.")

                with c_mod2:
                    with st.expander("✏️ Editar o Eliminar un Despacho"):
                        df_hijos = df_datos[df_datos['parent_id'].notna()] if not df_datos.empty else pd.DataFrame()
                        if not df_hijos.empty:
                            opts_hijos = df_hijos.apply(lambda r: f"Despacho ID: {r['id']} | Padre: {int(r['parent_id'])} | Cant: {int(r['despacho'])}", axis=1).tolist()
                            sel_hijo = st.selectbox("Seleccione el Despacho a corregir:", opts_hijos, key=f"sel_hijo_edit_{nombre_tab}")
                            id_desp_edit = int(sel_hijo.split(" | ")[0].replace("Despacho ID: ", ""))
                            cant_actual_desp = int(sel_hijo.split("Cant: ")[1])
                            
                            with st.form(f"form_edit_despacho_{nombre_tab}"):
                                st.write("Si pones **0**, el despacho se eliminará y las láminas volverán a Pendientes.")
                                new_q_desp = st.number_input("Nueva Cantidad Despachada:", min_value=0, value=cant_actual_desp, step=1)
                                if st.form_submit_button("Modificar Despacho"):
                                    exito, msg = modificar_despacho_db(id_desp_edit, new_q_desp)
                                    if exito: st.session_state.mensaje_toast = msg
                                    else: st.session_state.error_toast = msg
                                    st.rerun()
                        else:
                            st.info("No hay despachos registrados para editar.")

            st.write("---")
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
                    df_tabla['codigo_lamina'] = df_tabla['codigo_lamina'].astype(str)
                    df_tabla['descripcion'] = df_tabla['descripcion'].astype(str)
                    df_tabla['cantidad'] = df_tabla['cantidad'].astype(str)
                    
                    mascara_sub = df_tabla['parent_id'].notna()
                    df_tabla.loc[mascara_sub, 'codigo_lamina'] = "↳"
                    df_tabla.loc[mascara_sub, 'descripcion'] = "Despacho"
                    df_tabla.loc[mascara_sub, 'cantidad'] = "-"

                columnas_config = {
                    "id": None, "parent_id": None,
                    "hora": st.column_config.TextColumn("Fecha", disabled=True),
                    "codigo_lamina": st.column_config.TextColumn("Código", disabled=True),
                    "descripcion": st.column_config.TextColumn("Descripción", disabled=True),
                    "cantidad": st.column_config.TextColumn("Solicitado", disabled=True),
                    "creado_por": st.column_config.TextColumn("Autor", disabled=True),
                    "verificado": st.column_config.CheckboxColumn("Verific.", disabled=st.session_state.rol not in ["administrador", "boss"]),
                    "despacho": st.column_config.NumberColumn("Despachado", disabled=True),
                    "pendientes": st.column_config.NumberColumn("Pendiente", disabled=True),
                }

            editor_k = f"dt_editor_{nombre_tab}"
            st.data_editor(df_tabla, column_config=columnas_config, hide_index=True, use_container_width=True, disabled=(st.session_state.rol == "moderador"), key=editor_k)
            
            if nombre_tab != "Códigos SAP" and st.session_state.rol in ["administrador", "boss"]:
                if st.button("Guardar Checks (Verificaciones)", key=f"btn_chk_{nombre_tab}"):
                    cambios = st.session_state[editor_k].get("edited_rows", {})
                    if cambios:
                        with conectar_bd() as cx:
                            with cx.cursor() as cu:
                                for idx_str, d_cam in cambios.items():
                                    if "verificado" in d_cam:
                                        id_bd = int(df_datos.iloc[int(idx_str)]['id'])
                                        cu.execute("UPDATE traslados SET verificado=%s WHERE id=%s", (bool(d_cam["verificado"]), id_bd))
                        st.session_state.mensaje_toast = "Verificaciones Guardadas"
                        st.rerun()

# 7. Panel de Administrador (Roles y Excel Automático)
if st.session_state.rol in ["administrador", "boss"]:
    with tabs[4]: 
        with st.container():
            st.header("⚙️ Administración General y Datos")
            
            c_u1, c_u2 = st.columns(2)
            
            # --- GESTIÓN DE USUARIOS ---
            with c_u1:
                st.subheader("👥 Gestión de Usuarios")
                df_us = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios", engine)
                st.dataframe(df_us, use_container_width=True, hide_index=True)
                
                with st.expander("➕ Crear o Modificar Usuario"):
                    with st.form("form_add_user", clear_on_submit=True):
                        new_cedula = st.text_input("Usuario / Cédula")
                        new_pass = st.text_input("Contraseña")
                        new_rol = st.selectbox("Rol", ["moderador", "administrador", "boss"])
                        if st.form_submit_button("Guardar Usuario", type="primary"):
                            if new_cedula and new_pass:
                                with conectar_bd() as cx:
                                    with cx.cursor() as cu:
                                        cu.execute("""
                                            INSERT INTO usuarios (cedula, password, rol) VALUES (%s, %s, %s)
                                            ON CONFLICT (cedula) DO UPDATE SET password=EXCLUDED.password, rol=EXCLUDED.rol
                                        """, (new_cedula, new_pass, new_rol))
                                st.session_state.mensaje_toast = "Usuario registrado/modificado exitosamente."
                                st.rerun()
                            else:
                                st.error("Llene todos los campos.")
                                
                with st.expander("🗑️ Eliminar Usuario"):
                    with st.form("form_del_user"):
                        del_cedula = st.selectbox("Seleccione un usuario", df_us['cedula'].tolist())
                        if st.form_submit_button("Eliminar"):
                            if del_cedula == st.session_state.usuario:
                                st.error("No puedes eliminarte a ti mismo.")
                            else:
                                with conectar_bd() as cx:
                                    with cx.cursor() as cu:
                                        cu.execute("DELETE FROM usuarios WHERE cedula=%s", (del_cedula,))
                                st.session_state.mensaje_toast = "Usuario eliminado."
                                st.rerun()

            # --- GESTIÓN DE EXCEL ---
            with c_u2:
                st.subheader("📊 Importar / Exportar Datos Excel")
                
                st.write("**Exportar Base de Datos Completa**")
                df_export = pd.read_sql_query("SELECT * FROM traslados ORDER BY id ASC", engine)
                if not df_export.empty:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_export.to_excel(writer, index=False, sheet_name='Registros_Completos')
                    
                    st.download_button(
                        label="📥 Descargar Toda la BD (.xlsx)",
                        data=output.getvalue(),
                        file_name=f"Backup_BD_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                
                st.write("---")
                st.write("**Importación Mágica (Modificador Automático)**")
                st.info("Sube un Excel con las columnas `pestana`, `codigo_lamina`, `descripcion` y `cantidad`. Si el código ya existe, automáticamente acumula la cantidad o actualiza la descripción; de lo contrario, crea uno nuevo.")
                uploaded_file = st.file_uploader("Cargar Archivo Excel", type=["xlsx", "xls"])
                
                if uploaded_file is not None:
                    if st.button("Procesar Archivo e Integrar", type="primary", use_container_width=True):
                        try:
                            df_import = pd.read_excel(uploaded_file)
                            if 'codigo_lamina' in df_import.columns and 'pestana' in df_import.columns:
                                timestamp = obtener_hora_venezuela()
                                count_new = 0
                                count_upd = 0
                                with conectar_bd() as cx:
                                    with cx.cursor() as cu:
                                        for _, row in df_import.iterrows():
                                            pest = str(row['pestana'])
                                            cod = str(row['codigo_lamina'])
                                            desc = str(row.get('descripcion', ''))
                                            cant = int(row.get('cantidad', 1)) if pd.notna(row.get('cantidad')) else 1
                                            
                                            # Verificamos si ya existe ese código matriz en esa pestaña
                                            cu.execute("SELECT id, cantidad, pendientes FROM traslados WHERE pestana=%s AND codigo_lamina=%s AND parent_id IS NULL", (pest, cod))
                                            existe = cu.fetchone()
                                            
                                            if existe:
                                                id_bd, cant_vieja, pend_viejo = existe
                                                if pest == "Códigos SAP":
                                                    cu.execute("UPDATE traslados SET descripcion=%s WHERE id=%s", (desc, id_bd))
                                                else:
                                                    # Modificador Automático: Suma la cantidad nueva a la existente
                                                    nueva_cant = cant_vieja + cant
                                                    nuevo_pend = pend_viejo + cant
                                                    cu.execute("UPDATE traslados SET cantidad=%s, pendientes=%s, descripcion=%s WHERE id=%s", (nueva_cant, nuevo_pend, desc, id_bd))
                                                count_upd += 1
                                            else:
                                                pend_ini = cant if pest != "Códigos SAP" else 0
                                                cu.execute("""
                                                    INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes)
                                                    VALUES (%s, %s, %s, %s, %s, False, %s, 0, %s)
                                                """, (pest, timestamp, cod, desc, cant, st.session_state.usuario, pend_ini))
                                                count_new += 1
                                st.success(f"¡Integración Completa! Se añadieron {count_new} registros nuevos y se acumularon/actualizaron {count_upd} existentes.")
                            else:
                                st.error("Asegúrate de que el Excel tenga las columnas: 'pestana' y 'codigo_lamina'.")
                        except Exception as e:
                            st.error(f"Error al procesar: {e}")
