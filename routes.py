# turno/app/routes.py
from datetime import date
from calendar import monthrange
from zoneinfo import ZoneInfo
from flask import current_app
from flask import make_response, jsonify
from xhtml2pdf import pisa
from io import BytesIO
from calendar import monthrange
import calendar as cal_module
import os
import requests
from werkzeug.utils import secure_filename
from datetime import timedelta

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash, jsonify, current_app
)
from flask_mail import Message
from app import mysql, bcrypt, mail
from app.models import (
    obtener_hora_timeapi,
    get_user_by_username,
    tiene_salida_laboral_hoy,
    record_timeout_laboral,
    record_timein,
    record_timeout,
    record_timein_laboral,
    tiene_entrada_laboral_hoy,
    tiene_entrada_abierta_presencia,
    tiene_salida_comida_abierta,
    tiene_vuelta_comida_hoy,
    insert_user,
    insert_persona,
    get_persona,
    get_vacaciones,
    insert_vacaciones,
    delete_vacaciones,
    get_persona_detail,
    get_personas_by_department,
    get_attendance,
    get_vacaciones_from_date
)
from functools import wraps


main = Blueprint('main', __name__, template_folder='templates')
# Añade esto justo después de definir el Blueprint (al principio de routes.py)
@main.context_processor
def inject_sidebar_vars():
    if 'user_id' not in session:
        return {}
    
    user_foto = session.get('foto', None)
    
    # Calcular avatar aquí directamente
    if user_foto:
        avatar = url_for('static', filename=user_foto)
    else:
        avatar = url_for('static', filename='img/user.png')

    dep   = session.get('departamento', '').lower()
    role  = session.get('role', 1)

    if role == 0 and dep in ['financiero', 'melia']:
        rol_label = 'Supervisora'
        rol_icon  = 'bi-star-fill'
        rol_color = 'background:#fdf4ff; color:#7e22ce; border-color:#d8b4fe;'
    elif role == 0:
        rol_label = 'Admin'
        rol_icon  = 'bi-shield-check-fill'
        rol_color = 'background:#dbeafe; color:#1e40af; border-color:#93c5fd;'
    else:
        rol_label = 'Empleado'
        rol_icon  = 'bi-person-check-fill'
        rol_color = 'background:#eff6ff; color:#2563eb; border-color:#bfdbfe;'

    return dict(
        role         = role,
        user         = session.get('username', ''),
        departamento = session.get('departamento', ''),
        dep          = dep,
        rol_label    = rol_label,
        rol_icon     = rol_icon,
        rol_color    = rol_color,
        user_foto    = user_foto,
        avatar       = avatar,       # ← ya calculado aquí
    )


UPLOAD_FOLDER      = os.path.join('app', 'static', 'img', 'usuarios')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

