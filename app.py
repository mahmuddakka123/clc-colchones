import streamlit as st
import pandas as pd
import psycopg2
from sqlalchemy import create_engine
import datetime
import io
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="CLC Colchones - Gestión", page_icon="🛏️", layout="wide")

if 'mensaje_toast' in st.session_state:
    st.toast(st.session_state.mensaje_toast, icon="✅")
    del st.session_state.mensaje_toast
if 'error_toast' in st.session_state:
    st.toast(st.session_state.error_toast, icon="🚨")
    del st.session_state.error_toast

# --- 2. CONEXIÓN A BASE DE DATOS EN LA NUBE ---
try:
    DB_URL = st.secrets["DATABASE_URL"]
except Exception:
    st.error("🚨 Falta configurar DATABASE_URL en los Secrets de Streamlit.")
    st.stop()

# Motor para Pandas (Lecturas)
engine = create_engine(DB_URL)

# Conexión directa para Ejecuciones (Escrituras)
conn = psycopg2.connect(DB_URL)
conn.autocommit = True
c = conn.cursor()

# Crear tablas base en PostgreSQL
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

# --- MIGRACIÓN AUTOMÁTICA DE DATOS ---
c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='usuarios'")
columnas_usuarios = [col[0] for col in c.fetchall()]
if 'password' not in columnas_usuarios:
    c.execute("ALTER TABLE usuarios ADD COLUMN password TEXT DEFAULT '123456'")
    c.execute("UPDATE usuarios SET password = cedula") 

c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='traslados'")
columnas_traslados = [col[0] for col in c.fetchall()]
if 'creado_por' not in columnas_traslados:
    c.execute("ALTER TABLE traslados ADD COLUMN creado_por TEXT DEFAULT 'admin_legacy'")

# --- CREACIÓN DEL BOSS Y ADMIN DE RESPALDO ---
c.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('37322733', '12345678', 'boss') ON CONFLICT (cedula) DO NOTHING")
c.execute("INSERT INTO usuarios (cedula, password, rol) VALUES ('admin', 'admin', 'administrador') ON CONFLICT (cedula) DO NOTHING")

# --- 3. SISTEMA DE CONTROL DE SESIÓN (LOGIN) ---
if 'usuario' not in st.session_state:
    st.session_state.usuario = None
    st.session_state.rol = None

def login():
    st.title("🛏️ CLC Colchones - Iniciar Sesión")
    st.info("Ingresa tus credenciales de acceso.")
    
    # Uso de st.form para permitir inicio de sesión presionando "Enter"
    with st.form("login_form"):
        cedula = st.text_input("👤 Usuario (Cédula)")
        password = st.text_input("🔑 Contraseña", type="password")
        submit = st.form_submit_button("Ingresar", type="primary")
        
        if submit:
            if cedula != "" and password != "":
                c.execute("SELECT rol, password FROM usuarios WHERE cedula=%s", (cedula,))
                resultado = c.fetchone()
                if resultado:
                    rol_bd, password_bd = resultado
                    if password == password_bd:
                        st.session_state.usuario = cedula
                        st.session_state.rol = rol_bd
                        st.rerun()
                    else:
                        st.error("Contraseña incorrecta.")
                else:
                    st.error("Este usuario no existe en el sistema.")
            else:
                st.error("Por favor, llena ambos campos.")

if st.session_state.usuario is None:
    login()
    st.stop()

# --- 4. BARRA LATERAL (SIDEBAR) ---
st.sidebar.title(f"👤 Usuario:\n{st.session_state.usuario}")
st.sidebar.subheader(f"🛡️ Rol: {st.session_state.rol.capitalize()}")
if st.session_state.rol == "boss":
    st.sidebar.success("👑 Acceso de Nivel Máximo (Boss)")
    
if st.sidebar.button("🔒 Cerrar Sesión"):
    st.session_state.usuario = None
    st.session_state.rol = None
    st.rerun()

st.title("📦 Panel de Control CLC - Traslado de Láminas")
st.write("---")

# --- FUNCIONES AUXILIARES ---
def cargar_datos(pestana):
    return pd.read_sql_query(f"SELECT id, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por FROM traslados WHERE pestana='{pestana}'", engine)

