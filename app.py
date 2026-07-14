import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io
import re

# ==========================================
# 1. Configuración y Estilos
# ==========================================
st.set_page_config(page_title="CLC Colchones", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    div[data-testid="stTabs"] [data-testid="stTabContent"] { display: none; }
    div[data-testid="stTabs"] [data-testid="stTabContent"][aria-hidden="false"] { display: block; }
    .block-container { padding: 2rem 2rem !important; }
    </style>
""", unsafe_allow_html=True)

def obtener_hora_venezuela():
    zona_horaria_vzla = datetime.timezone(datetime.timedelta(hours=-4))
    return datetime.datetime.now(zona_horaria_vzla).strftime("%Y-%m-%d %H:%M")

# ==========================================
# 2. Motor de Base de Datos Seguro
# ==========================================
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
    except Exception as e:
        st.error("Error crítico de conexión a la base de datos.")
        st.stop()

engine = obtener_motor_bd()

def conectar_bd():
    try:
        conn = psycopg2.connect(st.secrets["DATABASE_URL"])
        conn.autocommit = True
        return conn
    except Exception as e:
        return None

# Creación de tablas segura
conn = conectar_bd()
if conn:
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (cedula TEXT PRIMARY KEY, password TEXT, rol TEXT)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS traslados (
                    id SERIAL PRIMARY KEY, pestana TEXT, hora TEXT, codigo_lamina TEXT,
                    descripcion TEXT, cantidad INTEGER, verificado BOOLEAN, creado_por TEXT,
                    despacho INTEGER DEFAULT 0, pendientes INTEGER DEFAULT 0, parent_id INTEGER
                )
            """)
            cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss') ON CONFLICT (cedula) DO NOTHING")
            cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador') ON CONFLICT (cedula) DO NOTHING")
            cursor.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('mod', 'mod123', 'moderador') ON CONFLICT (cedula) DO NOTHING")
    conn.close()

# ==========================================
# 3. Módulo de Auto-Adaptación de Excel
# ==========================================
def adaptar_excel_automaticamente(df):
    try:
        if df.empty: return pd.DataFrame()

        df.columns = df.columns.astype(str).str.lower().str.strip()

        alias_cod = ['codigo_lamina', 'codigo', 'cod', 'sku', 'material', 'id', 'item', 'artículo']
        alias_desc = ['descripcion', 'desc', 'detalle', 'nombre', 'producto']
        alias_cant = ['cantidad', 'cant', 'q', 'qty', 'unidad', 'unidades']

        col_cod, col_desc, col_cant = None, None, None

        for col in df.columns:
            if not col_cod and any(a in col for a in alias_cod): col_cod = col
            elif not col_desc and any(a in col for a in alias_desc): col_desc = col
            elif not col_cant and any(a in col for a in alias_cant): col_cant = col

        columnas_disp = list(df.columns)
        if not col_cod and len(columnas_disp) > 0: col_cod = columnas_disp[0]
        if not col_desc and len(columnas_disp) > 1: col_desc = columnas_disp[1]
        if not col_cant and len(columnas_disp) > 2: col_cant = columnas_disp[2]

        if not col_cod: return pd.DataFrame() 

        rename_dict = {col_cod: 'codigo_lamina'}
        if col_desc: rename_dict[col_desc] = 'descripcion'
        if col_cant: rename_dict[col_cant] = 'cantidad'
        df = df.rename(columns=rename_dict)

        if 'descripcion' not in df.columns: df['descripcion'] = "Sin descripción"
        if 'cantidad' not in df.columns: df['cantidad'] = 1

        df['codigo_lamina'] = df['codigo_lamina'].astype(str).str.strip().replace('nan', '')
        df['descripcion'] = df['descripcion'].astype(str).str.strip().replace('nan', '')
        df['cantidad'] = pd.to_numeric(df['cantidad'], errors='coerce').fillna(1).astype(int)

        df = df[df['codigo_lamina'] != '']
        return df[['codigo_lamina', 'descripcion', 'cantidad']]
    except Exception as e:
        return pd.DataFrame() 