MESES_ES = {
    1:'Enero', 2:'Febrero', 3:'Marzo', 4:'Abril',
    5:'Mayo', 6:'Junio', 7:'Julio', 8:'Agosto',
    9:'Septiembre', 10:'Octubre', 11:'Noviembre', 12:'Diciembre'
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


#------------------------------Calcular dias habiles entre dos fechas---------------------------------
from datetime import timedelta


from datetime import date, datetime, time, timedelta


def calcular_tiempo_laborable(inicio, fin, feriados_set):
  if not inicio or not fin or fin <= inicio:
    return '-'

  # Configuración de jornada laboral estándar (09:00 a 18:00 = 9 h diarias)
  HORA_INICIO_JORNADA = time(9, 0)
  HORA_FIN_JORNADA = time(18, 0)
  HORAS_POR_DIA = 9.0  # Horas que componen 1 día completo

  total_horas = 0.0
  curr_date = inicio.date()
  end_date = fin.date()

  while curr_date <= end_date:
    es_fin_de_semana = curr_date.weekday() >= 5
    es_feriado = curr_date.strftime('%Y-%m-%d') in feriados_set

    # Si es día laboral, calculamos las horas dentro del horario de trabajo
    if not es_fin_de_semana and not es_feriado:
      jornada_inicio = datetime.combine(curr_date, HORA_INICIO_JORNADA)
      jornada_fin = datetime.combine(curr_date, HORA_FIN_JORNADA)

      # Tramo coincidente entre la solicitud y la jornada laboral
      tramo_inicio = max(inicio, jornada_inicio)
      tramo_fin = min(fin, jornada_fin)

      if tramo_fin > tramo_inicio:
        horas_dia = (tramo_fin - tramo_inicio).total_seconds() / 3600.0
        total_horas += horas_dia

    curr_date += timedelta(days=1)

  if total_horas <= 0:
    return '0 h'

  # Convertir el total de horas a Días completados y Horas restantes
  dias = int(total_horas // HORAS_POR_DIA)
  horas_restantes = round(total_horas % HORAS_POR_DIA)

  if horas_restantes >= int(HORAS_POR_DIA):
    dias += 1
    horas_restantes = 0

  if dias > 0 and horas_restantes > 0:
    return f"{dias} día{'s' if dias != 1 else ''} y {horas_restantes} h"
  elif dias > 0:
    return f"{dias} día{'s' if dias != 1 else ''}"
  else:
    return f'{horas_restantes} h'
  #-----------------------------------------------------------------------------------------------------
HORAS_JORNADA_DIARIA = 8.0  # O 9.0 según el horario estándar de la empresa


def obtener_resumen_vacaciones(cur, user_id, anio, feriados_set):
  # 1. Obtener cupo total asignado
  cur.execute(
      """
        SELECT dias_totales 
        FROM vacaciones_cupo 
        WHERE iduser = %s AND anio = %s
    """,
      (user_id, anio),
  )
  row_cupo = cur.fetchone()
  dias_totales = float(row_cupo[0]) if row_cupo else 22.0

  # 2. Obtener solicitudes (Pendientes y Aprobadas)
  cur.execute(
      """
        SELECT vacacionesin, vacacionesout, estado 
        FROM vacaciones 
        WHERE iduser = %s 
          AND YEAR(vacacionesin) = %s 
          AND estado IN ('Pendiente', 'Aprobado')
    """,
      (user_id, anio),
  )
  solicitudes = cur.fetchall()

  horas_aprobadas = 0.0
  horas_pendientes = 0.0

  for v_in, v_out, estado in solicitudes:
    if v_in and v_out:
      # Calcular horas laborables exactas en días hábiles
      horas_solicitud = 0.0
      curr_date = v_in.date()
      end_date = v_out.date()

      while curr_date <= end_date:
        es_fin_semana = curr_date.weekday() >= 5
        es_feriado = curr_date.strftime('%Y-%m-%d') in feriados_set

        if not es_fin_semana and not es_feriado:
          if curr_date == v_in.date() and curr_date == v_out.date():
            # Mismo día: diferencia exacta de horas
            h = (v_out - v_in).total_seconds() / 3600.0
            horas_solicitud += min(h, HORAS_JORNADA_DIARIA)
          elif curr_date == v_out.date():
            # Último día parcial (ej. hasta las 12:00 desde las 09:00 = 3h)
            h_fin = v_out.hour + (v_out.minute / 60.0)
            h_inicio_jornada = 9.0  # Hora normal de entrada
            horas_solicitud += max(
                0.0, min(h_fin - h_inicio_jornada, HORAS_JORNADA_DIARIA)
            )
          else:
            # Día completo
            horas_solicitud += HORAS_JORNADA_DIARIA

        curr_date += timedelta(days=1)

      if estado == 'Aprobado':
        horas_aprobadas += horas_solicitud
      elif estado == 'Pendiente':
        horas_pendientes += horas_solicitud

  # Convertir horas a días
  dias_aprobados = round(horas_aprobadas / HORAS_JORNADA_DIARIA, 1)
  dias_pendientes = round(horas_pendientes / HORAS_JORNADA_DIARIA, 1)
  dias_disponibles = round(
      dias_totales - dias_aprobados - dias_pendientes, 1
  )

  if dias_disponibles < 0:
    dias_disponibles = 0.0

  return {
      'totales': (
          int(dias_totales)
          if dias_totales.is_integer()
          else round(dias_totales, 1)
      ),
      'aprobados': (
          int(dias_aprobados)
          if dias_aprobados.is_integer()
          else round(dias_aprobados, 1)
      ),
      'pendientes': (
          int(dias_pendientes)
          if dias_pendientes.is_integer()
          else round(dias_pendientes, 1)
      ),
      'disponibles': (
          int(dias_disponibles)
          if dias_disponibles.is_integer()
          else round(dias_disponibles, 1)
      ),
  }
@main.app_context_processor
def inject_year():
    return {'current_year': date.today().year}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated

@main.route('/')
def index():
    
    return redirect(url_for('main.login'))






#Test mail-------------------------------------------------------------------------
@main.route('/test-email')
@login_required
def test_email():
    destinatario = request.args.get('email')

    if not destinatario:
        return jsonify({
            'success': False,
            'error': 'Debes indicar un email de destino en la URL. Ejemplo: /test-email?email=tu_correo@ejemplo.com'
        }), 400

    try:
        msg = Message(
            subject="Prueba de configuración - TurnoApp",
            recipients=[destinatario],
            body="¡Hola!\n\nEste es un correo de prueba enviado desde TurnoApp."
        )
        mail.send(msg)
        return jsonify({
            'success': True,
            'msg': f'Correo enviado correctamente a {destinatario}'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'server_detectado': current_app.config.get('MAIL_SERVER'),
            'puerto_detectado': current_app.config.get('MAIL_PORT'),
            'usuario_detectado': current_app.config.get('MAIL_USERNAME'),
            'error': f'Error al enviar el correo: {str(e)}'
        }), 500
#Fin test mail

@main.route('/enviar-confirmacion')
def enviar_confirmacion():
    # Datos de ejemplo o provenientes de la BD
    datos_turno = {
        'nombre': 'Juan Pérez',
        'servicio': 'Consulta General',
        'fecha': '15/10/2026',
        'hora': '10:30 AM',
        'codigo': 'TRN-8492',
    }

    msg = Message(
        subject=f"Confirmación de Turno - {datos_turno['codigo']}",
        recipients=['ariel-c@resorts-advantage.com'],
    )

    # Renderizamos la plantilla pasando los datos al contexto Jinja2
    msg.html = render_template(
        'email_turno.html',
        nombre=datos_turno['nombre'],
        servicio=datos_turno['servicio'],
        fecha=datos_turno['fecha'],
        hora=datos_turno['hora'],
        codigo_turno=datos_turno['codigo'],
        url_app='http://192.168.242.7/mis-turnos',
    )

    mail.send(msg)
    return 'Correo enviado con éxito'




@main.route('/hora-api', methods=['GET'])
def hora_api():
    try:
        ahora = datetime.now(
            ZoneInfo("Europe/Madrid")
        )

        fecha = ahora.strftime("%Y-%m-%d")
        hora = ahora.strftime("%H:%M:%S")

        current_app.logger.info(
            "Hora del servidor: %s %s",
            fecha,
            hora
        )

        return jsonify({
            "hora": hora,
            "fecha": fecha,
            "zona_horaria": "Europe/Madrid"
        })

    except (ValueError, TypeError) as error:
        current_app.logger.error(
            "Error obteniendo la hora del servidor: %s",
            error
        )

        return jsonify({
            "error": "No se pudo obtener la hora del servidor"
        }), 500
@main.route('/login', methods=['GET', 'POST'])
def login():
  error = None
  if request.method == 'POST':
    username = request.form['user']
    password = request.form['password']

    cur = mysql.connection.cursor()
    user = get_user_by_username(cur, username)

    if user and bcrypt.check_password_hash(user[2], password):
      session.clear()
      session['user_id'] = user[0]
      session['username'] = user[1]
      session['role'] = int(user[3])
      cur.execute("SELECT departamento FROM personas WHERE iduser = %s", (user[0],))
      dep_row = cur.fetchone()
      user_dep = dep_row[0].lower() if (dep_row and dep_row[0]) else ''

      # Consultar si el usuario está asignado en la tabla Supervisoras
      cur.execute(
          'SELECT COUNT(*) FROM Supervisoras WHERE UserID = %s', (user[0],)
      )
      tiene_asignacion = cur.fetchone()[0] > 0
      cur.close()

      # Permite ver la gestión si es rol 0 O si está asignado en Supervisoras
      session['puede_ver_gestion'] = (int(user[3]) == 0) or tiene_asignacion or (user_dep == 'it')

      return redirect(url_for('main.dashboard'))
    else:
      cur.close()
      error = 'Usuario o contraseña incorrectos.'

  return render_template('login.html', error=error, titulo='Iniciar Sesión')


@main.route('/dashboard')
@login_required
def dashboard():
    cur = mysql.connection.cursor()
    fecha_actual = date.today()
    hoy = fecha_actual.strftime('%Y-%m-%d')
    user_id = session.get('user_id')
    user_role = session.get('role')

    tiempos_hoy = get_attendance(cur, user_id, hoy)

    anio = fecha_actual.year
    cur.execute("""
        SELECT vacacionesin, vacacionesout, idvac
        FROM vacaciones
        WHERE iduser = %s
          AND YEAR(vacacionesin) = %s
        ORDER BY vacacionesin
    """, (user_id, anio))
    vacaciones_anio = cur.fetchall()

    cur.execute("""
        SELECT u.foto, p.departamento
        FROM `user` u
        JOIN personas p ON u.iduser = p.iduser
        WHERE u.iduser = %s
    """, (user_id,))
    row = cur.fetchone()
    user_foto = row[0].strip().replace('\\', '/') if row and row[0] else None
    user_departamento = row[1] if row and row[1] else ''

    # ── 1. CONSULTAR DEPARTAMENTOS ASIGNADOS A LA SUPERVISORA ──
    cur.execute("SELECT departamento FROM Supervisoras WHERE UserID = %s", (user_id,))
    deptos_registrados = [r[0] for r in cur.fetchall() if r[0]]

    es_supervisora = False
    if (user_role is not None and int(user_role) == 0) or deptos_registrados:
        es_supervisora = True

    # ── 2. MONITOR DE ASISTENCIA DEL EQUIPO (SOLO SU DEPARTAMENTO) ──
    equipo_asistencia = []
    if es_supervisora:
        ver_todos = ('TODOS' in deptos_registrados) or (user_departamento.lower() == 'it')

        if ver_todos:
            # IT o Admin ver_todos
            cur.execute("""
                SELECT u.iduser, p.nombre, p.apellido, p.departamento, u.foto
                FROM `user` u
                JOIN personas p ON u.iduser = p.iduser
                ORDER BY CASE WHEN u.iduser = %s THEN 0 ELSE 1 END, p.nombre, p.apellido
            """, (user_id,))
        elif deptos_registrados:
            # Filtrar por departamentos asignados en la tabla Supervisoras
            cur.execute("""
                SELECT DISTINCT u.iduser, p.nombre, p.apellido, p.departamento, u.foto
                FROM `user` u
                JOIN personas p ON u.iduser = p.iduser
                JOIN Supervisoras s ON p.departamento = s.departamento
                WHERE s.UserID = %s OR u.iduser = %s
                ORDER BY CASE WHEN u.iduser = %s THEN 0 ELSE 1 END, p.nombre, p.apellido
            """, (user_id, user_id, user_id))
        else:
            # Fallback: Filtrar por su propio departamento en personas
            cur.execute("""
                SELECT u.iduser, p.nombre, p.apellido, p.departamento, u.foto
                FROM `user` u
                JOIN personas p ON u.iduser = p.iduser
                WHERE p.departamento = %s OR u.iduser = %s
                ORDER BY CASE WHEN u.iduser = %s THEN 0 ELSE 1 END, p.nombre, p.apellido
            """, (user_departamento, user_id, user_id))

        emps_rows = cur.fetchall()

        for emp in emps_rows:
            emp_id = emp[0]
            emp_nombre = emp[1] or ''
            emp_apellido = emp[2] or ''
            emp_depto = emp[3] or ''
            emp_foto = emp[4].strip().replace('\\', '/') if emp[4] else None
            es_tu = (emp_id == user_id)

            # Entrada Laboral del día
            cur.execute("""
                SELECT timein 
                FROM turn_in_laboral 
                WHERE iduser = %s AND DATE(timein) = CURDATE() 
                ORDER BY timein ASC LIMIT 1
            """, (emp_id,))
            r_in = cur.fetchone()
            hora_in = r_in[0].strftime('%H:%M') if r_in and r_in[0] else None

            # Salida Laboral del día
            cur.execute("""
                SELECT timeout 
                FROM turn_out_laboral 
                WHERE iduser = %s AND DATE(timeout) = CURDATE() 
                ORDER BY timeout DESC LIMIT 1
            """, (emp_id,))
            r_out = cur.fetchone()
            hora_out = r_out[0].strftime('%H:%M') if r_out and r_out[0] else None

            # Pausa Almuerzo del día
            cur.execute("""
                SELECT salida, entrada 
                FROM turn_lunch 
                WHERE iduser = %s AND DATE(salida) = CURDATE() 
                ORDER BY salida DESC LIMIT 1
            """, (emp_id,))
            r_lunch = cur.fetchone()

            lunch_salida = r_lunch[0].strftime('%H:%M') if r_lunch and r_lunch[0] else None
            lunch_entrada = r_lunch[1].strftime('%H:%M') if r_lunch and r_lunch[1] else None

            if lunch_salida and lunch_entrada:
                almuerzo_txt = f"{lunch_salida} ➔ {lunch_entrada}"
            elif lunch_salida:
                almuerzo_txt = f"{lunch_salida} ➔ En curso"
            else:
                almuerzo_txt = "—"

            if hora_out:
                estado_nom = "Jornada Finalizada"
                estado_clase = "chip-gray"
                estado_icono = "bi-stop-circle-fill"
            elif lunch_salida and not lunch_entrada:
                estado_nom = "En Almuerzo"
                estado_clase = "chip-amber"
                estado_icono = "bi-cup-hot-fill"
            elif hora_in:
                estado_nom = "En Jornada"
                estado_clase = "chip-green"
                estado_icono = "bi-check-circle-fill"
            else:
                estado_nom = "Sin Fichar"
                estado_clase = "chip-red"
                estado_icono = "bi-x-circle-fill"

            equipo_asistencia.append({
                'iduser': emp_id,
                'nombre_completo': f"{emp_nombre} {emp_apellido}".strip(),
                'departamento': emp_depto,
                'foto': emp_foto,
                'es_tu': es_tu,
                'hora_entrada': hora_in or '—',
                'hora_salida': hora_out or '—',
                'almuerzo_txt': almuerzo_txt,
                'estado_nom': estado_nom,
                'estado_clase': estado_clase,
                'estado_icono': estado_icono
            })

    # ── 3. PRÓXIMOS FESTIVOS ──
    cur.execute("""
        SELECT fecha, descripcion
        FROM feriados
        WHERE fecha >= CURDATE()
        ORDER BY fecha ASC
        LIMIT 3
    """)
    feriados_rows = cur.fetchall()

    DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    MESES_NOMBRE = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

    proximos_feriados = []
    for r in feriados_rows:
        f_val = r[0]
        desc = r[1] if (len(r) > 1 and r[1]) else 'Día Festivo'

        if isinstance(f_val, datetime):
            f_date = f_val.date()
        elif isinstance(f_val, date):
            f_date = f_val
        else:
            f_date = datetime.strptime(str(f_val), '%Y-%m-%d').date()

        dia_semana = DIAS_SEMANA[f_date.weekday()]
        mes_nom = MESES_NOMBRE[f_date.month]

        proximos_feriados.append({
            'titulo': desc,
            'fecha_larga': f'{f_date.day} de {mes_nom} ({dia_semana})',
            'fecha_corta': f_date.strftime('%d/%m/%Y'),
        })

    cur.execute("""
        SELECT salida, entrada
        FROM turn_lunch
        WHERE iduser = %s AND DATE(salida) = CURDATE()
        ORDER BY salida DESC LIMIT 1
    """, (user_id,))
    lunch_hoy = cur.fetchone()

    cur.execute("""
        SELECT timein
        FROM turn_in_laboral
        WHERE iduser = %s AND DATE(timein) = CURDATE()
        ORDER BY timein ASC
        LIMIT 1
    """, (user_id,))
    row_laboral = cur.fetchone()
    entrada_laboral_hoy = row_laboral[0] if row_laboral else None

    cur.close()
    return render_template(
        'dashboard.html',
        user=session.get('username'),
        role=session.get('role'),
        tiempos_hoy=tiempos_hoy,
        vacaciones_anio=vacaciones_anio,
        user_foto=user_foto,
        proximos_feriados=proximos_feriados,
        lunch_hoy=lunch_hoy,
        entrada_laboral_hoy=entrada_laboral_hoy,
        departamento=user_departamento,
        current_year=anio,
        es_supervisora=es_supervisora,
        equipo_asistencia=equipo_asistencia,
    )
# ══════════════════════════════════════════════════════
#  Dashboard IT — Solo para usuarios del departamento IT (roles 0 )
# ══════════════════════════════════════════════════════
from datetime import datetime

@main.route('/dashboardit')
@login_required
def dashboardit():
    user         = session.get('username')
    role         = session.get('role')
    departamento = session.get('departamento', '')
    dep          = departamento.lower()
    user_foto    = session.get('foto', None)

    if role == 0 and dep in ['financiero', 'melia']:
        rol_label = 'Supervisora'
    elif role == 0:
        rol_label = 'Admin'
    else:
        rol_label = 'Empleado'

    # ══ RESUMEN EQUIPOS (FUNCIONA) ══
    cur_eq = mysql.connection.cursor()
    cur_eq.execute("""
        SELECT nombre_equipo as nombre, usuario, numero_serie as ip 
        FROM equipos ORDER BY fecha_registro DESC LIMIT 3
    """)
    columns_eq = [col[0] for col in cur_eq.description]
    equipos_resumen = [dict(zip(columns_eq, row)) for row in cur_eq.fetchall()]
    cur_eq.execute("SELECT COUNT(*) FROM equipos")
    total_equipos = cur_eq.fetchone()[0]

    # ══ RESUMEN SERVIDORES (NUEVO - IGUAL QUE EQUIPOS) ══
    try:
        cur_sv = mysql.connection.cursor()
        cur_sv.execute("""
            SELECT server_name as nombre, hostname, ip_address 
            FROM servidores ORDER BY creado_en DESC LIMIT 3
        """)
        columns_sv = [col[0] for col in cur_sv.description]
        servidores_resumen = [dict(zip(columns_sv, row)) for row in cur_sv.fetchall()]
        cur_sv.execute("SELECT COUNT(*) FROM servidores")
        total_servidores = cur_sv.fetchone()[0]
        cur_sv.close()
    except Exception as e:
        print(f"Servidores error: {e}")
        servidores_resumen = []
        total_servidores = 0

    # ══ BACKUPS (FUNCIONA) ══
    try:
        cur_bu = mysql.connection.cursor()
        cur_bu.execute("SELECT MAX(fecha) as ultimo_backup FROM backups")
        ultimo_backup_row = cur_bu.fetchone()
        ultimo_backup = ultimo_backup_row[0] if ultimo_backup_row else None
        
        cur_bu.execute("SELECT COUNT(*) FROM backups")
        total_backups = cur_bu.fetchone()[0]
        
        cur_bu.execute("SELECT COUNT(*) FROM backups WHERE estado='OK'")
        backup_exito = cur_bu.fetchone()[0]
        backup_fallos = total_backups - backup_exito
        backup_exito_pct = round((backup_exito / total_backups * 100) if total_backups else 0)
        
        cur_bu.execute("""
            SELECT fecha, servidor, estado 
            FROM backups ORDER BY fecha DESC LIMIT 3
        """)
        columns_bu = [col[0] for col in cur_bu.description]
        backups_recientes = [dict(zip(columns_bu, row)) for row in cur_bu.fetchall()]
        cur_bu.close()
    except Exception as e:
        print(f"Backups error: {e}")
        ultimo_backup = None
        total_backups = 0
        backup_exito_pct = 0
        backup_fallos = 0
        backups_recientes = []
        # ══ TICKETS ══
    try:
        cur_tk = mysql.connection.cursor()
        cur_tk.execute("SELECT titulo, departamento, usuario, estado FROM tickets ORDER BY fecha_apertura DESC LIMIT 3")
        columns_tk = [col[0] for col in cur_tk.description]
        tickets_resumen = [dict(zip(columns_tk, row)) for row in cur_tk.fetchall()]
        cur_tk.execute("SELECT COUNT(*) FROM tickets WHERE estado='Abierto'")
        tickets_abiertos = cur_tk.fetchone()[0]
        cur_tk.close()
    except:
        tickets_resumen = []
        tickets_abiertos = 0


    return render_template('dashboardit.html',
        user              = user,
        role              = role,
        departamento      = departamento,
        dep               = dep,
        rol_label         = rol_label,
        user_foto         = user_foto,
        current_year      = datetime.now().year,
        equipos_resumen   = equipos_resumen,
        total_equipos     = total_equipos,
        servidores_resumen = servidores_resumen,
        total_servidores  = total_servidores,
        ultimo_backup     = ultimo_backup,
        total_backups     = total_backups,
        backup_exito_pct  = backup_exito_pct,
        backup_fallos     = backup_fallos,
        backups_recientes = backups_recientes,
        tickets_resumen     =tickets_resumen,
        tickets_abiertos    =tickets_abiertos,

    )
# ══════════════════════════════════════════════════════
#   tickets
# ══════════════════════════════════════════════════════
@main.route('/tickets')
@login_required
def tickets():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tickets ORDER BY fecha_apertura DESC")
        columns = [col[0] for col in cur.description]
        tickets = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE estado='Abierto'")
        abiertos = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE estado='En Progreso'")
        progreso = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE estado='Cerrado'")
        cerrados = cur.fetchone()[0]
        cur.close()
        return render_template('tickets.html', tickets=tickets, abiertos=abiertos, progreso=progreso, cerrados=cerrados)
    except:
        return render_template('tickets.html', tickets=[], abiertos=0, progreso=0, cerrados=0)

@main.route('/tickets/add', methods=['POST'])
@login_required
def add_ticket():
    data = request.json
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO tickets (titulo, departamento, usuario, descripcion, prioridad, estado)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data['titulo'], data['departamento'], data['usuario'],
            data['descripcion'], data['prioridad'], data['estado']
        ))
        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@main.route('/tickets/update/<int:id>', methods=['POST'])
