import streamlit as st
import pandas as pd
import sqlite3
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
    /* --- 💻 ESTILOS POR DEFECTO (COMPUTADORA) --- */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    h1 {
        font-size: 2.5rem !important;
    }
    
    /* --- 📱 ESTILOS EXCLUSIVOS PARA PANTALLAS PEQUEÑAS (CELULARES) --- */
    @media (max-width: 768px) {
        /* Reduce los márgenes generales para aprovechar la pantalla del móvil */
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
            padding-left: 0.4rem !important;
            padding-right: 0.4rem !important;
        }
        
        /* Ajusta los títulos para que no se corten en celulares */
        h1 {
            font-size: 1.6rem !important;
            text-align: center !important;
        }
        h2, h3, h4 {
            font-size: 1.2rem !important;
        }
        
        /* Optimiza las pestañas de navegación para que quepan en una sola fila móvil */
        div[data-testid="stTabs"] button {
            font-size: 11px !important;
            padding: 6px 8px !important;
            gap: 2px !important;
        }
        
        /* Hace que las tarjetas de métricas sean más compactas */
        div[data-testid="stMetricValue"] {
            font-size: 1.4rem !important;
        }
        
        /* Engorda los botones en el celular para que sea fácil tocarlos con el dedo */
        button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-primary"] {
            padding: 12px 10px !important;
            font-size: 15px !important;
            min-height: 45px !important;
        }
        
        /* Fuerza a que las columnas de los formularios se apilen verticalmente en el celular */
        div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 auto !important;
            padding: 0.2rem 0rem !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# Manejo de notificaciones en pantalla (Toasts)
if 'mensaje_toast' in st.session_state:
    st.toast(st.session_state.mensaje_toast, icon="✅")
    del st.session_state.mensaje_toast
if 'error_toast' in st.session_state:
    st.toast(st.session_state.error_toast, icon="🚨")
    del st.session_state.error_toast

# --- 2. CONEXIÓN A BASE DE DATOS LOCAL (SQLite como en tu VS Code) ---
conn = sqlite3.connect('clc_datos.db', check_same_thread=False)
conn.autocommit = True
c = conn.cursor()