# ==========================================
# 4. Funciones de Base de Datos y Operaciones
# ==========================================
def obtener_registros(pestana):
    try:
        query = f"SELECT * FROM traslados WHERE pestana='{pestana}' ORDER BY COALESCE(parent_id, id) ASC, parent_id IS NOT NULL ASC, id ASC"
        df = pd.read_sql_query(query, engine)
        if not df.empty:
            df['despacho'] = df['despacho'].fillna(0).astype(int)
            df['pendientes'] = df['pendientes'].fillna(0).astype(int)
        return df
    except Exception:
        return pd.DataFrame()

def agregar_nuevo_registro(pestana, codigo, descripcion, cantidad, autor):
    try:
        timestamp = obtener_hora_venezuela()
        inicial_pendiente = int(cantidad) if pestana != "Códigos SAP" else 0
        conn = conectar_bd()
        if conn:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s)
                    """, (pestana, timestamp, str(codigo), str(descripcion), int(cantidad), False, autor, inicial_pendiente))
            conn.close()
    except Exception as e:
        pass 

def modificar_despacho_db(id_despacho, nueva_cantidad):
    conn = None
    try:
        id_despacho = int(id_despacho)
        nueva_cantidad = int(nueva_cantidad)
        
        conn = conectar_bd()
        if not conn: return False, "Error: Sin conexión a base de datos."
        
        with conn: 
            with conn.cursor() as cursor:
                cursor.execute("SELECT despacho, parent_id FROM traslados WHERE id=%s", (id_despacho,))
                info = cursor.fetchone()
                if not info: return False, "Error: Despacho no existe."
                
                cant_vieja = int(info[0])
                parent_id = int(info[1])
                
                cursor.execute("SELECT pendientes FROM traslados WHERE id=%s", (parent_id,))
                padre_info = cursor.fetchone()
                if not padre_info: return False, "Error: Pedido base eliminado."
                
                pendientes_actuales = int(padre_info[0])
                diferencia = nueva_cantidad - cant_vieja
                
                if nueva_cantidad == 0:
                    cursor.execute("UPDATE traslados SET pendientes = pendientes + %s WHERE id=%s", (cant_vieja, parent_id))
                    cursor.execute("DELETE FROM traslados WHERE id=%s", (id_despacho,))
                    return True, "Despacho eliminado. Láminas devueltas."
                else:
                    if diferencia > 0 and pendientes_actuales < diferencia:
                        return False, "Láminas insuficientes para aumentar el despacho."
                    cursor.execute("UPDATE traslados SET despacho=%s WHERE id=%s", (nueva_cantidad, id_despacho))
                    cursor.execute("UPDATE traslados SET pendientes = pendientes - %s WHERE id=%s", (diferencia, parent_id))
                    return True, "Despacho actualizado correctamente."
    except Exception as e:
        return False, f"Error interno: {e}"
    finally:
        if conn:
            conn.close()

# ==========================================
# 5. Sistema de Sesión
# ==========================================
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

if st.session_state.usuario is None:
    st.title("Iniciar Sesión — CLC Colchones")
    with st.form("login_form"):
        user_in = st.text_input("Usuario / Cédula").strip()
        pass_in = st.text_input("Contraseña", type="password").strip()
        submit_login = st.form_submit_button("Acceder", type="primary", use_container_width=True)
        
        if submit_login:
            if user_in and pass_in:
                conn = conectar_bd()
                if conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT rol, password FROM usuarios WHERE cedula=%s", (user_in,))
                        res = cursor.fetchone()
                        if res and res[1] == pass_in:
                            st.session_state.usuario = user_in
                            st.session_state.rol = res[0]
                            st.rerun()
                        else:
                            st.error("Datos incorrectos.")
                    conn.close()
                else:
                    st.error("No hay conexión a la base de datos.")
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

# ==========================================
# 6. Interfaz Principal y Pestañas
# ==========================================
lista_pestanas_base = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
pestanas_visibles = lista_pestanas_base.copy()
if st.session_state.rol in ["administrador", "boss"]: pestanas_visibles.append("Admin")

tabs = st.tabs(pestanas_visibles)

try:
    df_sap_global = pd.read_sql_query("SELECT codigo_lamina, descripcion FROM traslados WHERE pestana='Códigos SAP'", engine)
except:
    df_sap_global = pd.DataFrame()

for idx, nombre_tab in enumerate(lista_pestanas_base):
    with tabs[idx]:
        with st.container():
            df_datos = obtener_registros(nombre_tab)
            df_pedidos_base = df_datos[df_datos['parent_id'].isna()] if not df_datos.empty else df_datos
            
            # --- PANELES ADMINISTRADOR / BOSS ---
            if st.session_state.rol in ["administrador", "boss"]:
                c_add, c_edit, c_del = st.columns(3)
                
                # AÑADIR
                with c_add:
                    with st.expander("➕ Añadir Petición"):
                        if nombre_tab != "Códigos SAP":
                            def_cod, def_desc = "", ""
                            if not df_sap_global.empty:
                                opts = df_sap_global.apply(lambda r: f"{r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                                sel_sap = st.selectbox("Buscar en SAP:", options=opts, key=f"sel_sap_add_{nombre_tab}")
                                if sel_sap: def_cod, def_desc = sel_sap.split(" - ")[0].strip(), sel_sap.split(" - ")[1].strip()
                            else:
                                st.warning("SAP Vacío")
                            
                            with st.form(f"form_add_pet_{nombre_tab}", clear_on_submit=True):
                                c_fin = st.text_input("Código", value=def_cod)
                                d_fin = st.text_input("Descripción", value=def_desc)
                                q_fin_str = st.text_input("Cantidad", value="1")
                                
                                if st.form_submit_button("Registrar (Presione Enter)", type="primary"):
                                    q_fin = int(q_fin_str) if q_fin_str.isdigit() else 1
                                    if c_fin.strip():
                                        agregar_nuevo_registro(nombre_tab, c_fin, d_fin, q_fin, st.session_state.usuario)
                                        st.session_state.mensaje_toast = "Registrado."
                                        st.rerun()
                        else:
                            with st.form(f"form_add_sap_{nombre_tab}", clear_on_submit=True):
                                c_s = st.text_input("Código SAP")
                                d_s = st.text_input("Descripción")
                                if st.form_submit_button("Añadir a SAP"):
                                    if c_s.strip():
                                        agregar_nuevo_registro("Códigos SAP", c_s, d_s, 1, st.session_state.usuario)
                                        st.session_state.mensaje_toast = "SAP Actualizado."
                                        st.rerun()
                
                # MODIFICAR
                with c_edit:
                    with st.expander("📝 Modificar Petición"):
                        if not df_pedidos_base.empty:
                            opts_mod = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                            sel_mod = st.selectbox("Elegir:", opts_mod, key=f"sel_mod_{nombre_tab}")
                            if sel_mod:
                                id_mod = int(sel_mod.split(" | ")[0].replace("ID: ", ""))
                                fila_m = df_pedidos_base[df_pedidos_base['id'] == id_mod].iloc[0]
                                
                                with st.form(f"form_mod_pet_{nombre_tab}"):
                                    c_upd = st.text_input("Código", value=str(fila_m.get('codigo_lamina', '')))
                                    d_upd = st.text_input("Descripción", value=str(fila_m.get('descripcion', '')))
                                    
                                    val_cant_m = str(int(fila_m.get('cantidad', 1))) if nombre_tab != "Códigos SAP" else "1"
                                    q_upd_str = st.text_input("Cantidad", value=val_cant_m)
                                    
                                    if st.form_submit_button("Actualizar"):
                                        q_upd = int(q_upd_str) if q_upd_str.isdigit() else 1
                                        conn = conectar_bd()
                                        if conn:
                                            with conn.cursor() as cu:
                                                cu.execute("SELECT COALESCE(SUM(despacho),0) FROM traslados WHERE parent_id=%s", (id_mod,))
                                                despachado_total = int(cu.fetchone()[0])
                                                nuevo_pendiente = max(0, q_upd - despachado_total)
                                                cu.execute("UPDATE traslados SET codigo_lamina=%s, descripcion=%s, cantidad=%s, pendientes=%s WHERE id=%s", 
                                                           (c_upd, d_upd, q_upd, nuevo_pendiente, id_mod))
                                            conn.close()
                                        st.session_state.mensaje_toast = "Modificado."
                                        st.rerun()

                # ELIMINAR
                with c_del:
                    with st.expander("🗑️ Eliminar Petición"):
                        if not df_pedidos_base.empty:
                            with st.form(f"form_del_pet_{nombre_tab}"):
                                opts_del = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                                items_del = st.multiselect("Remover:", opts_del)
                                if st.form_submit_button("Eliminar Seleccionados", type="primary"):
                                    if items_del:
                                        conn = conectar_bd()
                                        if conn:
                                            with conn.cursor() as cu:
                                                for item in items_del:
                                                    i_d = int(item.split(" | ")[0].replace("ID: ", ""))
                                                    cu.execute("DELETE FROM traslados WHERE id=%s OR parent_id=%s", (i_d, i_d))
                                            conn.close()
                                        st.session_state.mensaje_toast = "Eliminados."
                                        st.rerun()

                # --- MÓDULO EXCEL INTELIGENTE ---
                with st.expander(f"📊 Importar / Exportar Excel - Área {nombre_tab}"):
                    c_exp, c_imp = st.columns(2)
                    with c_exp:
                        st.markdown(f"**📥 Descargar registros**")
                        if not df_datos.empty:
                            try:
                                output = io.BytesIO()
                                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                                    # Exportamos el DataFrame completo con la info original para que el Excel sí la tenga
                                    df_datos.to_excel(writer, index=False, sheet_name=nombre_tab)
                                st.download_button("Descargar Excel", data=output.getvalue(), file_name=f"Datos_{nombre_tab}.xlsx",
                                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"btn_ex_{nombre_tab}")
                            except Exception as e:
                                st.error("Error al generar el archivo.")
                        else:
                            st.info("No hay datos para exportar.")
                            
                    with c_imp:
                        st.markdown(f"**📤 Importación Inteligente**")
                        st.caption("Adapta el formato automáticamente. Ignora errores.")
                        uploaded_file = st.file_uploader(f"Subir Excel para {nombre_tab}", type=["xlsx", "xls", "csv"], key=f"file_up_{nombre_tab}")
                        if uploaded_file:
                            if st.button("Procesar Archivo", key=f"btn_proc_{nombre_tab}"):
                                with st.spinner("Limpiando e integrando datos..."):
                                    try:
                                        if uploaded_file.name.endswith('.csv'): df_import = pd.read_csv(uploaded_file)
                                        else: df_import = pd.read_excel(uploaded_file)
                                        
                                        df_import = adaptar_excel_automaticamente(df_import)
                                        
                                        if not df_import.empty:
                                            timestamp = obtener_hora_venezuela()
                                            c_new, c_upd = 0, 0
                                            conn = conectar_bd()
                                            if conn:
                                                with conn.cursor() as cu:
                                                    for _, row in df_import.iterrows():
                                                        cod = str(row['codigo_lamina'])
                                                        desc = str(row['descripcion'])
                                                        cant = int(row['cantidad'])
                                                        
                                                        cu.execute("SELECT id, cantidad, pendientes FROM traslados WHERE pestana=%s AND codigo_lamina=%s AND parent_id IS NULL", (nombre_tab, cod))
                                                        existe = cu.fetchone()
                                                        
                                                        if existe:
                                                            id_bd, cant_vieja, pend_viejo = existe
                                                            if nombre_tab == "Códigos SAP":
                                                                cu.execute("UPDATE traslados SET descripcion=%s WHERE id=%s", (desc, id_bd))
                                                            else:
                                                                cu.execute("UPDATE traslados SET cantidad=%s, pendientes=%s, descripcion=%s WHERE id=%s", 
                                                                           (cant_vieja + cant, pend_viejo + cant, desc, id_bd))
                                                            c_upd += 1
                                                        else:
                                                            pend_ini = cant if nombre_tab != "Códigos SAP" else 0
                                                            cu.execute("""
                                                                INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes)
                                                                VALUES (%s, %s, %s, %s, %s, False, %s, 0, %s)
                                                            """, (nombre_tab, timestamp, cod, desc, cant, st.session_state.usuario, pend_ini))
                                                            c_new += 1
                                                conn.close()
                                                st.session_state.mensaje_toast = f"¡Éxito! {c_new} nuevos, {c_upd} sumados."
                                                st.rerun()
                                        else:
                                            st.error("No se detectaron datos válidos. Intenta verificar el formato de tu archivo.")
                                    except Exception as e:
                                        st.error("El archivo está corrupto o es ilegible. Revisa el Excel e intenta de nuevo.")

            # --- PANEL MODERADOR ---
            if st.session_state.rol == "moderador" and nombre_tab != "Códigos SAP":
                st.subheader("🚚 Panel de Moderación y Despachos")
                c_mod1, c_mod2 = st.columns(2)
                with c_mod1:
                    with st.expander("✅ Registrar Nuevo Despacho", expanded=True):
                        df_pendientes = df_pedidos_base[df_pedidos_base['pendientes'] > 0] if not df_pedidos_base.empty else pd.DataFrame()
                        if not df_pendientes.empty:
                            opts_desp = df_pendientes.apply(lambda r: f"ID: {r['id']} | Cód: {r['codigo_lamina']} | Pend: {r['pendientes']}", axis=1).tolist()
                            sel_pet_desp = st.selectbox("Petición:", opts_desp, key=f"sel_pet_desp_{nombre_tab}")
                            if sel_pet_desp:
                                id_padre = int(sel_pet_desp.split(" | ")[0].replace("ID: ", ""))
                                max_disp = int(sel_pet_desp.split("Pend: ")[1])
                                
                                with st.form(f"form_new_despacho_{nombre_tab}", clear_on_submit=True):
                                    q_despacho_str = st.text_input("Cantidad a despachar:", value="1")
                                    
                                    if st.form_submit_button("Confirmar Despacho", type="primary"):
                                        q_despacho = int(q_despacho_str) if q_despacho_str.isdigit() else 1
                                        if q_despacho > max_disp: q_despacho = max_disp
                                        
                                        timestamp = obtener_hora_venezuela()
                                        conn = conectar_bd()
                                        if conn:
                                            with conn.cursor() as cu:
                                                cu.execute("""
                                                    INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id)
                                                    VALUES (%s, %s, '=', '=', 0, False, %s, %s, %s, %s)
                                                """, (nombre_tab, timestamp, st.session_state.usuario, q_despacho, max_disp - q_despacho, id_padre))
                                                cu.execute("UPDATE traslados SET pendientes=%s WHERE id=%s", (max_disp - q_despacho, id_padre))
                                            conn.close()
                                        st.session_state.mensaje_toast = "Despacho exitoso."
                                        st.rerun()
                        else:
                            st.info("No hay láminas pendientes.")

                with c_mod2:
                    with st.expander("✏️ Editar/Eliminar Despacho"):
                        df_hijos = df_datos[df_datos['parent_id'].notna()] if not df_datos.empty else pd.DataFrame()
                        if not df_hijos.empty:
                            opts_hijos = df_hijos.apply(lambda r: f"ID: {r['id']} | Padre: {int(r['parent_id'])} | Cant: {int(r['despacho'])}", axis=1).tolist()
                            sel_hijo = st.selectbox("Despacho:", opts_hijos, key=f"sel_hijo_edit_{nombre_tab}")
                            if sel_hijo:
                                id_desp_edit = int(sel_hijo.split(" | ")[0].replace("ID: ", ""))
                                cant_actual_desp = int(sel_hijo.split("Cant: ")[1])
                                
                                with st.form(f"form_edit_despacho_{nombre_tab}"):
                                    st.caption("Pon **0** para eliminar y devolver.")
                                    new_q_desp_str = st.text_input("Nueva Cant:", value=str(cant_actual_desp))
                                    
                                    if st.form_submit_button("Modificar"):
                                        new_q_desp = int(new_q_desp_str) if new_q_desp_str.isdigit() else 0
                                        exito, msg = modificar_despacho_db(id_desp_edit, new_q_desp)
                                        if exito: st.session_state.mensaje_toast = msg
                                        else: st.session_state.error_toast = msg
                                        st.rerun()
                        else:
                            st.info("No hay despachos.")

            # --- TABLA VISUAL SEGURA ---
            st.write("---")
            if nombre_tab == "Códigos SAP":
                df_tabla = df_datos[['id', 'codigo_lamina', 'descripcion']].copy() if not df_datos.empty else pd.DataFrame(columns=['id','codigo_lamina','descripcion'])
                columnas_config = {"id": None, "codigo_lamina": st.column_config.TextColumn("Código SAP", disabled=True), "descripcion": st.column_config.TextColumn("Descripción de Material", disabled=True)}
            else:
                df_tabla = df_datos.copy() if not df_datos.empty else pd.DataFrame()
                if not df_tabla.empty:
                    df_tabla['verificado'] = df_tabla['verificado'].fillna(False).astype(bool)
                    df_tabla['codigo_lamina'] = df_tabla['codigo_lamina'].astype(str).replace('nan','')
                    df_tabla['descripcion'] = df_tabla['descripcion'].astype(str).replace('nan','')
                    df_tabla['cantidad'] = df_tabla['cantidad'].astype(str)
                    
                    mascara_sub = df_tabla['parent_id'].notna()
                    df_tabla.loc[mascara_sub, 'codigo_lamina'] = "↳"
                    df_tabla.loc[mascara_sub, 'descripcion'] = "Despacho"
                    df_tabla.loc[mascara_sub, 'cantidad'] = "-"
                    
                    # ELIMINACIÓN TOTAL DE LAS COLUMNAS HORA Y CREADO_POR PARA LA INTERFAZ
                    df_tabla = df_tabla.drop(columns=['hora', 'creado_por'], errors='ignore')

                columnas_config = {
                    "id": None, "parent_id": None,
                    "codigo_lamina": st.column_config.TextColumn("Código", disabled=True),
                    "descripcion": st.column_config.TextColumn("Descripción", disabled=True),
                    "cantidad": st.column_config.TextColumn("Solicitado", disabled=True),
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
                        conn = conectar_bd()
                        if conn:
                            with conn.cursor() as cu:
                                for idx_str, d_cam in cambios.items():
                                    if "verificado" in d_cam:
                                        id_bd = int(df_tabla.iloc[int(idx_str)]['id'])
                                        cu.execute("UPDATE traslados SET verificado=%s WHERE id=%s", (bool(d_cam["verificado"]), id_bd))
                            conn.close()
                            st.session_state.mensaje_toast = "Verificaciones Guardadas"
                            st.rerun()

# ==========================================
# 7. Panel de Admin Global
# ==========================================
if st.session_state.rol in ["administrador", "boss"]:
    with tabs[4]: 
        with st.container():
            st.header("⚙️ Administración General")
            try:
                df_us = pd.read_sql_query("SELECT cedula, rol FROM usuarios", engine)
                st.dataframe(df_us, use_container_width=True, hide_index=True)
            except:
                st.error("Error cargando usuarios.")
            
            c_u1, c_u2 = st.columns(2)
            with c_u1:
                with st.expander("➕ Crear/Modificar Usuario", expanded=True):
                    with st.form("form_add_user", clear_on_submit=True):
                        new_cedula = st.text_input("Usuario / Cédula").strip()
                        new_pass = st.text_input("Contraseña").strip()
                        new_rol = st.selectbox("Rol", ["moderador", "administrador", "boss"])
                        if st.form_submit_button("Guardar", type="primary"):
                            if new_cedula and new_pass:
                                conn = conectar_bd()
                                if conn:
                                    with conn.cursor() as cu:
                                        cu.execute("""
                                            INSERT INTO usuarios (cedula, password, rol) VALUES (%s, %s, %s)
                                            ON CONFLICT (cedula) DO UPDATE SET password=EXCLUDED.password, rol=EXCLUDED.rol
                                        """, (new_cedula, new_pass, new_rol))
                                    conn.close()
                                    st.session_state.mensaje_toast = "Usuario guardado."
                                    st.rerun()
                            else:
                                st.error("Llene todos los campos.")
            with c_u2:
                with st.expander("🗑️ Eliminar Usuario", expanded=True):
                    with st.form("form_del_user"):
                        opts_us = df_us['cedula'].tolist() if 'df_us' in locals() else []
                        del_cedula = st.selectbox("Seleccione un usuario", opts_us)
                        if st.form_submit_button("Eliminar"):
                            if del_cedula == st.session_state.usuario:
                                st.error("No puedes eliminarte a ti mismo.")
                            else:
                                conn = conectar_bd()
                                if conn:
                                    with conn.cursor() as cu:
                                        cu.execute("DELETE FROM usuarios WHERE cedula=%s", (del_cedula,))
                                    conn.close()
                                    st.session_state.mensaje_toast = "Usuario eliminado."
                                    st.rerun()
