# turno/app/models.py
import requests
from datetime import datetime
from zoneinfo import ZoneInfo


def obtener_hora_timeapi():
    ahora = datetime.now(
        ZoneInfo("Europe/Madrid")
    )

    return ahora.strftime("%Y-%m-%d %H:%M:%S")

def get_user_by_username(cursor, username):
    """
    Devuelve una tupla (iduser, user, pass_hash, roles) o None.
    roles es un entero (0=admin, 1=usuario).
    """
    sql = "SELECT iduser, user, pass, roles FROM user WHERE user = %s"
    cursor.execute(sql, (username,))
    return cursor.fetchone()


def record_timein(cursor, user_id):
    """
    Inserta en turn_in (iduser, timein) la hora actual.
    """
    hora_actual = obtener_hora_timeapi()
    sql = "INSERT INTO turn_in (iduser, timein) VALUES (%s, %s)"
    cursor.execute(sql, (user_id,hora_actual))


def record_timeout(cursor, user_id):
    """
    Inserta en turn_out (iduser, timeout) la hora actual.
    """
    hora_actual = obtener_hora_timeapi()
    sql = "INSERT INTO turn_out (iduser, timeout) VALUES (%s, %s)"
    cursor.execute(sql, (user_id,hora_actual))


def insert_user(cursor, username, pass_hash, role=1, foto=None):
    """
    Inserta un nuevo usuario en la tabla `user` con foto opcional.
    Devuelve el id generado.
    """
    sql = "INSERT INTO `user` (`user`, `pass`, `roles`, `foto`) VALUES (%s, %s, %s, %s)"
    cursor.execute(sql, (username, pass_hash, role, foto))
    return cursor.lastrowid


def insert_persona(cursor, iduser, nombre, apellidos, correo, departamento):
    """
    Inserta los datos personales en la tabla `personas`.
    """
    sql = """
      INSERT INTO personas
        (iduser, nombre, apellido, correo, departamento)
      VALUES (%s, %s, %s, %s, %s)
    """
    cursor.execute(sql, (iduser, nombre, apellidos, correo, departamento))


def get_persona(cursor, user_id):
    """
    Devuelve (nombre, apellido) de la tabla personas para el usuario dado.
    """
    sql = "SELECT nombre, apellido FROM personas WHERE iduser = %s"
    cursor.execute(sql, (user_id,))
    return cursor.fetchone()


def get_vacaciones(cursor, user_id):
    """
    Devuelve una lista de tuplas (vacacionesin, vacacionesout) para el usuario.
    """
    sql = "SELECT vacacionesin, vacacionesout FROM vacaciones WHERE iduser = %s"
    cursor.execute(sql, (user_id,))
    return cursor.fetchall()


def insert_vacaciones(cursor, user_id, vac_in, vac_out):
    """
    Inserta un registro de vacaciones para el usuario.
    """
    sql = """
      INSERT INTO vacaciones (iduser, vacacionesin, vacacionesout)
      VALUES (%s, %s, %s)
    """
    cursor.execute(sql, (user_id, vac_in, vac_out))


def delete_vacaciones(cursor, user_id, vac_in, vac_out):
    """
    Elimina el registro específico de vacaciones.
    """
    sql = """
      DELETE FROM vacaciones
      WHERE iduser = %s AND vacacionesin = %s AND vacacionesout = %s
    """
    cursor.execute(sql, (user_id, vac_in, vac_out))


def get_persona_detail(cursor, user_id):
    """
    Devuelve (nombre, apellido, departamento) para el usuario dado.
    """
    cursor.execute(
        "SELECT nombre, apellido, departamento FROM personas WHERE iduser = %s",
        (user_id,)
    )
    return cursor.fetchone()


def get_personas_by_department(cursor, dept):
    """
    IT y Administración ven todos los empleados.
    El resto solo ve su propio departamento.
    """
    dept_lower = (dept or '').lower()
    if dept_lower in ['it', 'administración', 'administracion']:
        cursor.execute("""
            SELECT u.iduser, p.nombre, p.apellido, p.departamento
            FROM `user` u
            JOIN personas p ON u.iduser = p.iduser
            ORDER BY p.departamento, p.nombre
        """)
    else:
        cursor.execute("""
            SELECT u.iduser, p.nombre, p.apellido, p.departamento
            FROM `user` u
            JOIN personas p ON u.iduser = p.iduser
            WHERE LOWER(p.departamento) = %s
            ORDER BY p.nombre
        """, (dept_lower,))
    return cursor.fetchall()



def get_attendance(cursor, user_id, fecha_desde, limit=30):
    """
    Obtiene hasta `limit` registros de (timein, timeout)
    para la fecha exacta indicada.
    """
    cursor.execute(
        """
        SELECT timein
          FROM turn_in
         WHERE iduser = %s
           AND DATE(timein) = %s
         ORDER BY timein
         LIMIT %s
        """,
        (user_id, fecha_desde, limit)
    )
    timeins = [row[0] for row in cursor.fetchall()]

    attendance = []
    for ti in timeins:
        cursor.execute(
            """
            SELECT timeout
              FROM turn_out
             WHERE iduser = %s
               AND timeout >= %s
             ORDER BY timeout
             LIMIT 1
            """,
            (user_id, ti)
        )
        row = cursor.fetchone()
        to = row[0] if row else None
        attendance.append((ti, to))

    return attendance