@login_required
def update_ticket(id):
    data = request.json
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE tickets SET titulo=%s, departamento=%s, usuario=%s,
            descripcion=%s, prioridad=%s, estado=%s
            WHERE id=%s
        """, (
            data['titulo'], data['departamento'], data['usuario'],
            data['descripcion'], data['prioridad'], data['estado'], id
        ))
        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@main.route('/tickets/delete/<int:id>', methods=['POST'])
@login_required
def delete_ticket(id):
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM tickets WHERE id=%s", (id,))
        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ══════════════════════════════════════════════════════
#  REGISTRAR backups
# ══════════════════════════════════════════════════════
@main.route('/it/backups', methods=['GET', 'POST'])
@login_required
def backups():
    role         = session.get('role')
    departamento = session.get('departamento', '')

    if request.method == 'POST':
        data = request.get_json()
        action = data.get('action') if data else request.form.get('action')
        cur = mysql.connection.cursor()

        if action == 'add':
            cur.execute("""
                INSERT INTO backups (fecha, servidor, tamano_gb, estado)
                VALUES (%s, %s, %s, %s)
            """, (
                data.get('fecha'),
                data.get('servidor'),
                data.get('tamano') or None,
                data.get('estado'),
            ))
            mysql.connection.commit()
            cur.close()
            return jsonify({'success': True})

        elif action == 'update':
            cur.execute("""
                UPDATE backups
                SET fecha=%s, servidor=%s, tamano_gb=%s, estado=%s
                WHERE id=%s
            """, (
                data.get('fecha'),
                data.get('servidor'),
                data.get('tamano') or None,
                data.get('estado'),
                data.get('id'),
            ))
            mysql.connection.commit()
            cur.close()
            return jsonify({'success': True})

        elif action == 'delete':
            cur.execute("DELETE FROM backups WHERE id = %s", (data.get('id'),))
            mysql.connection.commit()
            cur.close()
            return jsonify({'success': True})

        cur.close()
        return jsonify({'success': False, 'error': 'Acción desconocida'}), 400

    # ── GET: lista completa ──
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, fecha, servidor, tamano_gb, estado
        FROM backups ORDER BY fecha DESC
    """)
    columns      = [col[0] for col in cur.description]
    backups_list = [dict(zip(columns, row)) for row in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM backups WHERE estado='OK'")
    backups_ok = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM backups WHERE estado='ERROR'")
    backups_error = cur.fetchone()[0]

    cur.execute("SELECT DATEDIFF(NOW(), MAX(fecha)) FROM backups")
    dias_ultimo_row = cur.fetchone()
    dias_ultimo = dias_ultimo_row[0] if dias_ultimo_row and dias_ultimo_row[0] else 0

    cur.close()

    return render_template('backups.html',
        backups       = backups_list,
        backups_ok    = backups_ok,
        backups_error = backups_error,
        dias_ultimo   = dias_ultimo,
        role          = role,
        departamento  = departamento,
        current_year  = datetime.now().year,
    )





# ══════════════════════════════════════════════════════
#  REGISTRAR PRESENCIA
# ══════════════════════════════════════════════════════
@main.route('/register_entry', methods=['GET', 'POST'])
@login_required
def register_entry():
    if session.get('role') not in [0, 1]:
        flash('No tienes permisos para registrar presencia.', 'warning')
        return redirect(url_for('main.dashboard'))

    cur = mysql.connection.cursor()
    entrada_abierta = tiene_entrada_abierta_presencia(cur, session['user_id'])

    if request.method == 'POST':
        if entrada_abierta:
            flash('Ya tienes una entrada registrada hoy. Registra la salida primero.', 'warning')
        else:
            record_timein(cur, session['user_id'])
            mysql.connection.commit()
            flash('¡Presencia registrada correctamente!', 'success')
        cur.close()
        return redirect(url_for('main.dashboard'))

    cur.close()
    return render_template('register_entry.html', entrada_abierta=entrada_abierta)


# ══════════════════════════════════════════════════════
#  REGISTRAR SALIDA
# ══════════════════════════════════════════════════════
@main.route('/register_exit', methods=['GET', 'POST'])
@login_required
def register_exit():
    if session.get('role') not in [0, 1]:
        flash('No tienes permisos para registrar salida.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        cur = mysql.connection.cursor()
        record_timeout(cur, session['user_id'])
        mysql.connection.commit()
        cur.close()
        flash('¡Salida registrada correctamente!', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('register_exit.html')


# ══════════════════════════════════════════════════════
#  CONTROL HORARIO — REGISTRO JORNADA LABORAL
# ══════════════════════════════════════════════════════
@main.route('/control_horario', methods=['GET', 'POST'])
@login_required
def control_horario():
    if session.get('role') not in [0, 1]:
        flash('No tienes permisos para registrar jornada laboral.', 'warning')
        return redirect(url_for('main.dashboard'))

    cur = mysql.connection.cursor()
    entrada_laboral_hoy = tiene_entrada_laboral_hoy(cur, session['user_id'])
    salida_laboral_hoy  = tiene_salida_laboral_hoy(cur, session['user_id'])
    
    # Verificamos si el usuario se fue a comer y NO ha vuelto usando tu función existente
    en_comida = tiene_salida_comida_abierta(cur, session['user_id'])

    if request.method == 'POST':
        accion = request.form.get('accion')

        if accion == 'entrada':
            if entrada_laboral_hoy:
                flash('Ya tienes una jornada laboral registrada hoy.', 'warning')
            else:
                record_timein_laboral(cur, session['user_id'])
                mysql.connection.commit()
                flash('¡Inicio de jornada registrado correctamente!', 'success')

        elif accion == 'salida':
            if not entrada_laboral_hoy:
                flash('No puedes registrar la salida sin haber registrado la entrada.', 'warning')
            elif en_comida:
                # Bloqueo en backend si intenta trampear el formulario
                flash('No puedes finalizar tu jornada. Primero debes registrar tu vuelta de comer.', 'danger')
            elif salida_laboral_hoy:
                flash('Ya tienes una salida de jornada registrada hoy.', 'warning')
            else:
                record_timeout_laboral(cur, session['user_id'])
                mysql.connection.commit()
                flash('¡Fin de jornada registrado correctamente!', 'success')

        cur.close()
        return redirect(url_for('main.control_horario'))

    cur.close()
    return render_template('control_horario.html',
                           entrada_abierta=entrada_laboral_hoy,
                           salida_abierta=salida_laboral_hoy,
                           en_comida=en_comida)


@main.route('/create_user', methods=['GET', 'POST'])
@login_required
def create_user():
    if session.get('role') != 0:
        flash('No tienes permisos para crear usuarios.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        nombre       = request.form['nombre']
        apellidos    = request.form['apellidos']
        correo       = request.form['correo']
        departamento = request.form['departamento']
        username     = request.form['username']
        raw_password = request.form['password']
        role         = int(request.form.get('role', 1))
        foto_file    = request.files.get('foto')

        foto_path = None

        if foto_file and foto_file.filename and allowed_file(foto_file.filename):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename  = secure_filename(f"{username}_{foto_file.filename}")
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            foto_file.save(save_path)
            foto_path = f"img/usuarios/{filename}"

        pass_hash = bcrypt.generate_password_hash(raw_password).decode('utf-8')

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO user (user, pass, roles, foto)
            VALUES (%s, %s, %s, %s)
        """, (username, pass_hash, role, foto_path))
        new_id = cur.lastrowid
        insert_persona(cur, new_id, nombre, apellidos, correo, departamento)
        mysql.connection.commit()
        cur.close()

        flash(f'Usuario {username} creado correctamente', 'success')
        return redirect(url_for('main.create_user'))

    return render_template('create_user.html')
    current_year = datetime.now().year,


from datetime import date, datetime, timedelta
from flask import flash, redirect, render_template, request, session, url_for



@main.route('/vacaciones', methods=['GET', 'POST'])
@main.route('/vacaciones/<int:uid>', methods=['GET', 'POST'])
@login_required
def vacaciones(uid=None):
  if session.get('role') not in (0, 1):
    flash('No tienes permisos para esta sección.', 'warning')
    return redirect(url_for('main.dashboard'))

  # Determina el usuario objetivo
  target_user = (
      uid if (uid and session.get('role') in (0, 1)) else session['user_id']
  )
  año_actual = date.today().year

  cur = mysql.connection.cursor()

  if request.method == 'POST':
    vac_in = request.form.get('vacacionesin')
    vac_out = request.form.get('vacacionesout')
    observacion = request.form.get('observacion', '').strip()

    # 1. Validar presencia de datos
    if not vac_in or not vac_out:
      cur.close()
      flash(
          'Debes seleccionar la fecha y hora de inicio y finalización.',
          'danger',
      )
      return redirect(
          url_for('main.vacaciones', uid=uid)
          if uid
          else url_for('main.vacaciones')
      )

    # 2. Parsear cadenas a objetos datetime
    try:
      dt_in = datetime.strptime(
          vac_in.replace('T', ' '),
          '%Y-%m-%d %H:%M:%S'
          if len(vac_in) > 16
          else '%Y-%m-%d %H:%M',
      )
      dt_out = datetime.strptime(
          vac_out.replace('T', ' '),
          '%Y-%m-%d %H:%M:%S'
          if len(vac_out) > 16
          else '%Y-%m-%d %H:%M',
      )
    except ValueError:
      cur.close()
      flash('El formato de fecha u hora introducido no es válido.', 'danger')
      return redirect(
          url_for('main.vacaciones', uid=uid)
          if uid
          else url_for('main.vacaciones')
      )

    # 🛑 RESTRICCIÓN DE AÑO ACTUAL: Solo se permite crear en el año en curso
    if dt_in.year != año_actual or dt_out.year != año_actual:
      cur.close()
      flash(
          f'Solo se pueden registrar propuestas para el año en curso'
          f' ({año_actual}).',
          'danger',
      )
      return redirect(
          url_for('main.vacaciones', uid=uid, anio=año_actual)
          if uid
          else url_for('main.vacaciones', anio=año_actual)
      )

    # 3. Validar coherencia cronológica
    if dt_in >= dt_out:
      cur.close()
      flash(
          'La fecha/hora de inicio debe ser anterior a la de finalización.',
          'danger',
      )
      return redirect(
          url_for('main.vacaciones', uid=uid)
          if uid
          else url_for('main.vacaciones')
      )

    # 4. Validar solapamiento con solicitudes previas del usuario
    cur.execute(
        """
            SELECT idvac FROM vacaciones 
            WHERE iduser = %s 
              AND estado IN ('Pendiente', 'Aprobado')
              AND %s < vacacionesout 
              AND %s > vacacionesin
        """,
        (target_user, dt_in, dt_out),
    )
    if cur.fetchone():
      cur.close()
      flash(
          'Ya existe una solicitud pendiente o aprobada que coincide con este'
          ' rango de fechas/horas.',
          'warning',
      )
      return redirect(
          url_for('main.vacaciones', uid=uid)
          if uid
          else url_for('main.vacaciones')
      )

    # 4.5. Validar disponibilidad de días de vacaciones
    cur.execute('SELECT fecha FROM feriados')
    f_set = {
        r[0].strftime('%Y-%m-%d') if hasattr(r[0], 'strftime') else str(r[0])
        for r in cur.fetchall()
    }
    resumen_check = obtener_resumen_vacaciones(
        cur, target_user, dt_in.year, f_set
    )

    curr_date = dt_in.date()
    dias_solicitados = 0
    while curr_date <= dt_out.date():
      es_fin_semana = curr_date.weekday() >= 5
      es_feriado = curr_date.strftime('%Y-%m-%d') in f_set
      if not es_fin_semana and not es_feriado:
        dias_solicitados += 1
      curr_date += timedelta(days=1)

    if dias_solicitados > resumen_check['disponibles']:
      cur.close()
      flash(
          f'No dispones de suficientes días disponibles. Solicitaste'
          f' {dias_solicitados} día(s) hábil(es) y solo tienes'
          f" {resumen_check['disponibles']} disponible(s).",
          'danger',
      )
      return redirect(
          url_for('main.vacaciones', uid=uid)
          if uid
          else url_for('main.vacaciones')
      )

    # 5. Inserción en la base de datos en estado 'Pendiente'
    cur.execute(
        """
            INSERT INTO vacaciones (iduser, vacacionesin, vacacionesout, estado, observacion)
            VALUES (%s, %s, %s, 'Pendiente', %s)
        """,
        (target_user, dt_in, dt_out, observacion),
    )
    mysql.connection.commit()

    # 6. Buscar datos del solicitante y departamento
    cur.execute(
        """
            SELECT nombre, apellido, departamento 
            FROM personas
            WHERE iduser = %s
        """,
        (target_user,),
    )
    emp_data = cur.fetchone()

    if emp_data:
      emp_nombre = emp_data[0] or 'Empleado'
      emp_apellido = emp_data[1] or ''
      emp_dpto = (emp_data[2] or '').strip()

      supervisora_correos = []
      if emp_dpto:
        cur.execute(
            """
                SELECT DISTINCT TRIM(p.correo)
                FROM Supervisoras s
                JOIN personas p ON s.UserID = p.iduser
                WHERE LOWER(TRIM(s.departamento)) = LOWER(TRIM(%s))
                  AND p.correo IS NOT NULL 
                  AND TRIM(p.correo) != ''
            """,
            (emp_dpto,),
        )
        sup_rows = cur.fetchall()
        supervisora_correos = [row[0] for row in sup_rows if row[0]]

      if supervisora_correos:
        try:
          msg = Message(
              subject=(
                  'Nueva Propuesta de Vacaciones/Permiso -'
                  f' {emp_nombre} {emp_apellido}'
              ),
              recipients=supervisora_correos,
          )
          msg.html = render_template(
              'email_vacaciones_pendiente.html',
              nombre_supervisora='Supervisora',
              nombre_empleado=f'{emp_nombre} {emp_apellido}',
              departamento=emp_dpto,
              fecha_inicio=dt_in.strftime('%d/%m/%Y %H:%M'),
              fecha_fin=dt_out.strftime('%d/%m/%Y %H:%M'),
              observacion=observacion,
              url_revision=url_for('main.gestion_vacaciones', _external=True),
          )
          mail.send(msg)
          flash(
              'Propuesta registrada correctamente. Se ha notificado por correo'
              ' a la supervisora.',
              'success',
          )
        except Exception as e:
          print(f'[ERROR SMTP AL ENVIAR CORREO]: {e}')
          flash(
              'Propuesta registrada en estado Pendiente. (Aviso de correo:'
              f' {e})',
              'warning',
          )
      else:
        flash(
            'Propuesta registrada en estado Pendiente. (Aviso: No se encontró'
            f" supervisora con correo activo para el departamento '{emp_dpto}').",
            'warning',
        )

    cur.close()
    return redirect(
        url_for('main.vacaciones', uid=uid, anio=dt_in.year)
        if uid
        else url_for('main.vacaciones', anio=dt_in.year)
    )

  # GET: Capturar el año seleccionado en la URL (por defecto, año actual)
  anio_seleccionado = request.args.get('anio', type=int, default=año_actual)

  # GET: Obtener información del usuario
  nombre, apellido = get_persona(cur, target_user)

  # 1. Obtener conjunto de feriados
  cur.execute('SELECT fecha FROM feriados')
  feriados_rows = cur.fetchall()
  feriados_set = {
      r[0].strftime('%Y-%m-%d') if hasattr(r[0], 'strftime') else str(r[0])
      for r in feriados_rows
  }

  # 2. Consultar solicitudes FILTRADAS POR EL AÑO SELECCIONADO
  cur.execute(
      """
        SELECT vacacionesin, vacacionesout, idvac, estado, observacion
        FROM vacaciones
        WHERE iduser = %s AND YEAR(vacacionesin) = %s
        ORDER BY vacacionesin DESC
    """,
      (target_user, anio_seleccionado),
  )
  lista_vacs = cur.fetchall()

  # 3. Procesar lista para calcular tiempo laborable
  vacaciones_procesadas = []
  for vac in lista_vacs:
    v_in, v_out = vac[0], vac[1]
    tiempo_texto = (
        calcular_tiempo_laborable(v_in, v_out, feriados_set)
        if v_in and v_out
        else '-'
    )

    vacaciones_procesadas.append((
        vac[0],
        vac[1],
        vac[2],
        vac[3],
        vac[4],
        tiempo_texto,
    ))

  # 4. Obtener resumen de días correspondientes al AÑO SELECCIONADO
  resumen_vac = obtener_resumen_vacaciones(
      cur, target_user, anio_seleccionado, feriados_set
  )

  cur.close()

  # Lista de años para el desplegable del selector (histórico)
  anios_disponibles = list(range(año_actual - 2, año_actual + 2))

  return render_template(
      'register_vacaciones.html',
      nombre=nombre,
      apellido=apellido,
      vacaciones=vacaciones_procesadas,
      current_year=año_actual,
      selected_year=anio_seleccionado,
      anios_disponibles=anios_disponibles,
      target_user=target_user,
      resumen_vac=resumen_vac,
  )


@main.route('/editar-vacacion', methods=['POST'])
@login_required
def editar_vacacion():
  vacacion_id = request.form.get('vacacion_id')
  vac_in = request.form.get('vacacionesin')
  vac_out = request.form.get('vacacionesout')
  obs = request.form.get('observacion', '').strip()
  uid = request.form.get('uid')
  user_role = session.get('role')
  año_actual = date.today().year

  cur = mysql.connection.cursor()

  # 1. Obtener los datos actuales de la solicitud
  cur.execute(
      'SELECT iduser, estado, vacacionesin FROM vacaciones WHERE idvac = %s',
      (vacacion_id,),
  )
  vac = cur.fetchone()

  if not vac:
    cur.close()
    flash('La solicitud no existe.', 'danger')
    return redirect(url_for('main.vacaciones'))

  vac_owner, estado_actual, fecha_original = vac

  # Restricción de año actual
  if fecha_original and fecha_original.year != año_actual:
    cur.close()
    flash(
        f'No se pueden editar registros de otros años ({fecha_original.year}).',
        'danger',
    )
    return redirect(
        url_for('main.vacaciones', uid=uid, anio=fecha_original.year)
        if uid
        else url_for('main.vacaciones', anio=fecha_original.year)
    )

  # 2. Permitir editar si está 'Pendiente' O 'Rechazado' (o si es Admin)
  if estado_actual not in ['Pendiente', 'Rechazado'] and user_role != 0:
    cur.close()
    flash(
        f'No puedes editar una solicitud que ya ha sido procesada ({estado_actual}).',
        'danger',
    )
    return redirect(
        url_for('main.vacaciones', uid=uid)
        if uid
        else url_for('main.vacaciones')
    )

  # Parsear fechas de edición
  try:
    dt_in = datetime.strptime(
        vac_in.replace('T', ' '),
        '%Y-%m-%d %H:%M:%S' if len(vac_in) > 16 else '%Y-%m-%d %H:%M',
    )
    dt_out = datetime.strptime(
        vac_out.replace('T', ' '),
        '%Y-%m-%d %H:%M:%S' if len(vac_out) > 16 else '%Y-%m-%d %H:%M',
    )
  except ValueError:
    cur.close()
    flash('Formato de fecha u hora no válido.', 'danger')
    return redirect(url_for('main.vacaciones'))

  # Validar que la nueva fecha pertenezca al año actual
  if dt_in.year != año_actual or dt_out.year != año_actual:
    cur.close()
    flash(
        f'La nueva fecha debe pertenecer al año en curso ({año_actual}).',
        'danger',
    )
    return redirect(url_for('main.vacaciones'))

  # 3. Validar disponibilidad de días
  cur.execute('SELECT fecha FROM feriados')
  feriados_set = {
      r[0].strftime('%Y-%m-%d') if hasattr(r[0], 'strftime') else str(r[0])
      for r in cur.fetchall()
  }

  resumen = obtener_resumen_vacaciones(
      cur, vac_owner, dt_in.year, feriados_set
  )

  curr = dt_in.date()
  dias_nuevos = 0
  while curr <= dt_out.date():
    if curr.weekday() < 5 and curr.strftime('%Y-%m-%d') not in feriados_set:
      dias_nuevos += 1
    curr += timedelta(days=1)

  if dias_nuevos > resumen['disponibles']:
    cur.close()
    flash(
        f'No dispones de suficientes días. Solicitaste {dias_nuevos} día(s)'
        f" hábil(es) y solo tienes {resumen['disponibles']} disponible(s).",
        'warning',
    )
    return redirect(
        url_for('main.vacaciones', uid=uid)
        if uid
        else url_for('main.vacaciones')
    )

  # 4. Actualizar solicitud y restablecer estado a 'Pendiente'
  cur.execute(
      """
        UPDATE vacaciones
        SET vacacionesin = %s,
            vacacionesout = %s,
            observacion = %s,
            estado = 'Pendiente',
            aprobado_por = NULL
        WHERE idvac = %s
    """,
      (dt_in, dt_out, obs, vacacion_id),
  )

  mysql.connection.commit()

  # 5. Buscar datos del solicitante y enviar correo de renotificación
  cur.execute(
      """
        SELECT nombre, apellido, departamento 
        FROM personas 
        WHERE iduser = %s
    """,
      (vac_owner,),
  )
  emp_data = cur.fetchone()

  if emp_data:
    emp_nombre = emp_data[0] or 'Empleado'
    emp_apellido = emp_data[1] or ''
    emp_dpto = (emp_data[2] or '').strip()

    supervisora_correos = []
    if emp_dpto:
      cur.execute(
          """
                SELECT DISTINCT TRIM(p.correo)
                FROM Supervisoras s
                JOIN personas p ON s.UserID = p.iduser
                WHERE LOWER(TRIM(s.departamento)) = LOWER(TRIM(%s))
                  AND p.correo IS NOT NULL 
                  AND TRIM(p.correo) != ''
            """,
          (emp_dpto,),
      )
      sup_rows = cur.fetchall()
      supervisora_correos = [row[0] for row in sup_rows if row[0]]

    if supervisora_correos:
      try:
        msg = Message(
            subject=(
                'Propuesta Modificada de Vacaciones -'
                f' {emp_nombre} {emp_apellido}'
            ),
            recipients=supervisora_correos,
        )
        msg.html = render_template(
            'email_vacaciones_pendiente.html',
            nombre_supervisora='Supervisora',
            nombre_empleado=f'{emp_nombre} {emp_apellido}',
            departamento=emp_dpto,
            fecha_inicio=dt_in.strftime('%d/%m/%Y %H:%M'),
            fecha_fin=dt_out.strftime('%d/%m/%Y %H:%M'),
            observacion=obs,
            url_revision=url_for('main.gestion_vacaciones', _external=True),
        )
        mail.send(msg)
        flash(
            'Solicitud actualizada correctamente y reenviada por correo a la'
            ' supervisora.',
            'success',
        )
      except Exception as e:
        print(f'[ERROR SMTP AL REENVIAR CORREO]: {e}')
        flash(
            'Solicitud actualizada en estado Pendiente. (Aviso de correo:'
            f' {e})',
            'warning',
        )
    else:
      flash(
          'Solicitud actualizada en estado Pendiente. (Aviso: No se encontró'
          f" supervisora con correo activo para el departamento '{emp_dpto}').",
          'warning',
      )

  cur.close()
  return redirect(
      url_for('main.vacaciones', uid=uid, anio=año_actual)
      if uid
      else url_for('main.vacaciones', anio=año_actual)
  )
@main.route('/vacaciones/delete', methods=['POST'])
@login_required
def delete_vacacion():
  if session.get('role') not in (0, 1):
    flash('No tienes permisos para esta sección.', 'warning')
    return redirect(url_for('main.dashboard'))

  vacacion_id = request.form.get('vacacion_id')
  uid = request.form.get('uid')
  año_actual = date.today().year

  cur = mysql.connection.cursor()

  # Consultar fecha y estado antes de borrar
  cur.execute(
      'SELECT iduser, estado, vacacionesin FROM vacaciones WHERE idvac = %s',
      (vacacion_id,),
  )
  vac = cur.fetchone()

  if not vac:
    cur.close()
    flash('La solicitud no existe o ya fue eliminada.', 'danger')
    return redirect(url_for('main.vacaciones'))

  estado_actual = vac[1]
  fecha_original = vac[2]

  # 🛑 RESTRICCIÓN DE AÑO ACTUAL: Impedir borrar registros de otros años
  if fecha_original and fecha_original.year != año_actual:
    cur.close()
    flash(
        f'No se pueden eliminar registros del año {fecha_original.year}. Solo'
        f' se pueden gestionar solicitudes del año actual ({año_actual}).',
        'danger',
    )
    return redirect(
        url_for('main.vacaciones', uid=uid, anio=fecha_original.year)
        if uid
        else url_for('main.vacaciones', anio=fecha_original.year)
    )

  # Bloquear borrado a empleados si la solicitud no está Pendiente/Rechazada
  if session.get('role') == 1 and estado_actual not in ('Pendiente', 'Rechazado'):
    cur.close()
    flash(
        f'No puedes eliminar una solicitud que ya fue procesada ({estado_actual}).',
        'danger',
    )
    return redirect(url_for('main.vacaciones'))

  cur.execute(
      """
        DELETE FROM vacaciones
        WHERE idvac = %s 
    """,
      (vacacion_id,),
  )
  mysql.connection.commit()
  cur.close()

  flash('Solicitud de vacaciones eliminada.', 'info')
  return redirect(
      url_for('main.vacaciones', uid=uid, anio=año_actual)
      if uid
      else url_for('main.vacaciones', anio=año_actual)
  )
#--------------------------------------------------------
@main.route('/gestion-vacaciones')
@login_required
def gestion_vacaciones():
  user_id = session['user_id']
  user_role = session.get('role')
  cur = mysql.connection.cursor()

  # 1. Obtener departamento del usuario actual
  cur.execute(
      'SELECT departamento FROM personas WHERE iduser = %s', (user_id,)
  )
  dep_row = cur.fetchone()
  user_dep = dep_row[0].lower() if (dep_row and dep_row[0]) else ''
  es_it = user_dep == 'it'

  # 2. Consultar festivos registrados en la BD
  cur.execute('SELECT fecha FROM feriados')
  feriados_rows = cur.fetchall()
  feriados_set = {
      r[0].strftime('%Y-%m-%d') if hasattr(r[0], 'strftime') else str(r[0])
      for r in feriados_rows
  }

  # 3. Comprobar asignación en la tabla Supervisoras
  cur.execute(
      'SELECT departamento FROM Supervisoras WHERE UserID = %s', (user_id,)
  )
  deptos_registrados = [row[0] for row in cur.fetchall()]

  # Si no es Rol 0, no tiene departamentos en Supervisoras y tampoco es IT -> Denegar
  if user_role != 0 and not deptos_registrados and not es_it:
    cur.close()
    flash('No tienes permisos para acceder a esta sección.', 'danger')
    return redirect(url_for('main.dashboard'))

  # Determinar si es solo lectura (Si no es admin ni supervisora asignada)
  es_solo_lectura = user_role != 0 and not deptos_registrados

  # SOLO ven a todos: si tienen 'TODOS' asignado, si pertenecen a IT, o si es un Admin sin restricción
  ver_todos = (
      ('TODOS' in deptos_registrados)
      or es_it
      or (user_role == 0 and not deptos_registrados)
  )

  # 4. Fechas del mes y año a visualizar
  hoy = date.today()
  anio = request.args.get('anio', hoy.year, type=int)
  mes = request.args.get('mes', hoy.month, type=int)
  num_dias_mes = monthrange(anio, mes)[1]
  dias_mes = [date(anio, mes, d) for d in range(1, num_dias_mes + 1)]

  # 5. Consultar Empleados (Filtrado estricto por equipo si no es ver_todos)
  if ver_todos:
    cur.execute("""
            SELECT DISTINCT p.iduser, p.nombre, p.apellido, p.departamento, u.foto
            FROM personas p
            LEFT JOIN user u ON p.iduser = u.iduser
            ORDER BY p.apellido, p.nombre
        """)
  else:
    cur.execute(
        """
            SELECT DISTINCT p.iduser, p.nombre, p.apellido, p.departamento, u.foto
            FROM personas p
            JOIN Supervisoras s ON p.departamento = s.departamento
            LEFT JOIN user u ON p.iduser = u.iduser
            WHERE s.UserID = %s
            ORDER BY p.apellido, p.nombre
        """,
        (user_id,),
    )

  empleados = cur.fetchall()

  # 6. Solicitudes Pendientes de la bandeja rápida
  if ver_todos:
    cur.execute("""
            SELECT DISTINCT v.idvac, p.iduser, p.nombre, p.apellido, p.departamento, v.vacacionesin, v.vacacionesout, v.observacion, v.fecha_solicitud
            FROM vacaciones v
            JOIN personas p ON v.iduser = p.iduser
            WHERE v.estado = 'Pendiente'
            ORDER BY v.vacacionesin ASC
        """)
  else:
    cur.execute(
        """
            SELECT DISTINCT v.idvac, p.iduser, p.nombre, p.apellido, p.departamento, v.vacacionesin, v.vacacionesout, v.observacion, v.fecha_solicitud
            FROM vacaciones v
            JOIN personas p ON v.iduser = p.iduser
            JOIN Supervisoras s ON p.departamento = s.departamento
            WHERE s.UserID = %s AND v.estado = 'Pendiente'
            ORDER BY v.vacacionesin ASC
        """,
        (user_id,),
    )

  pendientes = cur.fetchall()

  # 7. Obtener vacaciones para la matriz del mes
  inicio_mes = f'{anio}-{mes:02d}-01 00:00:00'
  fin_mes = f'{anio}-{mes:02d}-{num_dias_mes:02d} 23:59:59'

  if ver_todos:
    cur.execute(
        """
            SELECT DISTINCT v.idvac, v.iduser, v.vacacionesin, v.vacacionesout, v.estado, v.observacion, p.nombre, p.apellido
            FROM vacaciones v
            JOIN personas p ON v.iduser = p.iduser
            WHERE v.estado IN ('Pendiente', 'Aprobado')
              AND v.vacacionesin <= %s AND v.vacacionesout >= %s
        """,
        (fin_mes, inicio_mes),
    )
  else:
    cur.execute(
        """
            SELECT DISTINCT v.idvac, v.iduser, v.vacacionesin, v.vacacionesout, v.estado, v.observacion, p.nombre, p.apellido
            FROM vacaciones v
            JOIN personas p ON v.iduser = p.iduser
            JOIN Supervisoras s ON p.departamento = s.departamento
            WHERE s.UserID = %s 
              AND v.estado IN ('Pendiente', 'Aprobado')
              AND v.vacacionesin <= %s AND v.vacacionesout >= %s
        """,
        (user_id, fin_mes, inicio_mes),
    )

  vacaciones_mes = cur.fetchall()

  # 8. CALCULAR SALDOS Y RESUMEN DE VACACIONES DE CADA EMPLEADO (PARA LA 3ª PESTAÑA)
  equipo_saldos = []
  for emp in empleados:
    emp_id = emp[0]
    emp_nom = emp[1] or ''
    emp_ape = emp[2] or ''
    emp_dpto = emp[3] or '-'
    emp_foto = emp[4]

    # Generar iniciales para el avatar
    ini_nom = emp_nom[0].upper() if emp_nom else ''
    ini_ape = emp_ape[0].upper() if emp_ape else ''
    iniciales = f'{ini_nom}{ini_ape}' or 'U'

    # Consultar resumen para el año seleccionado (anio)
    resumen = obtener_resumen_vacaciones(cur, emp_id, anio, feriados_set)

    equipo_saldos.append({
        'iduser': emp_id,
        'nombre': f'{emp_nom} {emp_ape}'.strip(),
        'departamento': emp_dpto,
        'foto': emp_foto,
        'iniciales': iniciales,
        'totales': resumen.get('totales', 30),
        'disfrutados': resumen.get('disfrutados', 0),
        'aprobados': resumen.get('aprobados', 0),
        'pendientes': resumen.get('pendientes', 0),
        'disponibles': resumen.get('disponibles', 0),
    })

  # Cierre del cursor de MySQL
  cur.close()

  # 9. Mapear la matriz (omite fines de semana y feriados)
  matriz_eventos = {emp[0]: {} for emp in empleados}
  for vac in vacaciones_mes:
    idvac, iduser, vac_in, vac_out, estado, obs, nom, ape = vac
    if iduser in matriz_eventos:
      es_multidia = (vac_out.date() - vac_in.date()).days >= 1
      duracion_horas = (vac_out - vac_in).total_seconds() / 3600.0

      if es_multidia or duracion_horas >= 7:
        texto_bloque = 'VAC'
      else:
        texto_bloque = (
            f"{vac_in.strftime('%H:%M')}-{vac_out.strftime('%H:%M')}"
        )

      for dia in dias_mes:
        if vac_in.date() <= dia <= vac_out.date():
          es_fin_semana = dia.weekday() >= 5
          es_feriado = dia.strftime('%Y-%m-%d') in feriados_set

          if es_fin_semana or es_feriado:
            continue

          dia_num = dia.day
          if dia_num not in matriz_eventos[iduser]:
            matriz_eventos[iduser][dia_num] = []

          if not any(
              e['idvac'] == idvac for e in matriz_eventos[iduser][dia_num]
          ):
            matriz_eventos[iduser][dia_num].append({
                'idvac': idvac,
                'estado': estado,
                'texto_bloque': texto_bloque,
                'vac_in_fmt': vac_in.strftime('%d/%m/%Y %H:%M'),
                'vac_out_fmt': vac_out.strftime('%d/%m/%Y %H:%M'),
                'observacion': obs or '',
                'nombre_completo': f'{nom} {ape}',
            })

  # Lista de años para el selector
  anios_disponibles = list(range(hoy.year - 2, hoy.year + 2))

  return render_template(
      'gestion_vacaciones.html',
      empleados=empleados,
      pendientes=pendientes,
      matriz_eventos=matriz_eventos,
      equipo_saldos=equipo_saldos,  # ← Se envía la lista de saldos
      dias_mes=dias_mes,
      feriados_set=feriados_set,
      mes_actual=mes,
      anio_actual=anio,
      selected_year=anio,
      anios_disponibles=anios_disponibles,
      es_solo_lectura=es_solo_lectura,
      es_it=es_it,
      current_year=hoy.year,
  )

@main.route('/procesar-vacacion/<int:idvac>/<string:accion>', methods=['POST'])
@login_required
def procesar_vacacion(idvac, accion):
  user_id = session['user_id']

  # 1. Validar que la acción enviada sea válida
  if accion not in ('Aprobado', 'Rechazado'):
    flash('Acción no válida.', 'danger')
    return redirect(url_for('main.gestion_vacaciones'))

  cur = mysql.connection.cursor()

  # 2. Obtener departamento del usuario actual (para comprobar IT)
  cur.execute('SELECT departamento FROM personas WHERE iduser = %s', (user_id,))
  dep_row = cur.fetchone()
  user_dep = dep_row[0].lower() if (dep_row and dep_row[0]) else ''
  es_it = user_dep == 'it'

  # 3. Obtener datos de la solicitud y del empleado solicitante
  cur.execute(
      """
        SELECT 
            v.iduser,
            p_emp.nombre,
            p_emp.apellido,
            p_emp.correo,
            v.vacacionesin,
            v.vacacionesout
        FROM vacaciones v
        JOIN personas p_emp ON v.iduser = p_emp.iduser
        WHERE v.idvac = %s
    """,
      (idvac,),
  )
  solicitud = cur.fetchone()

  if not solicitud:
    cur.close()
    flash('La solicitud no existe.', 'danger')
    return redirect(url_for('main.gestion_vacaciones'))

  emp_id, emp_nombre, emp_apellido, emp_correo, vac_in, vac_out = solicitud

  # 4. Permisos IT: Si el usuario es de IT y la solicitud NO es suya -> Bloquear
  if es_it and emp_id != user_id:
    cur.close()
    flash(
        'Como personal de IT solo puedes gestionar tus propias solicitudes.',
        'warning',
    )
    return redirect(url_for('main.gestion_vacaciones'))

  # 5. Obtener motivo de rechazo si aplica
  motivo_rechazo = request.form.get('motivo_rechazo', '').strip()

  # 6. Actualizar estado y registrador en la base de datos
  cur.execute(
      """
        UPDATE vacaciones
        SET estado = %s, aprobado_por = %s
        WHERE idvac = %s
    """,
      (accion, user_id, idvac),
  )
  mysql.connection.commit()
  cur.close()

  # 7. Enviar correo de notificación al empleado
  if emp_correo:
    try:
      msg = Message(
          subject=(
              f'Respuesta a tu Solicitud de Vacaciones/Permiso - {accion}'
          ),
          recipients=[emp_correo],
      )
      msg.html = render_template(
          'email_vacaciones_respuesta.html',
          nombre_empleado=f'{emp_nombre} {emp_apellido}',
          estado=accion,
          fecha_inicio=vac_in.strftime('%d/%m/%Y %H:%M'),
          fecha_fin=vac_out.strftime('%d/%m/%Y %H:%M'),
          motivo_rechazo=motivo_rechazo if accion == 'Rechazado' else None,
          url_mis_vacaciones=url_for('main.vacaciones', _external=True),
      )
      mail.send(msg)
      flash(
          f'Solicitud {accion.lower()} correctamente y empleado notificado por'
          ' correo.',
          'success',
      )
    except Exception as e:
      print(f'[ERROR SMTP RESPUESTA VACACIÓN]: {e}')
      flash(
          f'Solicitud {accion.lower()} registrada en la base de datos. (Aviso'
          f' correo: {e})',
          'warning',
      )
  else:
    flash(
        f'Solicitud {accion.lower()} correctamente en la base de datos.',
        'success',
    )

  # REDIRECCIÓN FINAL (OBLIGATORIA)
  return redirect(url_for('main.gestion_vacaciones'))


@main.route('/enviar-correo', methods=['GET', 'POST'])
@login_required
def enviar_correo():
  # Restringir acceso solo a Administradores / Supervisoras (roles 0 y 1)
  if session.get('role') not in (0, 1):
    flash('No tienes permisos para acceder a esta sección.', 'warning')
    return redirect(url_for('main.dashboard'))

  if request.method == 'POST':
    destinatarios_raw = request.form.get('destinatarios', '').strip()
    asunto = request.form.get('asunto', '').strip()
    mensaje_cuerpo = request.form.get('mensaje', '').strip()

    # 1. Validar campos vacíos
    if not destinatarios_raw or not asunto or not mensaje_cuerpo:
      flash('Todos los campos son obligatorios.', 'danger')
      return redirect(url_for('main.enviar_correo'))

    # 2. Procesar lista de correos (permite separar por comas o punto y coma)
    lista_destinatarios = [
        email.strip()
        for email in destinatarios_raw.replace(';', ',').split(',')
        if email.strip() and '@' in email
    ]

    if not lista_destinatarios:
      flash(
          'Debes ingresar al menos una dirección de correo válida.', 'warning'
      )
      return redirect(url_for('main.enviar_correo'))

    # 3. Enviar el correo electrónico
    try:
      msg = Message(subject=asunto, recipients=lista_destinatarios)
      msg.html = render_template(
          'email_personalizado.html',
          asunto=asunto,
          mensaje=mensaje_cuerpo,
          remitente_nombre=session.get('nombre', 'TurnoApp'),
      )
      mail.send(msg)

      correos_str = ', '.join(lista_destinatarios)
      flash(
          f'Correo enviado correctamente a: {correos_str}',
          'success',
      )
      return redirect(url_for('main.enviar_correo'))

    except Exception as e:
      print(f'[ERROR AL ENVIAR CORREO]: {e}')
      flash(f'Error al procesar el envío: {e}', 'danger')

  return render_template('enviar_correo.html')




# ══════════════════════════════════════════════════════
#  Feriados API Endpoint
# ══════════════════════════════════════════════════════

@main.route('/api/feriados', methods=['GET'])
@login_required
def get_feriados():
  try:
    cur = mysql.connection.cursor()
    cur.execute('SELECT fecha, descripcion FROM feriados')
    rows = cur.fetchall()
    cur.close()

    lista_feriados = []
    for r in rows:
      # Compatible si el cursor devuelve tupla r[0] o diccionario r['fecha']
      fecha_val = r[0] if isinstance(r, (tuple, list)) else r.get('fecha')
      desc_val = (
          r[1] if isinstance(r, (tuple, list)) else r.get('descripcion', '')
      )

      # Convertir objeto date/datetime a string YYYY-MM-DD
      if hasattr(fecha_val, 'strftime'):
        fecha_str = fecha_val.strftime('%Y-%m-%d')
      else:
        fecha_str = str(fecha_val)

      lista_feriados.append({'fecha': fecha_str, 'descripcion': desc_val})

    return jsonify(lista_feriados)

  except Exception as e:
    print(f'[ERROR /api/feriados]: {e}')
    return jsonify([])

# ══════════════════════════════════════════════════════
#  PANEL DE EMPLEADOS
# ══════════════════════════════════════════════════════
@main.route('/empleados', methods=['GET', 'POST'])
@login_required
def admin_empleados():
    cur        = mysql.connection.cursor()
    nombre_a, apellido_a, dept = get_persona_detail(cur, session['user_id'])
    dept_lower = (dept or '').lower()
    role       = session.get('role')
    user_id    = session['user_id']

    # ══ CARGAR LISTA USUARIOS SEGÚN ROL ══
    if role == 0:
        if dept_lower in ['it', 'administración', 'administracion']:
            cur.execute("SELECT iduser, nombre, apellido FROM personas ORDER BY nombre")
            usuarios = cur.fetchall()
        else:
            cur.execute("""
                SELECT iduser, nombre, apellido FROM personas
                WHERE LOWER(departamento) = %s ORDER BY nombre
            """, (dept_lower,))
            usuarios = cur.fetchall()
    else:
        cur.execute("""
            SELECT iduser, nombre, apellido FROM personas
            WHERE iduser = %s
        """, (user_id,))
        usuarios = cur.fetchall()

    asistencia   = None
    vacaciones_u = None
    horas_ret    = None        # ← NUEVO
    lunch        = None
    fecha        = date.today().strftime('%Y-%m-%d')
    seleccionado = None
    accion       = None        # ← NUEVO: para que Jinja sepa qué mostrar

    if request.method == 'POST':
        selected_raw = request.form.get('selected_user')
        if not selected_raw:
            cur.close()
            return redirect(url_for('main.admin_empleados'))

        seleccionado = int(selected_raw)
        fecha        = request.form.get('fecha', date.today().strftime('%Y-%m-%d'))
        accion       = request.form.get('action', 'asistencia')

        # ══ VALIDAR PERMISOS ══
        if role == 0:
            if dept_lower not in ['it', 'administración', 'administracion']:
                ids_permitidos = [u[0] for u in usuarios]
                if seleccionado not in ids_permitidos:
                    cur.close()
                    flash('No tienes permisos para ver ese empleado.', 'warning')
                    return redirect(url_for('main.admin_empleados'))
        else:
            if seleccionado != user_id:
                cur.close()
                flash('Solo puedes ver tu propio registro.', 'warning')
                return redirect(url_for('main.admin_empleados'))

        # ══ ASISTENCIA ══
        if accion == 'asistencia':
            cur.execute("""
                SELECT
                   MIN(til.id)         AS id,
                   MIN(til.timein)     AS timein,
                    MAX(tol.timeout)    AS timeout,
                    MAX(til.nota)       AS nota
                FROM turn_in_laboral til
                LEFT JOIN turn_out_laboral tol
                    ON til.iduser = tol.iduser
                    AND DATE(til.timein) = DATE(tol.timeout)
                WHERE til.iduser = %s
                AND DATE(til.timein) = %s
                GROUP BY DATE(til.timein)
                
            """, (seleccionado, fecha))
            asistencia = cur.fetchall()

            cur.execute("""
                SELECT id, salida, entrada
                FROM turn_lunch
                WHERE iduser = %s AND DATE(salida) = %s
                LIMIT 1
            """, (seleccionado, fecha))
            lunch = cur.fetchone()

        # ══ VACACIONES ══
        elif accion == 'vacaciones':
            anio_actual     = date.today().year
            primer_dia_anio = f"{anio_actual}-01-01"
            ultimo_dia_anio = f"{anio_actual}-12-31"
            cur.execute("""
                SELECT vacacionesin, vacacionesout, idvac
                FROM vacaciones
                WHERE iduser = %s AND vacacionesin BETWEEN %s AND %s
                ORDER BY vacacionesin
            """, (seleccionado, primer_dia_anio, ultimo_dia_anio))
            vacaciones_u = cur.fetchall()

        # ══ HORAS RETRIBUIDAS ══ 
        elif accion == 'retribuidas':
            
            mes = fecha[:7]  # '2026-03'
            cur.execute("""
                SELECT
                    hr.id,
                    hr.fecha_inicio,
                    hr.fecha_fin,
                    hr.motivos,
                    TIMESTAMPDIFF(MINUTE, hr.fecha_inicio, hr.fecha_fin) AS minutos
                FROM horas_retribuidas hr
                WHERE hr.user_id = %s
                  AND DATE_FORMAT(hr.fecha_inicio, '%%Y-%%m') = %s
                ORDER BY hr.fecha_inicio ASC
            """, (seleccionado, mes))
            horas_ret = cur.fetchall()

    cur.close()

    return render_template(
        'admin_empleados.html',
        admin_name   = f"{nombre_a} {apellido_a}",
        usuarios     = usuarios,
        asistencia   = asistencia,
        vacaciones   = vacaciones_u,
        horas_ret    = horas_ret,      
        lunch        = lunch,
        fecha        = fecha,
        seleccionado = seleccionado,
        current_year = date.today().year,
        role         = role,
        accion       = accion          
    )


@main.route('/horas_retribuidas/add_dia', methods=['POST'])
@login_required
def horas_retribuidas_add_dia():
    data = request.get_json()
    try:
        user_id = data.get('user_id')
        fecha   = data.get('fecha')
        motivos = data.get('motivos')

        if not fecha or not user_id:
            return jsonify({'success': False, 'error': 'Faltan datos: user_id o fecha'}), 400

        fecha_inicio = fecha + ' 00:00:00'
        fecha_fin    = fecha + ' 08:00:00'
        creado_por   = session.get('user_id', 0)

        cur = mysql.connection.cursor()

        # 1. horas_retribuidas — columnas correctas
        cur.execute("""
            INSERT INTO horas_retribuidas (user_id, fecha_inicio, fecha_fin, motivos, tipo, creado_por)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, fecha_inicio, fecha_fin, motivos, 'Permiso', creado_por))

        # 2. turn_in_laboral
        cur.execute("""
            INSERT INTO turn_in_laboral (iduser, timein, nota)
            VALUES (%s, %s, %s)
        """, (user_id, fecha_inicio, motivos))

        # 3. turn_out_laboral
        cur.execute("""
            INSERT INTO turn_out_laboral (iduser, timeout)
            VALUES (%s, %s)
        """, (user_id, fecha_inicio))

        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ══════════════════════════════════════════════════════
#  GUARDAR NOTA — turn_in_laboral
# ══════════════════════════════════════════════════════
@main.route('/guardar-nota', methods=['POST'])
@login_required
def guardar_nota():
    

    turn_in_id = request.form.get('turn_in_id')
    nota       = request.form.get('nota', '').strip()

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE turn_in_laboral SET nota = %s WHERE id = %s
    """, (nota, turn_in_id))
    mysql.connection.commit()
    cur.close()

    return jsonify({'status': 'ok'}), 200


# ══════════════════════════════════════════════════════
#  EDITAR REGISTRO — turn_in_laboral + turn_out_laboral
# ══════════════════════════════════════════════════════
@main.route('/editar-registro', methods=['POST'])
@login_required
def editar_registro():
    if session.get('role') != 0:
        return jsonify({'status': 'error', 'msg': 'Sin permisos'}), 403

    turn_in_id    = request.form.get('turn_in_id')
    nuevo_timein  = request.form.get('timein')
    nuevo_timeout = request.form.get('timeout')
    nota          = request.form.get('nota', '').strip()

    cur = mysql.connection.cursor()

    # Verifica si el timein está vacío
    if not nuevo_timein:
        return jsonify({'status': 'error', 'msg': 'El campo timein no puede estar vacío.'}), 400

    # Verifica si el registro existe
    cur.execute("SELECT COUNT(*) FROM turn_in_laboral WHERE id = %s", (turn_in_id,))
    exists = cur.fetchone()[0]

    if exists:
        # Actualizar entrada + nota
        cur.execute("""
            UPDATE turn_in_laboral
            SET timein = %s, nota = %s
            WHERE id = %s
        """, (nuevo_timein, nota, turn_in_id))
    else:
        # Si no existe, insertar un nuevo registro
        cur.execute("""
            INSERT INTO turn_in_laboral (iduser, timein, nota)
            VALUES (%s, %s, %s)
        """, (session['user_id'], nuevo_timein, nota))

    # Actualizar salida si existe
    if nuevo_timeout:
        cur.execute("""
            UPDATE turn_out_laboral
            SET timeout = %s
            WHERE iduser = (
                SELECT iduser FROM turn_in_laboral WHERE id = %s
            )
            AND DATE(timeout) = DATE(%s)
        """, (nuevo_timeout, turn_in_id, nuevo_timein))

    mysql.connection.commit()
    cur.close()

    return jsonify({'status': 'ok'}), 200


# ══════════════════════════════════════════════════════
#  EDITAR LUNCH — turn_lunch
# ══════════════════════════════════════════════════════
@main.route('/editar-lunch', methods=['POST'])
@login_required
def editar_lunch():
    if session.get('role') != 0:
        return jsonify({'status': 'error', 'msg': 'Sin permisos'}), 403

    lunch_id      = request.form.get('lunch_id')
    nueva_salida  = request.form.get('lunch_salida')
    nueva_entrada = request.form.get('lunch_entrada')

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE turn_lunch
        SET salida  = %s,
            entrada = %s
        WHERE id = %s
    """, (
        nueva_salida  if nueva_salida  else None,
        nueva_entrada if nueva_entrada else None,
        lunch_id
    ))
    mysql.connection.commit()
    cur.close()

    return jsonify({'status': 'ok'}), 200


# ══════════════════════════════════════════════════════
#  ASISTENCIA MES — turn_in_laboral + turn_out_laboral asasdasdasdasd
# ══════════════════════════════════════════════════════
@main.route('/asistencia-mes', methods=['GET'])
@login_required
def asistencia_mes():
    if session.get('role') not in [0, 1]:
        return jsonify({'error': 'Sin permisos'}), 403

    user_id = request.args.get('user_id', type=int)
    mes = request.args.get('mes')

    if not user_id or not mes:
        return jsonify({'registros': []})

    try:
        year, month = map(int, mes.split('-'))
    except:
        return jsonify({'registros': []})

    from calendar import monthrange
    ultimo_dia_num = monthrange(year, month)[1]
    primer_dia = f"{year}-{month:02d}-01"
    ultimo_dia = f"{year}-{month:02d}-{ultimo_dia_num}"

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT
            d.fecha,
            d.timein,
            d.timeout,
            d.nota,
            tl.salida AS lunch_salida,
            tl.entrada AS lunch_entrada
        FROM (
            SELECT
                DATE(til.timein) AS fecha,
                MIN(til.timein)  AS timein,
                MAX(tol.timeout) AS timeout,
                MAX(til.nota)    AS nota
            FROM turn_in_laboral til
            LEFT JOIN turn_out_laboral tol
                ON til.iduser = tol.iduser
                AND DATE(til.timein) = DATE(tol.timeout)
            WHERE til.iduser = %s
              AND DATE(til.timein) BETWEEN %s AND %s
            GROUP BY DATE(til.timein)
        ) d
        LEFT JOIN turn_lunch tl
            ON tl.iduser = %s
            AND DATE(tl.salida) = d.fecha
        ORDER BY d.fecha ASC
    """, (user_id, primer_dia, ultimo_dia, user_id))

    rows = cur.fetchall()
    cur.close()

    registros = []
    for row in rows:
        registros.append({
            'timein': row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else None,
            'timeout': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else None,
            'nota': row[3] or '',
            'lunchsalida': row[4].strftime('%H:%M') if row[4] else None,
            'lunchentrada': row[5].strftime('%H:%M') if row[5] else None,
        })

    return jsonify({'registros': registros})

# ══════════════════════════════════════════════════════
#  EXPORTAR PDF — turn_in_laboral + turn_out_laboral
# ══════════════════════════════════════════════════════
from io import BytesIO
from datetime import datetime
from calendar import monthrange
from flask import request, redirect, url_for, flash, session, render_template, make_response

@main.route('/doc')
@login_required
def doc():
    return render_template('doc.html', current_year=date.today().year)

@main.route('/exportar-asistencia-pdf', methods=['POST'])
@login_required
def exportar_asistencia_pdf():
  # 1. Validación de permisos
  if session.get('role') != 0:
    flash('No tienes permisos.', 'warning')
    return redirect(url_for('main.dashboard'))

  # 2. Captura y normalización de parámetros
  user_id = int(request.form.get('user_id', 0))
  mes = request.form.get('mes', '')
  añadir_20min = request.form.get('añadir_20min') == 'on'
  añadir_iniciales = request.form.get('añadir_iniciales') == 'on'

  if not mes or user_id == 0:
    flash('Datos de solicitud incompletos.', 'danger')
    return redirect(url_for('main.vacaciones'))

  year, month = map(int, mes.split('-'))
  primer_dia = f'{year}-{month:02d}-01'
  ultimo_dia_num = monthrange(year, month)[1]
  ultimo_dia = f'{year}-{month:02d}-{ultimo_dia_num}'

  # 3. Inicialización segura de variables
  total_minutos_ret = 0
  total_horas_ret = 0
  total_mins_ret = 0
  total_minutos_trab = 0

  cur = mysql.connection.cursor()

  # ── CONSULTAR FESTIVOS REGISTRADOS ──
  cur.execute('SELECT fecha FROM feriados')
  feriados_rows = cur.fetchall()
  feriados_set = {
      r[0].strftime('%Y-%m-%d') if hasattr(r[0], 'strftime') else str(r[0])
      for r in feriados_rows
  }

  # ── ASISTENCIA ──
  cur.execute(
      """
        SELECT DATE(til.timein) AS fecha, MIN(til.timein) AS entrada_manana, 
               tl.salida AS salida_comida, tl.entrada AS entrada_tarde, 
               MAX(tol.timeout) AS salida_tarde, 
               GROUP_CONCAT(DISTINCT til.nota SEPARATOR ' | ') AS notas
        FROM turn_in_laboral til
        LEFT JOIN turn_out_laboral tol ON til.iduser = tol.iduser AND DATE(til.timein) = DATE(tol.timeout)
        LEFT JOIN turn_lunch tl ON til.iduser = tl.iduser AND DATE(til.timein) = DATE(tl.salida)
        WHERE til.iduser = %s AND DATE(til.timein) BETWEEN %s AND %s
        GROUP BY DATE(til.timein), tl.salida, tl.entrada
        ORDER BY fecha
    """,
      (user_id, primer_dia, ultimo_dia),
  )
  registros = cur.fetchall()

  # ── HORAS RETRIBUIDAS ──
  cur.execute(
      """
        SELECT hr.fecha_inicio, hr.fecha_fin, hr.motivos, 
               TIMESTAMPDIFF(MINUTE, hr.fecha_inicio, hr.fecha_fin) AS minutos
        FROM horas_retribuidas hr
        WHERE hr.user_id = %s AND DATE_FORMAT(hr.fecha_inicio, '%%Y-%%m') = %s
        ORDER BY hr.fecha_inicio ASC
    """,
      (user_id, mes),
  )
  horas_ret = cur.fetchall()

  if horas_ret:
    total_minutos_ret = sum(r[3] for r in horas_ret if r[3] or 0)
    total_horas_ret = total_minutos_ret // 60
    total_mins_ret = total_minutos_ret % 60

  # ── VACACIONES (Filtradas sin fines de semana ni feriados) ──
  cur.execute(
      """
        SELECT vacacionesin, vacacionesout FROM vacaciones
        WHERE iduser = %s AND DATE(vacacionesin) <= %s AND DATE(vacacionesout) >= %s
        ORDER BY vacacionesin
    """,
      (user_id, ultimo_dia, primer_dia),
  )
  vacaciones_raw = cur.fetchall()

  vacaciones_mes = []
  for vin, vout in vacaciones_raw:
    if vin and vout:
      v_start = (
          vin
          if isinstance(vin, datetime)
          else datetime.strptime(str(vin), '%Y-%m-%d %H:%M:%S')
      )
      v_end = (
          vout
          if isinstance(vout, datetime)
          else datetime.strptime(str(vout), '%Y-%m-%d %H:%M:%S')
      )

      curr_date = v_start.date()
      end_date = v_end.date()

      # Recorrer día a día omitiendo fines de semana y feriados
      while curr_date <= end_date:
        es_fin_semana = curr_date.weekday() >= 5
        es_feriado = curr_date.strftime('%Y-%m-%d') in feriados_set

        if not es_fin_semana and not es_feriado:
          dt_inicio = (
              v_start
              if curr_date == v_start.date()
              else datetime.combine(curr_date, v_start.time())
          )
          dt_fin = (
              v_end
              if curr_date == v_end.date()
              else datetime.combine(curr_date, v_end.time())
          )
          vacaciones_mes.append((dt_inicio, dt_fin))

        curr_date += timedelta(days=1)

  # ── EMPLEADO ──
  cur.execute(
      'SELECT nombre, apellido, nif, nass FROM personas WHERE iduser = %s',
      (user_id,),
  )
  empleado = cur.fetchone()
  cur.close()

  # ── CALCULAR TOTAL TRABAJADAS ──
  for r in registros:
    if r[1] and r[4]:
      minutos_dia = int((r[4] - r[1]).total_seconds() // 60)
      if r[2] and r[3]:
        minutos_dia -= int((r[3] - r[2]).total_seconds() // 60)
      if minutos_dia > 0:
        total_minutos_trab += minutos_dia

  total_horas_trab = total_minutos_trab // 60
  total_mins_trab = total_minutos_trab % 60

  total_minutos_comp = total_minutos_trab + total_minutos_ret

  # 4. Render final con retorno obligatorio
  html = render_template(
      'pdf_asistencia.html',
      empleado=f'{empleado[0]} {empleado[1]}' if empleado else 'Desconocido',
      mes=f'{MESES_ES[month]} {year}',
      nif=empleado[2] if empleado else '',
      nass=empleado[3] if empleado else '',
      registros=registros,
      horas_ret=horas_ret,
      total_minutos_ret=total_minutos_ret,
      total_horas_ret=total_horas_ret,
      total_mins_ret=total_mins_ret,
      total_horas_trab=total_horas_trab,
      total_mins_trab=total_mins_trab,
      total_horas_comp=total_minutos_comp // 60,
      total_mins_comp=total_minutos_comp % 60,
      vacaciones_mes=vacaciones_mes,
      month=month,
      year=year,
      ultimo_dia_num=ultimo_dia_num,
      añadir_20min=añadir_20min,
      añadir_iniciales=añadir_iniciales,
  )

  pdf = BytesIO()
  pisa.CreatePDF(html, dest=pdf)

  response = make_response(pdf.getvalue())
  response.headers['Content-Type'] = 'application/pdf'
  response.headers['Content-Disposition'] = (
      f'attachment; filename=Registro-{mes}-{user_id}.pdf'
  )

  return response
# ══════════════════════════════════════════════════════
#  SALIDA A COMER
# ══════════════════════════════════════════════════════
@main.route('/lunch-out', methods=['GET', 'POST'])
@login_required
def lunch_out():
    

    if session.get('role') not in [0, 1]:
        flash('No tienes permisos.', 'warning')
        return redirect(url_for('main.dashboard'))

    cur = mysql.connection.cursor()
    salida_abierta = tiene_salida_comida_abierta(cur, session['user_id'])
    vuelta_hoy     = tiene_vuelta_comida_hoy(cur, session['user_id'])
    bloqueado      = salida_abierta or vuelta_hoy

    if request.method == 'POST':
        if bloqueado:
            if salida_abierta:
                flash('Ya tienes una salida a comer registrada. Registra la vuelta primero.', 'warning')
            else:
                flash('Ya completaste la pausa de comida hoy.', 'warning')
        else:
            hora_actual = obtener_hora_timeapi()
            cur.execute("INSERT INTO turn_lunch (iduser, salida) VALUES (%s, %s)", (session['user_id'], hora_actual))
            mysql.connection.commit()
            flash('¡Salida a comer registrada!', 'success')
        cur.close()
        return redirect(url_for('main.dashboard'))

    cur.close()
    return render_template('lunch_out.html', bloqueado=bloqueado,
                           salida_abierta=salida_abierta, vuelta_hoy=vuelta_hoy)


# ══════════════════════════════════════════════════════
#  VUELTA DE COMER
# ══════════════════════════════════════════════════════
@main.route('/lunch-in', methods=['GET', 'POST'])
@login_required
def lunch_in():
    

    if session.get('role') not in [0, 1]:
        flash('No tienes permisos.', 'warning')
        return redirect(url_for('main.dashboard'))

    cur = mysql.connection.cursor()
    salida_abierta = tiene_salida_comida_abierta(cur, session['user_id'])
    vuelta_hoy     = tiene_vuelta_comida_hoy(cur, session['user_id'])
    bloqueado      = not salida_abierta or vuelta_hoy

    if request.method == 'POST':
        if bloqueado:
            if vuelta_hoy:
                flash('Ya registraste la vuelta de comer hoy.', 'warning')
            else:
                flash('No tienes ninguna salida a comer registrada hoy.', 'warning')
        else:
            hora_actual = obtener_hora_timeapi()
            cur.execute("""
                UPDATE turn_lunch SET entrada = %s
                WHERE iduser = %s AND DATE(salida) = CURDATE() AND entrada IS NULL
            """, (hora_actual, session['user_id']))
            mysql.connection.commit()
            flash('¡Vuelta de comer registrada!', 'success')
        cur.close()
        return redirect(url_for('main.dashboard'))

    cur.close()
    return render_template('lunch_in.html', bloqueado=bloqueado,
                           salida_abierta=salida_abierta, vuelta_hoy=vuelta_hoy)


@main.route('/visitante', methods=['GET', 'POST'])
@login_required
def register_visitante():
    if request.method == 'POST':
        nombre   = request.form['nombre'].strip()
        apellido = request.form['apellido'].strip()
        nota     = request.form.get('nota', '').strip()

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO visitantes (nombre, apellido, entrada, nota)
            VALUES (%s, %s, NOW(), %s)
        """, (nombre, apellido, nota or None))
        mysql.connection.commit()
        cur.close()

        flash(f'Visitante {nombre} {apellido} registrado correctamente.', 'success')
        return redirect(url_for('main.register_visitante'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, nombre, apellido, entrada, salida, nota
        FROM visitantes
        WHERE DATE(entrada) = CURDATE()
        ORDER BY entrada DESC
    """)
    visitantes_hoy = cur.fetchall()
    cur.close()

    return render_template('register_visitante.html', visitantes=visitantes_hoy)


@main.route('/visitante/salida/<int:vid>', methods=['POST'])
@login_required
def visitante_salida(vid):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE visitantes SET salida = NOW() WHERE id = %s", (vid,))
    mysql.connection.commit()
    cur.close()
    flash('Salida del visitante registrada.', 'info')
    return redirect(url_for('main.register_visitante'))

@main.route('/visitantes/mes', methods=['POST'])
@login_required
def visitantes_mes():
    mes = request.form.get('mes')
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, nombre, apellido, entrada, salida, nota
        FROM visitantes
        WHERE DATE_FORMAT(entrada, '%%Y-%%m') = %s
        ORDER BY entrada ASC
    """, (mes,))
    resultado = cur.fetchall()

    # También carga visitantes de hoy para no perder la tabla superior
    cur.execute("""
        SELECT id, nombre, apellido, entrada, salida, nota
        FROM visitantes WHERE DATE(entrada) = CURDATE() ORDER BY entrada DESC
    """)
    visitantes_hoy = cur.fetchall()
    cur.close()

    return render_template('register_visitante.html',
        visitantes     = visitantes_hoy,
        visitantes_mes = resultado,
        mes            = mes
    )
from datetime import datetime

@main.route('/editar_visitante/<int:vid>', methods=['POST'])
@login_required
def editar_visitante(vid):
    # Obtener y limpiar los datos de texto del formulario
    nombre = request.form.get('nombre', '').strip()
    apellido = request.form.get('apellido', '').strip()
    nota = request.form.get('nota', '').strip()

    # Obtener los strings de fecha y hora
    entrada_raw = request.form.get('entrada', '').strip()
    salida_raw = request.form.get('salida', '').strip()

    # Procesar fecha de entrada (Obligatoria)
    entrada = None
    if entrada_raw:
        try:
            # HTML5 datetime-local usualmente envía: YYYY-MM-DDTHH:MM
            entrada = datetime.strptime(entrada_raw, '%Y-%m-%dT%H:%M')
        except ValueError:
            # En caso de que algún navegador incluya los segundos (:SS)
            entrada = datetime.strptime(entrada_raw, '%Y-%m-%dT%H:%M:%S')

    # Procesar fecha de salida (Opcional, puede ser None/NULL)
    salida = None
    if salida_raw:
        try:
            salida = datetime.strptime(salida_raw, '%Y-%m-%dT%H:%M')
        except ValueError:
            salida = datetime.strptime(salida_raw, '%Y-%m-%dT%H:%M:%S')

    # Actualizar el registro en la base de datos
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE visitantes 
        SET nombre = %s, apellido = %s, nota = %s, entrada = %s, salida = %s
        WHERE id = %s
    """, (nombre, apellido, nota or None, entrada, salida, vid))
    
    mysql.connection.commit()
    cur.close()

    # Enviar mensaje de éxito y redirigir a la vista principal de visitantes
    flash(f'El registro de {nombre} {apellido} ha sido actualizado con sus horarios.', 'success')
    return redirect(url_for('main.register_visitante'))

@main.route('/perfil', methods=['GET', 'POST'])
@main.route('/perfil/<int:target_id>', methods=['GET', 'POST'])
@login_required
def perfil(target_id=None):
    mi_depto = ''
    cur = mysql.connection.cursor()
    cur.execute("SELECT p.departamento FROM personas p WHERE p.iduser = %s", (session['user_id'],))
    r = cur.fetchone()
    mi_depto = (r[0] or '').lower() if r else ''

    es_it = (mi_depto == 'it')

    if target_id and not es_it:
        flash('No tienes permisos para editar otros perfiles.', 'warning')
        return redirect(url_for('main.perfil'))

    uid = target_id if target_id else session['user_id']

    todos_usuarios = []
    if es_it:
        cur.execute("""
            SELECT u.iduser, p.nombre, p.apellido, p.departamento
            FROM `user` u
            JOIN personas p ON u.iduser = p.iduser
            ORDER BY p.nombre
        """)
        todos_usuarios = cur.fetchall()

    if request.method == 'POST':
        nombre       = request.form['nombre'].strip()
        apellido     = request.form['apellido'].strip()
        correo       = request.form['correo'].strip()
        departamento = request.form['departamento'].strip()
        nueva_pass   = request.form.get('nueva_pass', '').strip()
        foto_file    = request.files.get('foto')

        cur.execute("""
            UPDATE personas
            SET nombre=%s, apellido=%s, correo=%s, departamento=%s
            WHERE iduser=%s
        """, (nombre, apellido, correo, departamento, uid))

        if foto_file and foto_file.filename and allowed_file(foto_file.filename):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            cur.execute("SELECT user FROM `user` WHERE iduser=%s", (uid,))
            urow = cur.fetchone()
            username_target = urow[0] if urow else str(uid)
            filename  = secure_filename(f"{username_target}_{foto_file.filename}")
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            foto_file.save(save_path)
            foto_path = f"img/usuarios/{filename}"
            cur.execute("UPDATE `user` SET foto=%s WHERE iduser=%s", (foto_path, uid))

        if nueva_pass:
            pass_hash = bcrypt.generate_password_hash(nueva_pass).decode('utf-8')
            cur.execute("UPDATE `user` SET pass=%s WHERE iduser=%s", (pass_hash, uid))

        mysql.connection.commit()
        flash('Perfil actualizado correctamente.', 'success')

        if target_id:
            return redirect(url_for('main.perfil', target_id=target_id))
        return redirect(url_for('main.perfil'))

    cur.execute("""
        SELECT u.user, u.foto, u.roles,
               p.nombre, p.apellido, p.correo, p.departamento
        FROM `user` u
        JOIN personas p ON u.iduser = p.iduser
        WHERE u.iduser = %s
    """, (uid,))
    datos = cur.fetchone()
    cur.close()

    if not datos:
        flash('Usuario no encontrado.', 'danger')
        return redirect(url_for('main.dashboard'))

    return render_template('perfil.html',
                           datos=datos,
                           uid=uid,
                           es_it=es_it,
                           todos_usuarios=todos_usuarios,
                           target_id=target_id)


@main.route('/directorio')
@login_required
def directorio():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT u.foto, p.departamento
        FROM `user` u
        JOIN personas p ON u.iduser = p.iduser
        WHERE u.iduser = %s
    """, (session.get('user_id'),))
    row = cur.fetchone()
    cur.close()
    user_foto         = row[0].strip().replace("\\", "/") if row and row[0] else None
    user_departamento = row[1] if row and row[1] else ''

    return render_template('directorio.html',
                           user=session.get('username'),
                           role=session.get('role'),
                           user_foto=user_foto,
                           departamento=user_departamento)


