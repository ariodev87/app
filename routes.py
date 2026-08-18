# turno/app/routes.py
from datetime import date
from flask import make_response, jsonify
from xhtml2pdf import pisa
from io import BytesIO
from calendar import monthrange
import calendar as cal_module
import os
import requests
from werkzeug.utils import secure_filename

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash,jsonify,current_app
)
from app import mysql, bcrypt
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

@main.route('/hora-api', methods=['GET'])
def hora_api():
    try:
        respuesta = requests.get(
            'https://timeapi.io/api/Time/current/zone',
            params={
                'timeZone': 'Europe/Madrid'
            },
            timeout=5
        )

        respuesta.raise_for_status()
        datos = respuesta.json()

        current_app.logger.info(
            'Respuesta recibida de TimeAPI: %s',
            datos
        )

        fecha_hora = datos.get('dateTime', '')
        hora = datos.get('time', '')

        if not fecha_hora or not hora:
            return jsonify({
                'error': 'La API no devolvió una fecha o una hora válida'
            }), 502

        # TimeAPI puede devolver HH:MM; aseguramos HH:MM:SS.
        if hora.count(':') == 1:
            hora = f'{hora}:00'

        return jsonify({
            'hora': hora,
            'fecha': fecha_hora[:10],
            'zona_horaria': datos.get(
                'timeZone',
                'Europe/Madrid'
            )
        })

    except requests.Timeout:
        current_app.logger.error(
            'TimeAPI agotó el tiempo de espera'
        )

        return jsonify({
            'error': 'La API de hora tardó demasiado en responder'
        }), 504

    except requests.RequestException as error:
        current_app.logger.error(
            'Error consultando TimeAPI: %s',
            error
        )

        return jsonify({
            'error': 'No se pudo consultar la API de hora'
        }), 503

    except (ValueError, TypeError, KeyError) as error:
        current_app.logger.error(
            'Respuesta no válida de TimeAPI: %s',
            error
        )

        return jsonify({
            'error': 'La respuesta de TimeAPI no tiene el formato esperado'
        }), 502
@main.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['user']
        password = request.form['password']

        cur = mysql.connection.cursor()
        user = get_user_by_username(cur, username)
        cur.close()

        if user and bcrypt.check_password_hash(user[2], password):
            session.clear()
            session['user_id']  = user[0]
            session['username'] = user[1]
            session['role']     = int(user[3])
            return redirect(url_for('main.dashboard'))
        else:
            error = 'Usuario o contraseña incorrectos.'

    return render_template('login.html', error=error, titulo='Iniciar Sesión')


@main.route('/dashboard')
@login_required
def dashboard():
    cur = mysql.connection.cursor()
    hoy = date.today().strftime('%Y-%m-%d')
    tiempos_hoy = get_attendance(cur, session.get('user_id'), hoy)

    anio = date.today().year
    cur.execute("""
        SELECT vacacionesin, vacacionesout,idvac
        FROM vacaciones
        WHERE iduser = %s
          AND YEAR(vacacionesin) = %s
        ORDER BY vacacionesin
    """, (session.get('user_id'), anio))
    vacaciones_anio = cur.fetchall()

    cur.execute("""
        SELECT u.foto, p.departamento
        FROM `user` u
        JOIN personas p ON u.iduser = p.iduser
        WHERE u.iduser = %s
    """, (session.get('user_id'),))
    row = cur.fetchone()
    user_foto         = row[0].strip().replace("\\", "/") if row and row[0] else None
    user_departamento = row[1] if row and row[1] else ''

    cur.execute("""
        SELECT titulo, noticia, created_at
        FROM noticias
        ORDER BY created_at DESC
        LIMIT 2
    """)
    noticias = cur.fetchall()

    cur.execute("""
        SELECT salida, entrada
        FROM turn_lunch
        WHERE iduser = %s AND DATE(salida) = CURDATE()
        ORDER BY salida DESC LIMIT 1
    """, (session.get('user_id'),))
    lunch_hoy = cur.fetchone()

    cur.execute("""
        SELECT timein
        FROM turn_in_laboral
        WHERE iduser = %s AND DATE(timein) = CURDATE()
        ORDER BY timein ASC
        LIMIT 1
    """, (session.get('user_id'),))
    row_laboral = cur.fetchone()
    entrada_laboral_hoy = row_laboral[0] if row_laboral else None

    cur.close()
    return render_template('dashboard.html',
                           user=session.get('username'),
                           role=session.get('role'),
                           tiempos_hoy=tiempos_hoy,
                           vacaciones_anio=vacaciones_anio,
                           user_foto=user_foto,
                           noticias=noticias,
                           lunch_hoy=lunch_hoy,
                           entrada_laboral_hoy=entrada_laboral_hoy,
                           departamento=user_departamento,
                           current_year=anio)

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


