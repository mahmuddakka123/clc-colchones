import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="CLC Colchones - Gestión", 
    page_icon="🛏️", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS AVANZADO: DISEÑO DIFERENCIADO PARA COMPUTADORA Y CELULAR ---
st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    h1 { font-size: 2.5rem !important; }
    
    @media (max-width: 768px) {
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
            padding-left: 0.4rem !important;
            padding-right: 0.4rem !important;
        }
        h1 { font-size: 1.6rem !important; text-align: center !important; }
        h2, h3, h4 { font-size: 1.2rem !important; }
        div[data-testid="stTabs"] button {
            font-size: 11px !important; padding: 6px 8px !important; gap: 2px !important;
        }
        div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-primary"] {
            padding: 12px 10px !important; font-size: 15px !important; min-height: 45px !important;
        }
        div[data-testid="column"] {
            width: 100% !important; flex: 1 1 auto !important; padding: 0.2rem 0rem !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# Manejo de notificaciones en pantalla
if 'mensaje_toast' in st.session_state:
    st.toast(st.session_state.mensaje_toast, icon="✅")
    del st.session_state.mensaje_toast
if 'error_toast' in st.session_state:
    st.toast(st.session_state.error_toast, icon="🚨")
    del st.session_state.error_toast

# --- 2. CONEXIÓN A BASE DE DATOS EN LA NUBE (SUPABASE) ---
try:
    DB_URL = st.secrets["DATABASE_URL"]
except Exception:
    st.error("🚨 Falta configurar DATABASE_URL en los Secrets de Streamlit.")
    st.stop()

engine = create_engine(DB_URL)
conn = psycopg2.connect(DB_URL)
conn.autocommit = True
c = conn.cursor()

# Crear tablas base en Supabase si no existen
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (cedula TEXT PRIMARY KEY, password TEXT, rol TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS traslados (
                id SERIAL PRIMARY KEY,
                pestana TEXT,
                hora TEXT,
                codigo_lamina TEXT,
                descripcion TEXT,
                cantidad INTEGER,
                verificado BOOLEAN,
                creado_por TEXT
            )''')

# Adaptar la tabla para soportar sub-líneas jerárquicas vinculadas al pedido principal
try:
    c.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS despacho INTEGER DEFAULT 0")
    c.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS pendientes INTEGER DEFAULT 0")
    c.execute("ALTER TABLE traslados ADD COLUMN IF NOT EXISTS parent_id INTEGER")
except Exception as e:
    pass

# Asegurar usuarios por defecto
c.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss') ON CONFLICT (cedula) DO NOTHING")
c.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador') ON CONFLICT (cedula) DO NOTHING")

# --- 3. LOGIN ---
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

def login():
    st.title("🛏️ CLC Colchones - Iniciar Sesión")
    with st.form("login_form"):
        cedula = st.text_input("👤 Usuario")
        password = st.text_input("🔑 Contraseña", type="password")
        submit = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
        if submit:
            if cedula.strip() != "" and password.strip() != "":
                c.execute("SELECT rol, password FROM usuarios WHERE cedula=%s", (cedula.strip(),))
                resultado = c.fetchone()
                if resultado:
                    rol_bd, password_bd = resultado
                    if password.strip() == password_bd:
                        st.session_state.usuario = cedula.strip()
                        st.session_state.rol = rol_bd
                        st.rerun()
                    else: st.error("Contraseña incorrecta.")
                else: st.error("Este usuario no existe.")
            else: st.error("Por favor, llena ambos campos.")

if st.session_state.usuario is None:
    login()
    st.stop()

# --- 4. BARRA LATERAL (SIDEBAR) ---
st.sidebar.title(f"👤 Usuario:\n{st.session_state.usuario}")
st.sidebar.subheader(f"🛡️ Rol: {st.session_state.rol.capitalize()}")
if st.sidebar.button("🔒 Cerrar Sesión", use_container_width=True):
    st.session_state.usuario = None
    st.session_state.rol = None
    st.rerun()

st.title("📦 Panel de Control CLC - Traslado de Láminas")
st.write("---")

# --- FUNCIONES AUXILIARES ---
def cargar_datos(pestana):
    query = f"""SELECT id, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, 
                despacho, pendientes, parent_id 
                FROM traslados WHERE pestana='{pestana}'
                ORDER BY COALESCE(parent_id, id) ASC, parent_id IS NOT NULL ASC, id ASC"""
    df = pd.read_sql_query(query, engine)
    
    if not df.empty:
        df['despacho'] = df['despacho'].fillna(0).astype(int)
        df['pendientes'] = df['pendientes'].fillna(0).astype(int)
    return df

def cargar_todos_los_sap():
    return pd.read_sql_query("SELECT codigo_lamina, descripcion FROM traslados WHERE pestana='Códigos SAP'", engine)

def guardar_nuevo_registro(pestana, codigo, desc, cant, creador):
    hora_actual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pendientes_iniciales = cant if pestana != "Códigos SAP" else 0
    c.execute("""INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, NULL)""",
              (pestana, hora_actual, codigo, desc, cant, False, creador, pendientes_iniciales))

def actualizar_verificacion(id_registro, estado):
    c.execute("UPDATE traslados SET verificado=%s WHERE id=%s", (estado, id_registro))

def actualizar_registro(id_registro, codigo, desc, cant):
    c.execute("SELECT COALESCE(SUM(despacho), 0) FROM traslados WHERE parent_id=%s", (id_registro,))
    total_despachado = int(c.fetchone()[0])
    nuevos_pendientes = max(0, cant - total_despachado)
    c.execute("UPDATE traslados SET codigo_lamina=%s, descripcion=%s, cantidad=%s, pendientes=%s WHERE id=%s", 
              (codigo, desc, cant, nuevos_pendientes, id_registro))

def eliminar_registro(id_registro):
    c.execute("DELETE FROM traslados WHERE id=%s OR parent_id=%s", (id_registro, id_registro))

def generar_excel_perfecto(df, nombre_hoja):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=nombre_hoja)
        if df.empty: return output.getvalue()
        worksheet = writer.sheets[nombre_hoja]
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        borde_fino = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        for cell in worksheet[1]:
            cell.fill = header_fill; cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center"); cell.border = borde_fino
        for col in worksheet.columns:
            max_length = 0
            columna_letra = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length: max_length = len(str(cell.value))
                except: pass
                cell.border = borde_fino
                if cell.row != 1: cell.alignment = Alignment(horizontal="left", vertical="center")
            worksheet.column_dimensions[columna_letra].width = max_length + 3
        worksheet.freeze_panes = "A2"
    return output.getvalue()

# --- 5. INTERFAZ DE PESTAÑAS ---
nombres_pestanas = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
lista_tabs_mostrar = nombres_pestanas.copy()
if st.session_state.rol in ["administrador", "boss"]:
    lista_tabs_mostrar.append("Panel de Administrador")

tabs = st.tabs(lista_tabs_mostrar)
df_sap_global = cargar_todos_los_sap()

for i, nombre_pestana in enumerate(nombres_pestanas):
    with tabs[i]:
        df = cargar_datos(nombre_pestana)
        
        # Filtramos para que en los formularios de modificación solo aparezcan pedidos base y no subtareas
        df_pedidos_base = df[df['parent_id'].isna()] if not df.empty else df
        
        total_registros = len(df_pedidos_base)
        total_laminas = int(df_pedidos_base['cantidad'].sum()) if total_registros > 0 else 0
        verificadas = int(df_pedidos_base['verificado'].sum()) if total_registros > 0 else 0
        
        if nombre_pestana == "Códigos SAP":
            st.metric("📄 Total de Códigos Registrados", len(df))
        else:
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("📄 Total de Pedidos", total_registros)
            col_m2.metric("📦 Unidades Solicitadas", total_laminas)
            col_m3.metric("✅ Verificados", f"{verificadas} de {total_registros}")
            
        st.write("---")
        
        if st.session_state.rol in ["administrador", "moderador", "boss"]:
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            
            with col_exp1:
                with st.expander("➕ Agregar traslado" if nombre_pestana != "Códigos SAP" else "➕ Agregar Código"):
                    if nombre_pestana != "Códigos SAP":
                        if not df_sap_global.empty:
                            lista_opciones_sap = df_sap_global.apply(lambda r: f"{r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                            articulo_sap_elegido = st.selectbox(
                                "🔍 Buscar Artículo SAP:", 
                                options=lista_opciones_sap,
                                key=f"sap_search_{nombre_pestana}"
                            )
                            cod_detectado = articulo_sap_elegido.split(" - ")[0].strip()
                            desc_detectada = articulo_sap_elegido.split(" - ")[1].strip()
                            st.text_input("Código", value=cod_detectado, disabled=True, key=f"disp_cod_{nombre_pestana}")
                            st.text_input("Descripción", value=desc_detectada, disabled=True, key=f"disp_desc_{nombre_pestana}")
                        else:
                            st.warning("⚠️ SAP vacío.")
                            cod_detectado = st.text_input("Código", key=f"manual_cod_{nombre_pestana}")
                            desc_detectada = st.text_input("Descripción", key=f"manual_desc_{nombre_pestana}")
                        
                        with st.form(key=f"form_add_{nombre_pestana}", clear_on_submit=True):
                            nueva_cant = st.number_input("Cantidad", min_value=1, value=1, key=f"num_cant_{nombre_pestana}")
                            submit_add = st.form_submit_button("Agregar", use_container_width=True, type="primary")
                            if submit_add:
                                if cod_detectado != "":
                                    guardar_nuevo_registro(nombre_pestana, cod_detectado, desc_detectada, nueva_cant, st.session_state.usuario)
                                    st.session_state.mensaje_toast = "¡Registro añadido exitosamente!"
                                    st.rerun()
                    else:
                        with st.form(key=f"form_add_sap", clear_on_submit=True):
                            n_cod = st.text_input("Código")
                            n_desc = st.text_input("Descripción")
                            if st.form_submit_button("Registrar en SAP", use_container_width=True):
                                if n_cod != "":
                                    guardar_nuevo_registro("Códigos SAP", n_cod, n_desc, 1, st.session_state.usuario)
                                    st.session_state.mensaje_toast = "Código guardado."
                                    st.rerun()
            
            with col_exp2:
                with st.expander("📝 Modificar pedido" if nombre_pestana != "Códigos SAP" else "📝 Modificar Código"):
                    if not df_pedidos_base.empty:
                        opciones_mod = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                        articulo_mod = st.selectbox("Selecciona registro:", opciones_mod, key=f"sel_mod_{nombre_pestana}")
                        id_real_mod = int(articulo_mod.split(" | ")[0].replace("ID: ", ""))
                        fila_actual = df_pedidos_base[df_pedidos_base['id'] == id_real_mod].iloc[0]
                        val_cant = int(fila_actual['cantidad']) if fila_actual['cantidad'] else 1
                        
                        with st.form(key=f"form_edit_{nombre_pestana}_{id_real_mod}"):
                            m_cod = st.text_input("Código", value=str(fila_actual['codigo_lamina']))
                            m_desc = st.text_input("Descripción", value=str(fila_actual['descripcion']))
                            m_cant = st.number_input("Cantidad", min_value=1, value=val_cant) if nombre_pestana != "Códigos SAP" else val_cant
                            if st.form_submit_button("💾 Guardar Cambios", use_container_width=True):
                                actualizar_registro(id_real_mod, m_cod, m_desc, m_cant)
                                st.session_state.mensaje_toast = "Actualizado con éxito."
                                st.rerun()
                    else: st.info("No hay datos.")

            with col_exp3:
                with st.expander("🗑️ Eliminar pedidos"):
                    if not df_pedidos_base.empty:
                        opciones_eliminar = df_pedidos_base.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']}", axis=1).tolist()
                        seleccion_eliminar = st.multiselect("Elige registros:", opciones_eliminar, key=f"ms_del_{nombre_pestana}")
                        if st.button("⚠️ Eliminar", key=f"btn_del_multi_{nombre_pestana}", type="primary", use_container_width=True):
                            for item in seleccion_eliminar:
                                id_del = int(item.split(" | ")[0].replace("ID: ", ""))
                                eliminar_registro(id_del)
                            st.session_state.mensaje_toast = "Registros y sus despachos eliminados."
                            st.rerun()
        
        st.write("#### 📊 Hoja de Trabajo")
        
        df_display = df.copy()
        if not df_display.empty:
            df_display['verificado'] = df_display['verificado'].astype(bool)
            if 'hora' in df_display.columns:
                df_display['hora'] = pd.to_datetime(df_display['hora']).dt.strftime('%d/%m/%Y %H:%M')
            
            # --- CORRECCIÓN DEL ERROR TYPEERROR AQUÍ ---
            # Convertimos TODAS las columnas afectadas a tipo string ANTES de insertar el símbolo "="
            df_display['codigo_lamina'] = df_display['codigo_lamina'].astype(str)
            df_display['descripcion'] = df_display['descripcion'].astype(str)
            df_display['cantidad'] = df_display['cantidad'].astype(str)
            
            if 'parent_id' in df_display.columns:
                sub_rows_mask = df_display['parent_id'].notna()
                df_display.loc[sub_rows_mask, 'codigo_lamina'] = "="
                df_display.loc[sub_rows_mask, 'descripcion'] = "="
                df_display.loc[sub_rows_mask, 'cantidad'] = "="

        permitir_verificacion = st.session_state.rol in ["administrador", "boss"]
        permitir_despacho = (st.session_state.rol == "moderador")
        
        columnas_config = {
            "id": None, 
            "parent_id": None,
            "hora": st.column_config.TextColumn("📅 Fecha", disabled=True),
            "codigo_lamina": st.column_config.TextColumn("🏷️ Código", disabled=True),
            "descripcion": st.column_config.TextColumn("📝 Descripción", disabled=True),
            "cantidad": st.column_config.TextColumn("🔢 Cantidad", disabled=True),
            "creado_por": st.column_config.TextColumn("👤 Autor", disabled=True),
            "verificado": st.column_config.CheckboxColumn("✅ Verificado", disabled=not permitir_verificacion),
            "despacho": st.column_config.NumberColumn("🚚 Despacho", disabled=not permitir_despacho, min_value=0),
            "pendientes": st.column_config.NumberColumn("⏳ Pendientes", disabled=True),
        }
        
        if nombre_pestana == "Códigos SAP":
            for col in ["hora", "verificado", "creado_por", "cantidad", "despacho", "pendientes", "parent_id"]:
                columnas_config[col] = None
        
        edited_df = st.data_editor(
            df_display,
            column_config=columnas_config,
            hide_index=True,
            use_container_width=True,
            height=380,
            key=f"editor_sheets_{nombre_pestana}"
        )
        
        # --- PROCESAR LOS CAMBIOS DE LA HOJA ---
        if not df.empty and nombre_pestana != "Códigos SAP":
            cambios_realizados = False
            for index, row in edited_df.iterrows():
                id_real = df.loc[index, 'id']
                es_sub_row = pd.notna(df.loc[index, 'parent_id'])
                
                # 1. Procesar verificación (solo admin / boss)
                if permitir_verificacion and row['verificado'] != df.loc[index, 'verificado']:
                    actualizar_verificacion(id_real, row['verificado'])
                    cambios_realizados = True
                
                # 2. Procesar despachos (Solo moderador y SOLO sobre las filas de pedido original)
                if permitir_despacho and not es_sub_row and row['despacho'] != df.loc[index, 'despacho']:
                    nuevo_despacho = int(row['despacho'])
                    
                    if nuevo_despacho > 0:
                        pendiente_actual = int(df.loc[index, 'pendientes'])
                        nuevos_pendientes = max(0, pendiente_actual - nuevo_despacho)
                        hora_movimiento = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Insertar la nueva línea por debajo con los datos del Moderador y con '='
                        c.execute("""INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por, despacho, pendientes, parent_id)
                                     VALUES (%s, %s, %s, %s, 0, %s, %s, %s, %s, %s)""",
                                  (nombre_pestana, hora_movimiento, '=', '=', False, st.session_state.usuario, nuevo_despacho, nuevos_pendientes, id_real))
                        
                        # Actualizar el saldo pendiente en el pedido original para llevar el control acumulativo
                        c.execute("UPDATE traslados SET pendientes=%s WHERE id=%s", (nuevos_pendientes, id_real))
                        cambios_realizados = True
            
            if cambios_realizados:
                st.rerun()

        st.write("---")
        col_down1, col_down2 = st.columns(2)
        
        if st.session_state.rol in ["administrador", "boss"]:
            with col_down1:
                st.subheader("📥 Importar Excel")
                archivo_subido = st.file_uploader("Sube archivo .xlsx", type=["xlsx"], key=f"up_{nombre_pestana}")
                if archivo_subido is not None:
                    try:
                        df_importado = pd.read_excel(archivo_subido)
                        df_importado.columns = [str(c).lower().strip() for c in df_importado.columns]
                        for index, row in df_importado.iterrows():
                            cod = str(row.get('codigo_lamina', row.get('código', row.get('codigo', 'N/A')))).strip()
                            desc = str(row.get('descripcion', row.get('descripción', 'N/A'))).strip()
                            try: cant = int(float(row.get('cantidad', 1)))
                            except: cant = 1
                            guardar_nuevo_registro(nombre_pestana, cod, desc, cant, st.session_state.usuario)
                        st.session_state.mensaje_toast = "¡Excel importado!"
                        st.rerun()
                    except: st.error("🚨 Archivo no legible.")

        with col_down2:
            st.subheader("📤 Exportar Reporte")
            # Se añade errors='ignore' para evitar fallos si las columnas no existen
            df_para_exportar = df_display.drop(columns=['id', 'parent_id'], errors='ignore') if not df_display.empty else df_display
            excel_data = generar_excel_perfecto(df_para_exportar, nombre_pestana)
            st.download_button("📊 Descargar Excel", data=excel_data, 
                file_name=f"CLC_{nombre_pestana}_{datetime.date.today()}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                key=f"down_{nombre_pestana}", type="primary", use_container_width=True)

# --- 6. PANEL DE CONTROL DE USUARIOS ---
if st.session_state.rol in ["administrador", "boss"]:
    with tabs[4]: 
        st.header("⚙️ Configuración Global de Usuarios")
        df_usuarios = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios", engine)
        st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
        col_adm1, col_adm2 = st.columns(2)
        
        with col_adm1:
            with st.form("nuevo_usuario", clear_on_submit=True):
                st.subheader("➕ Crear / Modificar Usuario")
                n_cedula = st.text_input("Usuario")
                n_password = st.text_input("Nueva Contraseña")
                n_rol = st.selectbox("Asignar Rol", ["administrador", "moderador", "visualizador", "boss"])
                if st.form_submit_button("Guardar Usuario", use_container_width=True):
                    if n_cedula.strip() != "" and n_password.strip() != "":
                        c.execute("""INSERT INTO usuarios (cedula, password, rol) VALUES (%s, %s, %s) 
                                     ON CONFLICT (cedula) DO UPDATE SET password = EXCLUDED.password, rol = EXCLUDED.rol""", 
                                  (n_cedula.strip(), n_password.strip(), n_rol))
                        st.session_state.mensaje_toast = f"Usuario {n_cedula} guardado."
                        st.rerun()
        
        with col_adm2:
            with st.form("eliminar_usuario"):
                st.subheader("🗑️ Eliminar Usuario")
                usuario_a_eliminar = st.selectbox("Selecciona el usuario a eliminar", df_usuarios['cedula'].tolist())
                if st.form_submit_button("Eliminar permanentemente", type="primary", use_container_width=True):
                    c.execute("DELETE FROM usuarios WHERE cedula=%s", (usuario_a_eliminar,))
                    st.session_state.mensaje_toast = f"Usuario {usuario_a_eliminar} eliminado."
                    st.rerun()

conn.close()