@main.route('/crear-usuarios-lote', methods=['GET', 'POST'])
@login_required
def crear_usuarios_lote():
    if session.get('role') != 0:
        flash('No tienes permisos para esta sección.', 'warning')
        return redirect(url_for('main.dashboard'))

    resultados = []

    if request.method == 'POST':
        lista_raw = request.form.get('lista_nombres', '').strip()
        lineas    = [l.strip() for l in lista_raw.splitlines() if l.strip()]

        cur = mysql.connection.cursor()

        for nombre_completo in lineas:
            partes   = nombre_completo.strip().split()
            if not partes:
                continue

            nombre   = partes[0]
            apellido = ' '.join(partes[1:]) if len(partes) > 1 else ''
            username = nombre.lower()
            password = '12345'
            pass_hash = bcrypt.generate_password_hash(password).decode('utf-8')

            cur.execute("SELECT iduser FROM `user` WHERE user = %s", (username,))
            existe = cur.fetchone()

            if existe:
                resultados.append({
                    'nombre':   nombre_completo,
                    'username': username,
                    'estado':   'warning',
                    'msg':      'Ya existe'
                })
                continue

            try:
                cur.execute("""
                    INSERT INTO `user` (user, pass, roles, foto)
                    VALUES (%s, %s, %s, NULL)
                """, (username, pass_hash, 1))
                new_id = cur.lastrowid

                cur.execute("""
                    INSERT INTO personas (iduser, nombre, apellido, correo, departamento)
                    VALUES (%s, %s, %s, NULL, NULL)
                """, (new_id, nombre, apellido))

                mysql.connection.commit()
                resultados.append({
                    'nombre':   nombre_completo,
                    'username': username,
                    'estado':   'success',
                    'msg':      'Creado correctamente'
                })
            except Exception as e:
                mysql.connection.rollback()
                resultados.append({
                    'nombre':   nombre_completo,
                    'username': username,
                    'estado':   'danger',
                    'msg':      f'Error: {str(e)}'
                })

        cur.close()

    return render_template('crear_usuarios_lote.html',
                           user=session.get('username'),
                           role=session.get('role'),
                           resultados=resultados,
                           user_foto=None,
                           departamento='')