def get_attendance_mes(cursor, user_id, primer_dia, ultimo_dia, limit=100):
    """
    Obtiene registros (timein, timeout) de un mes completo.
    Usado para exportar PDF mensual.
    """
    cursor.execute(
        """
        SELECT timein
          FROM turn_in
         WHERE iduser = %s
           AND DATE(timein) BETWEEN %s AND %s
         ORDER BY timein
         LIMIT %s
        """,
        (user_id, primer_dia, ultimo_dia, limit)
    )
    timeins = [row[0] for row in cursor.fetchall()]

    attendance = []
    for ti in timeins:
        cursor.execute(
            """
            SELECT timeout
              FROM turn_out
             WHERE iduser = %s
               AND timeout >= %s
             ORDER BY timeout
             LIMIT 1
            """,
            (user_id, ti)
        )
        row = cursor.fetchone()
        to = row[0] if row else None
        attendance.append((ti, to))

    return attendance


def get_vacaciones_from_date(cursor, user_id, fecha_desde):
    """
    Lista las vacaciones programadas (in/out) a partir de `fecha_desde`.
    """
    cursor.execute(
        """
        SELECT vacacionesin, vacacionesout
          FROM vacaciones
         WHERE iduser = %s
           AND vacacionesin >= %s
         ORDER BY vacacionesin
         LIMIT 30
        """,
        (user_id, fecha_desde)
    )
    return cursor.fetchall()


def get_user_foto(cursor, user_id):
    """
    Devuelve la ruta de la foto del usuario o None si no tiene.
    """
    cursor.execute(
        "SELECT foto FROM `user` WHERE iduser = %s",
        (user_id,)
    )
    row = cursor.fetchone()
    return row[0] if row else None
# ══════════════════════════════════════════════════════
#  CONTROL HORARIO
# ══════════════════════════════════════════════════════

def record_timein_laboral(cursor, user_id):
    """Inserta entrada en turn_in_laboral."""
    hora_actual = obtener_hora_timeapi()
    sql = "INSERT INTO turn_in_laboral (iduser, timein) VALUES (%s, %s)"
    cursor.execute(sql, (user_id,hora_actual))

def tiene_entrada_laboral_hoy(cursor, user_id):
    """
    Devuelve True si el usuario ya tiene algún registro
    en turn_in_laboral con fecha de hoy.
    """
    cursor.execute("""
        SELECT id FROM turn_in_laboral
        WHERE iduser = %s AND DATE(timein) = CURDATE()
        LIMIT 1
    """, (user_id,))
    return cursor.fetchone() is not None

def tiene_entrada_abierta_presencia(cursor, user_id):
    """
    Devuelve True si el usuario tiene una entrada HOY
    cuya hora es POSTERIOR a la última salida registrada hoy,
    o si tiene entrada pero ninguna salida en todo el día.
    """
    # Última entrada de hoy
    cursor.execute("""
        SELECT timein FROM turn_in
        WHERE iduser = %s AND DATE(timein) = CURDATE()
        ORDER BY timein DESC
        LIMIT 1
    """, (user_id,))
    ultima_entrada = cursor.fetchone()

    if not ultima_entrada:
        return False  # No hay entrada hoy → botón activo

    # Última salida de hoy
    cursor.execute("""
        SELECT timeout FROM turn_out
        WHERE iduser = %s AND DATE(timeout) = CURDATE()
        ORDER BY timeout DESC
        LIMIT 1
    """, (user_id,))
    ultima_salida = cursor.fetchone()

    if not ultima_salida:
        return True  # Hay entrada pero no salida → botón bloqueado

    # Si la última entrada es POSTERIOR a la última salida → bloqueado
    return ultima_entrada[0] > ultima_salida[0]
def tiene_salida_comida_abierta(cursor, user_id):
    """
    Devuelve True si hay una salida a comer hoy sin vuelta registrada.
    → bloquea el botón de 'Salida a Comer' y activa el de 'Vuelta de Comer'
    """
    cursor.execute("""
        SELECT id FROM turn_lunch
        WHERE iduser = %s AND DATE(salida) = CURDATE() AND entrada IS NULL
        LIMIT 1
    """, (user_id,))
    return cursor.fetchone() is not None

def tiene_vuelta_comida_hoy(cursor, user_id):
    """
    Devuelve True si ya completó el ciclo de comida hoy (salida + vuelta).
    → bloquea el botón de 'Vuelta de Comer' si ya volvió
    """
    cursor.execute("""
        SELECT id FROM turn_lunch
        WHERE iduser = %s AND DATE(salida) = CURDATE() AND entrada IS NOT NULL
        LIMIT 1
    """, (user_id,))
    return cursor.fetchone() is not None

def record_timeout_laboral(cursor, user_id):
    hora_actual = obtener_hora_timeapi()
    cursor.execute("""
   
        INSERT INTO turn_out_laboral (iduser, timeout)
        VALUES (%s, %s)
    """, (user_id, hora_actual))

def tiene_salida_laboral_hoy(cursor, user_id):
    cursor.execute("""
        SELECT id FROM turn_out_laboral
        WHERE iduser = %s AND DATE(timeout) = CURDATE()
        LIMIT 1
    """, (user_id,))
    return cursor.fetchone() is not None