def guardar_nuevo_registro(pestana, codigo, desc, cant, creador):
    hora_actual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO traslados (pestana, hora, codigo_lamina, descripcion, cantidad, verificado, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
              (pestana, hora_actual, codigo, desc, cant, False, creador))

def actualizar_verificacion(id_registro, estado):
    c.execute("UPDATE traslados SET verificado=%s WHERE id=%s", (estado, id_registro))

def actualizar_registro(id_registro, codigo, desc, cant):
    c.execute("UPDATE traslados SET codigo_lamina=%s, descripcion=%s, cantidad=%s WHERE id=%s", (codigo, desc, cant, id_registro))

def eliminar_registro(id_registro):
    c.execute("DELETE FROM traslados WHERE id=%s", (id_registro,))

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
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = borde_fino

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

# --- 5. INTERFAZ DE PESTAÑAS DE TRABAJO ---
nombres_pestanas = ["Minelba", "Kelvin", "Miguel", "Códigos SAP"]
lista_tabs_mostrar = nombres_pestanas.copy()
if st.session_state.rol in ["administrador", "boss"]:
    lista_tabs_mostrar.append("Panel de Administrador")

tabs = st.tabs(lista_tabs_mostrar)

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
        
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("📄 Total de Registros", total_registros)
        col_m2.metric("📦 Unidades Totales", total_laminas)
        col_m3.metric("✅ Láminas Verificadas", f"{verificadas} de {total_registros}")
        st.write("---")
        
        if st.session_state.rol in ["administrador", "moderador", "boss"]:
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            
            with col_exp1:
                with st.expander("➕ Agregar traslado"):
                    # st.form con clear_on_submit=True vacía los campos automáticamente al guardar
                    with st.form(key=f"form_add_{nombre_pestana}", clear_on_submit=True):
                        nuevo_codigo = st.text_input("Código Alfanumérico")
                        nueva_desc = st.text_input("Descripción")
                        nueva_cant = st.number_input("Cantidad", min_value=1, value=1)
                        submit_add = st.form_submit_button("Agregar a la tabla", use_container_width=True)
                        
                        if submit_add:
                            if nuevo_codigo != "":
                                guardar_nuevo_registro(nombre_pestana, nuevo_codigo, nueva_desc, nueva_cant, st.session_state.usuario)
                                st.session_state.mensaje_toast = "Registro añadido correctamente."
                                st.rerun()
                            else:
                                st.error("El código es obligatorio.")
            
            with col_exp2:
                with st.expander("📝 Modificar artículo"):
                    if not df_editable.empty:
                        opciones_mod = df_editable.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']}", axis=1).tolist()
                        articulo_mod = st.selectbox("Selecciona 1 registro a cambiar:", opciones_mod, key=f"sel_mod_{nombre_pestana}")
                        
                        id_real_mod = int(articulo_mod.split(" | ")[0].replace("ID: ", ""))
                        fila_actual = df_editable[df_editable['id'] == id_real_mod].iloc[0]
                        
                        # Corrección de StreamlitValueBelowMinError protegiendo el valor mínimo
                        val_cant = int(fila_actual['cantidad'])
                        if val_cant < 1:
                            val_cant = 1
                        
                        # st.form para garantizar el reinicio al guardar
                        with st.form(key=f"form_edit_{nombre_pestana}_{id_real_mod}"):
                            m_cod = st.text_input("Editar Código", value=str(fila_actual['codigo_lamina']))
                            m_desc = st.text_input("Editar Descripción", value=str(fila_actual['descripcion']))
                            m_cant = st.number_input("Editar Cantidad", min_value=1, value=val_cant)
                            
                            submit_upd = st.form_submit_button("💾 Guardar Cambios", use_container_width=True)
                            if submit_upd:
                                actualizar_registro(id_real_mod, m_cod, m_desc, m_cant)
                                st.session_state.mensaje_toast = "Registro actualizado con éxito."
                                st.rerun()
                    else:
                        st.info("No tienes registros propios para modificar." if st.session_state.rol == "moderador" else "No hay datos para modificar.")

            with col_exp3:
                with st.expander("🗑️ Eliminar artículos"):
                    if not df_editable.empty:
                        opciones_eliminar = df_editable.apply(lambda r: f"ID: {r['id']} | {r['codigo_lamina']} - {r['descripcion']} ({r['cantidad']})", axis=1).tolist()
                        seleccion_eliminar = st.multiselect("Elige 1 o más registros para borrar:", opciones_eliminar, key=f"ms_del_{nombre_pestana}")
                        
                        if st.button("⚠️ Eliminar Seleccionados", key=f"btn_del_multi_{nombre_pestana}", type="primary", use_container_width=True):
                            if seleccion_eliminar:
                                for item in seleccion_eliminar:
                                    id_del = int(item.split(" | ")[0].replace("ID: ", ""))
                                    eliminar_registro(id_del)
                                st.session_state.mensaje_toast = f"Se eliminaron {len(seleccion_eliminar)} registro(s)."
                                st.rerun()
                            else:
                                st.warning("Selecciona al menos un registro.")
                    else:
                        st.info("No tienes registros propios para eliminar." if st.session_state.rol == "moderador" else "No hay datos para eliminar.")
        
        st.write("#### 📊 Hoja de Trabajo")
        
        if not df.empty:
            df['verificado'] = df['verificado'].astype(bool)
            df['hora'] = pd.to_datetime(df['hora']).dt.strftime('%d/%m/%Y %H:%M')

        permitir_edicion = st.session_state.rol in ["administrador", "boss"]
        
        edited_df = st.data_editor(
            df,
            column_config={
                "id": None, 
                "hora": st.column_config.TextColumn("📅 Fecha", width="medium", disabled=True),
                "codigo_lamina": st.column_config.TextColumn("🏷️ Código", width="medium", disabled=True),
                "descripcion": st.column_config.TextColumn("📝 Descripción", width="large", disabled=True),
                "cantidad": st.column_config.NumberColumn("🔢 Cantidad", disabled=True),
                "creado_por": st.column_config.TextColumn("👤 Autor", disabled=True),
                "verificado": st.column_config.CheckboxColumn("✅ ¿Verificado?", disabled=not permitir_edicion)
            },
            hide_index=True,
            use_container_width=True,
            height=400,
            key=f"editor_sheets_{nombre_pestana}"
        )
        
        if permitir_edicion and not df.empty:
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
                if nombre_clave_sesion not in st.session_state:
                    st.session_state[nombre_clave_sesion] = 0
                
                archivo_subido = st.file_uploader("Sube un archivo .xlsx", type=["xlsx"], key=f"up_{nombre_pestana}_{st.session_state[nombre_clave_sesion]}")
                
                if archivo_subido is not None:
                    # Sistema de adaptación automática de Excel
                    try:
                        df_importado = pd.read_excel(archivo_subido)
                        # Limpiar nombres de columnas para facilitar la búsqueda en minúsculas
                        df_importado.columns = [str(c).lower().strip() for c in df_importado.columns]
                        
                        for index, row in df_importado.iterrows():
                            # 1. Adaptar Código (Busca por nombre o toma la columna 1)
                            cod = "N/A"
                            if 'codigo_lamina' in df_importado.columns: cod = row['codigo_lamina']
                            elif 'código' in df_importado.columns: cod = row['código']
                            elif 'codigo' in df_importado.columns: cod = row['codigo']
                            elif len(df_importado.columns) > 0: cod = row.iloc[0]
                            
                            # 2. Adaptar Descripción (Busca por nombre o toma la columna 2)
                            desc = "N/A"
                            if 'descripcion' in df_importado.columns: desc = row['descripcion']
                            elif 'descripción' in df_importado.columns: desc = row['descripción']
                            elif len(df_importado.columns) > 1: desc = row.iloc[1]
                            
                            # 3. Adaptar Cantidad (Busca por nombre o toma la columna 3)
                            raw_cant = 1
                            if 'cantidad' in df_importado.columns: raw_cant = row['cantidad']
                            elif 'cant' in df_importado.columns: raw_cant = row['cant']
                            elif len(df_importado.columns) > 2: raw_cant = row.iloc[2]
                            
                            # Limpieza final de datos para evitar errores en PostgreSQL
                            cod = str(cod).strip() if pd.notna(cod) else "N/A"
                            desc = str(desc).strip() if pd.notna(desc) else "N/A"
                            
                            try:
                                # Convertimos a float primero por si el Excel exportó números como "1.0"
                                cant = int(float(raw_cant)) 
                                if cant < 1: cant = 1
                            except (ValueError, TypeError):
                                cant = 1 # Si había texto o celdas vacías en la cantidad, pone 1 por seguridad
                            
                            # Guarda el registro ya reparado y adaptado
                            guardar_nuevo_registro(nombre_pestana, cod, desc, cant, st.session_state.usuario)
                        
                        st.session_state.mensaje_toast = "¡Archivo adaptado e importado con éxito!"
                        st.session_state[nombre_clave_sesion] += 1
                        st.rerun()
                        
                    except Exception as e:
                        st.error("🚨 El archivo está tan dañado que no se pudo leer. Verifica que sea un Excel válido (.xlsx).")

        with col_down2:
            st.subheader("📤 Exportar Reporte")
            excel_data = generar_excel_perfecto(df.drop(columns=['id']), nombre_pestana)
            st.download_button(
                label="📊 Descargar Excel", 
                data=excel_data, 
                file_name=f"CLC_{nombre_pestana}_{datetime.date.today()}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                key=f"down_{nombre_pestana}",
                type="primary"
            )