@main.route('/it/equipos', methods=['GET', 'POST'])
@login_required
def inventario_equipos():
    cur = mysql.connection.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            # DEBUG FORM
            print("=== DEBUG ADD ===")
            print("nombre:", request.form.get('nombre_equipo'))
            print("usuario:", request.form.get('usuario'))
            print("serie:", request.form.get('numero_serie'))
            print("==================")
            
            cur.execute("""
                INSERT INTO equipos
                (nombre_equipo, usuario, modelo, fabricante, numero_serie, procesador, memoria_mb, disco_gb, observaciones)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('nombre_equipo'),
                request.form.get('usuario'),
                request.form.get('modelo'),
                request.form.get('fabricante'),
                request.form.get('numero_serie'),
                request.form.get('procesador'),
                request.form.get('memoria_mb') or None,
                request.form.get('disco_gb') or None,
                request.form.get('observaciones'),
            ))
            mysql.connection.commit()
            flash('Equipo añadido correctamente', 'success')
            
        elif action == 'delete':
            cur.execute("DELETE FROM equipos WHERE id = %s", (request.form.get('equipo_id'),))
            mysql.connection.commit()
            flash('Equipo eliminado', 'success')
        
        cur.close()
        return redirect(url_for('main.inventario_equipos'))
    
    # Tu método manual que funciona (optimizado)
    cur.execute("""
        SELECT id, nombre_equipo, usuario, modelo, fabricante, numero_serie, 
               procesador, memoria_mb, disco_gb, observaciones, fecha_registro 
        FROM equipos ORDER BY fecha_registro DESC
    """)
    columns = [col[0] for col in cur.description]  # ← Nombres columnas
    equipos = [dict(zip(columns, row)) for row in cur.fetchall()]
    cur.close()
    
    return render_template('inventario_equipos.html',
        equipos=equipos,
        current_year=datetime.now().year,
    )

    


# ══ RUTA /inventario_servidores (copia/pega en routes.py) ══
@main.route('/inventario_servidores')
@login_required
def inventario_servidores():
    try:
        cur = mysql.connection.cursor()
        
        # Todos los servidores para tabla
        cur.execute("""
            SELECT id, technology, server_name, hostname, ip_address, model, serial_number 
            FROM servidores 
            ORDER BY server_name
        """)
        columns = [col[0] for col in cur.description]
        servidores = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        # Stats para cards
        cur.execute("SELECT COUNT(*) FROM servidores")
        total_servidores = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM servidores WHERE technology='Física'")
        fisicos = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM servidores WHERE technology='Virtual'")
        virtuales = cur.fetchone()[0]
        
        cur.close()
        
        return render_template('inventario_servidores.html',
            servidores=servidores,
            total_servidores=total_servidores,
            fisicos=fisicos,
            virtuales=virtuales
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('inventario_servidores.html', 
                             servidores=[], total_servidores=0, fisicos=0, virtuales=0)

# ══ RUTAS CRUD POST (añade después de la principal) ══
@main.route('/inventario_servidores/add', methods=['POST'])
@login_required
def add_servidor():
    data = request.json
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO servidores (technology, server_name, hostname, ip_address, model, serial_number)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (data['technology'], data['server_name'], data['hostname'], 
              data['ip_address'], data['model'], data['serial_number']))
        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True, 'id': cur.lastrowid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@main.route('/inventario_servidores/update/<int:id>', methods=['POST'])
@login_required
def update_servidor(id):
    data = request.json
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE servidores SET 
                technology=%s, server_name=%s, hostname=%s, ip_address=%s, model=%s, serial_number=%s
            WHERE id=%s
        """, (data['technology'], data['server_name'], data['hostname'], 
              data['ip_address'], data['model'], data['serial_number'], id))
        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@main.route('/inventario_servidores/delete/<int:id>', methods=['POST'])