@main.route('/vacaciones', methods=['GET', 'POST'])
@main.route('/vacaciones/<int:uid>', methods=['GET', 'POST'])  # ← ruta extra con uid
@login_required
def vacaciones(uid=None):
    if session.get('role') not in (0, 1):
        flash('No tienes permisos para esta sección.', 'warning')
        return redirect(url_for('main.dashboard'))

    # Si uid viene en la URL y quien lo pide es admin/supervisor → usa ese uid
    # Si no → usa el usuario logueado
    target_user = uid if (uid and session.get('role') in (0, 1)) else session['user_id']

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        vac_in  = request.form.get('vacacionesin')
        vac_out = request.form.get('vacacionesout')
        insert_vacaciones(cur, target_user, vac_in, vac_out)
        mysql.connection.commit()
        flash('Vacaciones registradas correctamente.', 'success')
        return redirect(url_for('main.vacaciones', uid=uid) if uid else url_for('main.vacaciones'))

    nombre, apellido = get_persona(cur, target_user)

    cur.execute("""
        SELECT vacacionesin, vacacionesout, idvac
        FROM vacaciones
        WHERE iduser = %s
        ORDER BY vacacionesin DESC
    """, (target_user,))
    lista_vacs = cur.fetchall()
    cur.close()

    return render_template(
        'register_vacaciones.html',
        nombre=nombre,
        apellido=apellido,
        vacaciones=lista_vacs,
        current_year=date.today().year,
        target_user=target_user  # ← para que editar/eliminar sepa a quién apunta
    )

@main.route('/editar-vacacion', methods=['POST'])
@login_required
def editar_vacacion():
    vacacion_id = request.form.get('vacacion_id')
    fecha_in    = request.form.get('vacacionesin')
    fecha_out   = request.form.get('vacacionesout')

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE vacaciones
        SET vacacionesin = %s, vacacionesout = %s
        WHERE idvac = %s 
    """, (fecha_in, fecha_out, vacacion_id,))
    mysql.connection.commit()
    cur.close()

    flash('Vacación actualizada correctamente.', 'success')
    return redirect(url_for('main.vacaciones'))


@main.route('/vacaciones/delete', methods=['POST'])
@login_required
def delete_vacacion():
    if session.get('role') not in (0, 1):
        flash('No tienes permisos para esta sección.', 'warning')
        return redirect(url_for('main.dashboard'))

    vacacion_id = request.form.get('vacacion_id')

    cur = mysql.connection.cursor()
    cur.execute("""
        DELETE FROM vacaciones
        WHERE idvac = %s 
    """, (vacacion_id,))
    mysql.connection.commit()
    cur.close()

    flash('Vacación eliminada.', 'info')
    return redirect(url_for('main.vacaciones'))


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
    primer_dia = f"{year}-{month:02d}-01"
    ultimo_dia_num = monthrange(year, month)[1]
    ultimo_dia = f"{year}-{month:02d}-{ultimo_dia_num}"

    # 3. Inicialización segura de variables
    total_minutos_ret = 0
    total_horas_ret = 0
    total_mins_ret = 0
    total_minutos_trab = 0
    
    cur = mysql.connection.cursor()

    # ── ASISTENCIA ──
    cur.execute("""
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
    """, (user_id, primer_dia, ultimo_dia))
    registros = cur.fetchall()

    # ── HORAS RETRIBUIDAS ──
    cur.execute("""
        SELECT hr.fecha_inicio, hr.fecha_fin, hr.motivos, 
               TIMESTAMPDIFF(MINUTE, hr.fecha_inicio, hr.fecha_fin) AS minutos
        FROM horas_retribuidas hr
        WHERE hr.user_id = %s AND DATE_FORMAT(hr.fecha_inicio, '%%Y-%%m') = %s
        ORDER BY hr.fecha_inicio ASC
    """, (user_id, mes))
    horas_ret = cur.fetchall()
    
    if horas_ret:
        total_minutos_ret = sum(r[3] for r in horas_ret if r[3] or 0)
        total_horas_ret = total_minutos_ret // 60
        total_mins_ret = total_minutos_ret % 60

    # ── VACACIONES (Normalizadas) ──
    cur.execute("""
        SELECT vacacionesin, vacacionesout FROM vacaciones
        WHERE iduser = %s AND DATE(vacacionesin) <= %s AND DATE(vacacionesout) >= %s
        ORDER BY vacacionesin
    """, (user_id, ultimo_dia, primer_dia))
    vacaciones_raw = cur.fetchall()
    
    vacaciones_mes = []
    for vin, vout in vacaciones_raw:
        if vin and vout:
            v_start = vin if isinstance(vin, datetime) else datetime.strptime(str(vin), '%Y-%m-%d %H:%M:%S')
            v_end = vout if isinstance(vout, datetime) else datetime.strptime(str(vout), '%Y-%m-%d %H:%M:%S')
            vacaciones_mes.append((v_start, v_end))

    # ── EMPLEADO ──
    cur.execute("SELECT nombre, apellido, nif, nass FROM personas WHERE iduser = %s", (user_id,))
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
        empleado=f"{empleado[0]} {empleado[1]}" if empleado else "Desconocido",
        mes=f"{MESES_ES[month]} {year}",
        nif=empleado[2] if empleado else "",      # ← NUEVO: Pasamos el NIF
        nass=empleado[3] if empleado else "",
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
        añadir_20min=añadir_20min,        # ← ESTO FALTABA
        añadir_iniciales=añadir_iniciales  # ← ESTO FALTABA
    )

    pdf = BytesIO()
    pisa.CreatePDF(html, dest=pdf)
    
    response = make_response(pdf.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Registro-{mes}-{user_id}.pdf'
    
    return response # <--- ESTO ASEGURA QUE LA FUNCIÓN SIEMPRE DEVUELVA ALGO
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