# --- 6. PANEL DE CONTROL DE USUARIOS ---
if st.session_state.rol in ["administrador", "boss"]:
    with tabs[4]: 
        st.header("⚙️ Configuración Global de Usuarios")
        
        if st.session_state.rol == "boss":
            df_usuarios = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios", engine)
        else:
            df_usuarios = pd.read_sql_query("SELECT cedula, rol, password FROM usuarios WHERE rol != 'boss'", engine)
        
        st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
        st.write("---")
        
        col_adm1, col_adm2 = st.columns(2)
        
        with col_adm1:
            with st.form("nuevo_usuario", clear_on_submit=True):
                st.subheader("➕ Crear / Modificar Usuario")
                n_cedula = st.text_input("Usuario (Cédula)")
                n_password = st.text_input("Nueva Contraseña")
                
                opciones_rol = ["administrador", "moderador", "visualizador"]
                if st.session_state.rol == "boss":
                    opciones_rol.append("boss")
                    
                n_rol = st.selectbox("Asignar Rol", opciones_rol)
                st.info("💡 Si la cédula ya existe, al guardar se actualizará su contraseña y rol.")
                
                if st.form_submit_button("Guardar Usuario"):
                    if n_cedula.strip() != "" and n_password.strip() != "":
                        c.execute("SELECT rol FROM usuarios WHERE cedula=%s", (n_cedula.strip(),))
                        rol_existente = c.fetchone()
                        
                        if rol_existente and rol_existente[0] == "boss" and st.session_state.rol != "boss":
                            st.session_state.error_toast = "❌ Acceso denegado: No tienes permisos para modificar cuentas Boss."
                            st.rerun()
                        else:
                            c.execute("""
                                INSERT INTO usuarios (cedula, password, rol) 
                                VALUES (%s, %s, %s) 
                                ON CONFLICT (cedula) 
                                DO UPDATE SET password = EXCLUDED.password, rol = EXCLUDED.rol
                            """, (n_cedula.strip(), n_password.strip(), n_rol))
                            st.session_state.mensaje_toast = f"Usuario {n_cedula} configurado con éxito."
                            st.rerun()
                    else:
                        st.error("Debes llenar la cédula y la contraseña.")
        
        with col_adm2:
            with st.form("eliminar_usuario"):
                st.subheader("🗑️ Eliminar Usuario")
                lista_usuarios = df_usuarios['cedula'].tolist()
                usuario_a_eliminar = st.selectbox("Selecciona el usuario a eliminar", lista_usuarios)
                
                if st.form_submit_button("Eliminar permanentemente", type="primary"):
                    c.execute("DELETE FROM usuarios WHERE cedula=%s", (usuario_a_eliminar,))
                    st.session_state.mensaje_toast = f"Usuario {usuario_a_eliminar} eliminado."
                    
                    if usuario_a_eliminar == st.session_state.usuario:
                        st.session_state.usuario = None
                        st.session_state.rol = None
                    st.rerun()

conn.close()