@login_required
def delete_servidor(id):
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM servidores WHERE id=%s", (id,))
        mysql.connection.commit()
        cur.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ══ RUTAS CRUD hORAS RETRIBUIDAS ══
from datetime import datetime

@main.route('/horas_retribuidas')
@login_required
def horas_retribuidas():
    try:
        cur = mysql.connection.cursor()

        cur.execute("""
            SELECT 
                hr.id,
                hr.user_id,
                hr.fecha_inicio,
                hr.fecha_fin,
                hr.motivos,
                u.username AS usuario
            FROM horas_retribuidas hr
            LEFT JOIN users u ON u.id = hr.user_id
            ORDER BY hr.fecha_inicio DESC
        """)
        horas = cur.fetchall()

        cur.close()
        return render_template('horas_retribuidas.html', horas=horas)

    except Exception as e:
        return render_template('horas_retribuidas.html', horas=[], error=str(e))
    

# ══ RUTAS ADD hORAS RETRIBUIDAS ══    
@main.route('/horas_retribuidas/add', methods=['POST'])
@login_required
def add_horas_retribuidas():
    data = request.get_json()

    try:
        user_id = data.get('user_id')
        fecha_inicio = data.get('fecha_inicio')
        fecha_fin = data.get('fecha_fin')
        motivos = data.get('motivos', '').strip()

        if not user_id or not fecha_inicio or not fecha_fin:
            return jsonify({'success': False, 'error': 'Faltan campos obligatorios'}), 400

        dt_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%dT%H:%M')
        dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%dT%H:%M')

        if dt_fin <= dt_inicio:
            return jsonify({'success': False, 'error': 'La fecha fin debe ser mayor que la fecha inicio'}), 400

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO horas_retribuidas (user_id, fecha_inicio, fecha_fin, motivos)
            VALUES (%s, %s, %s, %s)
        """, (user_id, dt_inicio, dt_fin, motivos))
        mysql.connection.commit()
        cur.close()

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ══ RUTAS DELETE hORAS RETRIBUIDAS ══
@main.route('/horas_retribuidas/delete/<int:id>', methods=['POST'])
@login_required
def delete_horas_retribuidas(id):
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM horas_retribuidas WHERE id = %s", (id,))
        mysql.connection.commit()
        cur.close()

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
# ══ RUTAS DELETE hORAS RETRIBUIDAS ══
@main.route('/horas_retribuidas/update/<int:id>', methods=['POST'])
@login_required
def update_horas_retribuidas(id):
    data = request.get_json()

    try:
        user_id = data.get('user_id')
        fecha_inicio = data.get('fecha_inicio')
        fecha_fin = data.get('fecha_fin')
        motivos = data.get('motivos', '').strip()

        if not user_id or not fecha_inicio or not fecha_fin:
            return jsonify({'success': False, 'error': 'Faltan campos obligatorios'}), 400

        dt_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%dT%H:%M')
        dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%dT%H:%M')

        if dt_fin <= dt_inicio:
            return jsonify({'success': False, 'error': 'La fecha fin debe ser mayor que la fecha inicio'}), 400

        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE horas_retribuidas
            SET userid = %s,
                fecha_inicio = %s,
                fecha_fin = %s,
                motivos = %s
            WHERE id = %s
        """, (user_id, dt_inicio, dt_fin, motivos, id))
        mysql.connection.commit()
        cur.close()

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@main.route('/admin/usuarios-eliminados')
@login_required
def admin_usuarios_gestion():
    if session.get('role') != 0:
        flash('Sin permisos.', 'warning')
        return redirect(url_for('main.dashboard'))

    cur = mysql.connection.cursor()

    # Usuarios activos
    cur.execute("""
        SELECT iduser, nombre, apellido, correo, departamento, nif, nass
        FROM personas
        ORDER BY nombre ASC
    """)
    activos = cur.fetchall()

    # Usuarios eliminados
    cur.execute("""
        SELECT iduser, nombre, apellido, correo, departamento, nif, nass,
               eliminado_fecha, eliminado_motivo
        FROM usuarios_eliminados
        ORDER BY eliminado_fecha DESC
    """)
    eliminados = cur.fetchall()
    cur.close()

    return render_template('admin_usuarios_gestion.html',
                           activos=activos,
                           eliminados=eliminados)