# Crear tablas base si no existen
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (cedula TEXT PRIMARY KEY, password TEXT, rol TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS traslados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pestana TEXT,
                hora TEXT,
                codigo_lamina TEXT,
                descripcion TEXT,
                cantidad INTEGER,
                verificado BOOLEAN,
                creado_por TEXT
            )''')

# Asegurar usuarios por defecto
c.execute("INSERT OR IGNORE INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss')")
c.execute("INSERT OR IGNORE INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador')")

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
                c.execute("SELECT rol, password FROM usuarios WHERE cedula=?", (cedula.strip(),))
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
    return pd.read_sql_query(f"SELECT id, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por FROM traslados WHERE pestana='{pestana}'", conn)

def cargar_todos_los_sap():
    return pd.read_sql_query("SELECT codigo_lamina, descripcion FROM traslados WHERE pestana='Códigos SAP'", conn)

def guardar_nuevo_registro(pestana, codigo, desc, cant, creador):
    hora_actual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (pestana, hora_actual, codigo, desc, cant, False, creador))

def actualizar_verificacion(id_registro, estado):
    c.execute("UPDATE traslados SET verificado=? WHERE id=?", (estado, id_registro))

def actualizar_registro(id_registro, codigo, desc, cant):
    c.execute("UPDATE traslados SET codigo_lamina=?, descripcion=?, cantidad=? WHERE id=?", (codigo, desc, cant, id_registro))

def eliminar_registro(id_registro):
    c.execute("DELETE FROM traslados WHERE id=?", (id_registro,))

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

def seleccionar_todos(nombre_pestana, opciones):
    st.session_state[f"ms_del_{nombre_pestana}"] = opciones

# --- 5. INTERFAZ DE PESTAÑAS ---
nombres_pestanas = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
lista_tabs_mostrar = nombres_pestanas.copy()
if st.session_state.rol in ["administrador", "boss"]:
    lista_tabs_mostrar.append("Panel de Administrador")

tabs = st.tabs(lista_tabs_mostrar)

# Cargar el catálogo global de SAP para sincronizar el buscador dinámico
df_sap_global = cargar_todos_los_sap()

for i, nombre_pestana in enumerate(nombres_pestanas):
    with tabs[i]:
        df = cargar_datos(nombre_pestana)
        
        if st.session_state.rol == "moderador":
            df_editable = df[df['creado_por'] == st.session_state.usuario]
        else:
            df_editable = df
        
        total_registros = len(df)
        total_laminas = int(df['cantidad'].sum()) if total_registros > 0 else 0
        verificadas = int(df['verificado'].sum()) if total_registros > 0 else 0
        
        if nombre_pestana == "Códigos SAP":
            st.metric("📄 Total de Códigos Registrados", total_registros)
        else:
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("📄 Total de Registros", total_registros)
            col_m2.metric("📦 Unidades Totales", total_laminas)
            col_m3.metric("✅ Verificadas", f"{verificadas} de {total_registros}")
            
        st.write("---")
        
        if st.session_state.rol in ["administrador", "moderador", "boss"]:
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            
            with col_exp1:
                with st.expander("➕ Agregar traslado" if nombre_pestana != "Códigos SAP" else "➕ Agregar Código"):
                    if nombre_pestana != "Códigos SAP":
                        # BUSCADOR DINÁMICO SINCRONIZADO CON "CÓDIGOS SAP"
                        if not df_sap_global.empty:
                            lista_opciones_sap = df_sap_global.apply(lambda r: f"{r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                            
                            # CORREGIDO: Se cambió 'opciones=' por 'options=' para solucionar el crash de la app
                            articulo_sap_elegido = st.selectbox(
                                "🔍 Buscar Artículo SAP (Escribe palabras clave):", 
                                options=lista_opciones_sap,
                                key=f"sap_search_{nombre_pestana}"
                            )
                            
                            cod_detectado = articulo_sap_elegido.split(" - ")[0].strip()
                            desc_detectada = articulo_sap_elegido.split(" - ")[1].strip()
                            
                            st.text_input("Código Detectado", value=cod_detectado, disabled=True, key=f"disp_cod_{nombre_pestana}")
                            st.text_input("Descripción Detectada", value=desc_detectada, disabled=True, key=f"disp_desc_{nombre_pestana}")
                        else:
                            st.warning("⚠️ La pestaña Códigos SAP está vacía. Registra artículos allí primero.")
                            cod_detectado = st.text_input("Código Alfanumérico (Manual)", key=f"manual_cod_{nombre_pestana}")
                            desc_detectada = st.text_input("Descripción (Manual)", key=f"manual_desc_{nombre_pestana}")
                        
                        # Formulario simplificado donde solo pones la cantidad
                        with st.form(key=f"form_add_{nombre_pestana}", clear_on_submit=True):
                            nueva_cant = st.number_input("Cantidad", min_value=1, value=1, key=f"num_cant_{nombre_pestana}")
                            submit_add = st.form_submit_button("Agregar a la tabla", use_container_width=True, type="primary")
                            
                            if submit_add:
                                if cod_detectado != "":
                                    guardar_nuevo_registro(nombre_pestana, cod_detectado, desc_detectada, nueva_cant, st.session_state.usuario)
                                    st.session_state.mensaje_toast = "¡Registro añadido exitosamente!"
                                    st.rerun()
                    else:
                        with st.form(key=f"form_add_sap_maestro", clear_on_submit=True):
                            nuevo_codigo = st.text_input("Código Alfanumérico")
                            nueva_desc = st.text_input("Descripción")
                            submit_add = st.form_submit_button("Registrar en SAP", use_container_width=True)
                            if submit_add:
                                if nuevo_codigo != "":
                                    guardar_nuevo_registro("Códigos SAP", nuevo_codigo, nueva_desc, 1, st.session_state.usuario)
                                    st.session_state.mensaje_toast = "Código Maestro guardado con éxito."
                                    st.rerun()
                                else: st.error("El código es obligatorio.")
            
            with col_exp2:
                with st.expander("📝 Modificar artículo" if nombre_pestana != "Códigos SAP" else "📝 Modificar Código"):
                    if not df_editable.empty:
                        opciones_mod = df_editable.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                        articulo_mod = st.selectbox("Selecciona 1 registro a cambiar:", opciones_mod, key=f"sel_mod_{nombre_pestana}")
                        
                        id_real_mod = int(articulo_mod.split(" | ")[0].replace("ID: ", ""))
                        fila_actual = df_editable[df_editable['id'] == id_real_mod].iloc[0]
                        val_cant = int(fila_actual['cantidad'])
                        if val_cant < 1: val_cant = 1
                        
                        with st.form(key=f"form_edit_{nombre_pestana}_{id_real_mod}"):
                            m_cod = st.text_input("Editar Código", value=str(fila_actual['codigo_lamina']), key=f"inp_cod_{nombre_pestana}_{id_real_mod}")
                            m_desc = st.text_input("Editar Descripción", value=str(fila_actual['descripcion']), key=f"inp_desc_{nombre_pestana}_{id_real_mod}")
                            if nombre_pestana != "Códigos SAP":
                                m_cant = st.number_input("Editar Cantidad", min_value=1, value=val_cant, key=f"inp_cant_{nombre_pestana}_{id_real_mod}")
                            else: m_cant = val_cant
                                
                            submit_upd = st.form_submit_button("💾 Guardar Cambios", use_container_width=True)
                            if submit_upd:
                                actualizar_registro(id_real_mod, m_cod, m_desc, m_cant)
                                st.session_state.mensaje_toast = "Registro actualizado con éxito."
                                st.rerun()
                    else: st.info("No hay datos para modificar.")

            with col_exp3:
                with st.expander("🗑️ Eliminar artículos"):
                    if not df_editable.empty:
                        opciones_eliminar = df_editable.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                        st.button("☑️ Seleccionar Todos", key=f"btn_all_{nombre_pestana}", on_click=seleccionar_todos, args=(nombre_pestana, opciones_eliminar), use_container_width=True)
                        seleccion_eliminar = st.multiselect("Elige registros:", opciones_eliminar, key=f"ms_del_{nombre_pestana}")
                        if st.button("⚠️ Eliminar Seleccionados", key=f"btn_del_multi_{nombre_pestana}", type="primary", use_container_width=True):
                            if seleccion_eliminar:
                                for item in seleccion_eliminar:
                                    id_del = int(item.split(" | ")[0].replace("ID: ", ""))
                                    eliminar_registro(id_del)
                                st.session_state.mensaje_toast = f"Se eliminaron {len(seleccion_eliminar)} registro(s)."
                                st.rerun()
                            else: st.warning("Selecciona al menos un registro.")
                    else: st.info("No hay datos para eliminar.")
        
        st.write("#### 📊 Hoja de Trabajo")
        if not df.empty:
            df['verificado'] = df['verificado'].astype(bool)
            df['hora'] = pd.to_datetime(df['hora']).dt.strftime('%d/%m/%Y %H:%M')

        permitir_edicion = st.session_state.rol in ["administrador", "boss"]
        columnas_config = {
            "id": None, 
            "hora": st.column_config.TextColumn("📅 Fecha", disabled=True),
            "codigo_lamina": st.column_config.TextColumn("🏷️ Código", disabled=True),
            "descripcion": st.column_config.TextColumn("📝 Descripción", disabled=True),
            "cantidad": st.column_config.NumberColumn("🔢 Cantidad", disabled=True),
            "creado_por": st.column_config.TextColumn("👤 Autor", disabled=True),
            "verificado": st.column_config.CheckboxColumn("✅ ¿Verificado?", disabled=not permitir_edicion)
        }
        
        if nombre_pestana == "Códigos SAP":
            columnas_config["hora"] = None; columnas_config["verificado"] = None
            columnas_config["creado_por"] = None; columnas_config["cantidad"] = None
        
        edited_df = st.data_editor(
            df,
            column_config=columnas_config,
            hide_index=True,
            use_container_width=True,
            height=350,
            key=f"editor_sheets_{nombre_pestana}"
        )
        
        if permitir_edicion and not df.empty and nombre_pestana != "Códigos SAP":
            for index, row in edited_df.iterrows():
                if row['verificado'] != df.loc[index, 'verificado']:
                    actualizar_verificacion(row['id'], row['verificado'])
                    st.rerun()

        st.write("---")
        col_down1, col_down2 = st.columns(2)
        
        if st.session_state.rol in ["administrador", "boss"]:
            with col_down1:
                st.subheader("📥 Importar Excel")
                nombre_clave_sesion = f"uploader_key_{nombre_pestana}"
                if nombre_clave_sesion not in st.session_state: st.session_state[nombre_clave_sesion] = 0
                archivo_subido = st.file_uploader("Sube un archivo .xlsx", type=["xlsx"], key=f"up_{nombre_pestana}_{st.session_state[nombre_clave_sesion]}")
                if archivo_subido is not None:
                    try:
                        df_importado = pd.read_excel(archivo_subido)
                        df_importado.columns = [str(c).lower().strip() for c in df_importado.columns]
                        registros_nuevos = 0
                        for index, row in df_importado.iterrows():
                            cod = "N/A"
                            if 'codigo_lamina' in df_importado.columns: cod = row['codigo_lamina']
                            elif 'código' in df_importado.columns: cod = row['código']
                            elif 'codigo' in df_importado.columns: cod = row['codigo']
                            
                            desc = "N/A"
                            if 'descripcion' in df_importado.columns: desc = row['descripcion']
                            elif 'descripción' in df_importado.columns: desc = row['descripción']
                            
                            raw_cant = 1
                            if 'cantidad' in df_importado.columns: raw_cant = row['cantidad']
                            
                            cod = str(cod).strip() if pd.notna(cod) else "N/A"
                            desc = str(desc).strip() if pd.notna(desc) else "N/A"
                            try: cant = int(float(raw_cant))
                            except: cant = 1
                            
                            guardar_nuevo_registro(nombre_pestana, cod, desc, cant, st.session_state.usuario)
                            registros_nuevos += 1
                        st.session_state.mensaje_toast = f"¡Se importaron {registros_nuevos} registros!"
                        st.session_state[nombre_clave_sesion] += 1
                        st.rerun()
                    except: st.error("🚨 Archivo no legible.")

        with col_down2:
            st.subheader("📤 Exportar Reporte")
            df_para_exportar = df.drop(columns=['id']) if not df.empty else df
            excel_data = generar_excel_perfecto(df_para_exportar, nombre_pestana)
            st.download_button(
                label="📊 Descargar Excel", data=excel_data, 
                file_name=f"CLC_{nombre_pestana}_{datetime.date.today()}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                key=f"down_{nombre_pestana}", type="primary", use_container_width=True
            )

# --- 6. PANEL DE CONTROL DE USUARIOS ---
if st.session_state.rol in ["administrador", "boss"]:
    with tabs[4]: 
        st.header("⚙️ Configuración Global de Usuarios")
        df_usuarios = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios", conn)
        st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
        st.write("---")
        col_adm1, col_adm2 = st.columns(2)
        
        with col_adm1:
            with st.form("nuevo_usuario", clear_on_submit=True):
                st.subheader("➕ Crear / Modificar Usuario")
                n_cedula = st.text_input("Usuario")
                n_password = st.text_input("Nueva Contraseña")
                n_rol = st.selectbox("Asignar Rol", ["administrador", "moderador", "visualizador", "boss"])
                if st.form_submit_button("Guardar Usuario", use_container_width=True):
                    if n_cedula.strip() != "" and n_password.strip() != "":
                        c.execute("""INSERT INTO usuarios (cedula, password, rol) VALUES (?, ?, ?) 
                                     ON CONFLICT (cedula) DO UPDATE SET password = EXCLUDED.password, rol = EXCLUDED.rol""", 
                                  (n_cedula.strip(), n_password.strip(), n_rol))
                        st.session_state.mensaje_toast = f"Usuario {n_cedula} guardado."
                        st.rerun()
        
        with col_adm2:
            with st.form("eliminar_usuario"):
                st.subheader("🗑️ Eliminar Usuario")
                usuario_a_eliminar = st.selectbox("Selecciona el usuario a eliminar", df_usuarios['cedula'].tolist())
                if st.form_submit_button("Eliminar permanentemente", type="primary", use_container_width=True):
                    c.execute("DELETE FROM usuarios WHERE cedula=?", (usuario_a_eliminar,))
                    st.session_state.mensaje_toast = f"Usuario {usuario_a_eliminar} eliminado."
                    st.rerun()

conn.close()