@main.route('/admin/eliminar-usuario', methods=['POST'])
@login_required
def eliminar_usuario():
    if session.get('role') != 0:
        flash('Sin permisos.', 'warning')
        return redirect(url_for('main.dashboard'))

    user_id = request.form.get('user_id')
    motivo  = request.form.get('motivo', '').strip()

    cur = mysql.connection.cursor()

    # Mover a usuarios_eliminados
    cur.execute("""
        INSERT INTO usuarios_eliminados
            (iduser, nombre, apellido, correo, departamento, nif, nass,
             eliminado_por, eliminado_fecha, eliminado_motivo)
        SELECT iduser, nombre, apellido, correo, departamento, nif, nass,
               %s, NOW(), %s
        FROM personas WHERE iduser = %s
    """, (session['user_id'], motivo, user_id))

    # Borrar de personas
    cur.execute("DELETE FROM personas WHERE iduser = %s", (user_id,))

    mysql.connection.commit()
    cur.close()

    flash('Usuario eliminado correctamente.', 'success')
    return redirect(url_for('main.admin_usuarios_gestion'))


from datetime import datetime

@main.route('/hora-servidor')
def hora_servidor():
    return jsonify({
        'hora': datetime.now().strftime('%H:%M:%S'),
        'fecha': datetime.now().strftime('%Y-%m-%d')
    })

@main.route('/admin/restaurar-usuario', methods=['POST'])
@login_required
def restaurar_usuario():
    if session.get('role') != 0:
        flash('Sin permisos.', 'warning')
        return redirect(url_for('main.dashboard'))

    user_id = request.form.get('user_id')

    cur = mysql.connection.cursor()

    # Restaurar a personas
    cur.execute("""
        INSERT INTO personas
            (iduser, nombre, apellido, correo, departamento, nif, nass)
        SELECT iduser, nombre, apellido, correo, departamento, nif, nass
        FROM usuarios_eliminados WHERE iduser = %s
    """, (user_id,))

    # Borrar de eliminados
    cur.execute("DELETE FROM usuarios_eliminados WHERE iduser = %s", (user_id,))

    mysql.connection.commit()
    cur.close()

    flash('Usuario restaurado correctamente.', 'success')
    return redirect(url_for('main.admin_usuarios_gestion'))




@main.route('/logout')
@login_required
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('main.login'))
