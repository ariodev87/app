================================================================================

TURNOAPP — SISTEMA DE CONTROL DE ASISTENCIA, TURNOS, VACACIONES E INVENTARIO IT

================================================================================



TurnoApp es una plataforma web autoalojable (self-hosted) y de código abierto

diseñada para facilitar la gestión operativa diaria de pequeñas y medianas

empresas. Permite centralizar el registro de jornada laboral, la administración

de turnos y vacaciones por departamento, y el control de equipamiento IT en

una interfaz moderna, ligera y segura.



--------------------------------------------------------------------------------

1. CARACTERÍSTICAS PRINCIPALES

--------------------------------------------------------------------------------



[ Control Horario y Asistencia ]

- Registro de fichajes en tiempo real (entrada, pausa de comida y salida).

- Reloj sincronizado directamente con la hora oficial del servidor (/hora-api).

- Solicitud y aprobación supervisada de correcciones de fichajes olvidados.

- Registro y control de horas retribuidas y ausencias justificadas.

- Exportación directa de reportes mensuales de asistencia en formato PDF.



[ Gestión de Vacaciones y Cobertura ]

- Solicitud de vacaciones por días completos o medias jornadas (< 7 horas = 0.5 d).

- Cálculo automático de saldos anuales: Cupo Anual, Disfrutados, Aprobados,

  En Revisión y Días Disponibles por solicitar.

- Descuento inteligente solo de días hábiles (excluye fines de semana y días

  festivos/feriados configurados en la base de datos).

- Panel de Supervisión con:

  * Matriz visual de cobertura mensual por empleado y departamento.

  * Bandeja rápida de solicitudes pendientes de aprobación o rechazo.

  * Resumen de saldos del equipo con filtro histórico por año.



[ Roles, Departamentos y Seguridad ]

- Control de acceso basado en roles y departamentos (Empleados, Supervisores,

  Administradores y departamento IT).

- Modo consulta (solo lectura) y reglas de aprobación diferenciadas por equipo.

- Gestión de perfiles de usuario con fotografía de avatar y respaldo automático

  con iniciales.



[ Operaciones y Utilidades Adicionales ]

- Módulo de gestión e inventario de equipamiento y activos IT.

- Notificaciones por correo electrónico sobre estados de solicitudes.

- Soporte preparado para copias de seguridad automatizadas en red (SMB / Cron).



--------------------------------------------------------------------------------

2. STACK TECNOLÓGICO

--------------------------------------------------------------------------------



- Backend:       Python 3.10+, Flask

- Base de Datos: MySQL / MariaDB

- Frontend:      HTML5, CSS3, Bootstrap 5, Bootstrap Icons, JavaScript (ES6+)

- Plantillas:    Jinja2

- Integraciones: API Open-Meteo (clima en pantalla de acceso), Typed.js



--------------------------------------------------------------------------------

3. REQUISITOS PREVIOS

--------------------------------------------------------------------------------



Antes de instalar TurnoApp en tu servidor o entorno local, asegúrate de contar con:

- Python 3.10 o superior

- Servidor MySQL 8.0+ o MariaDB 10.5+

- pip y virtualenv (recomendado)

- Git



--------------------------------------------------------------------------------

4. INSTALACIÓN Y CONFIGURACIÓN

--------------------------------------------------------------------------------



Paso 1: Clonar el repositorio

    git clone https://github.com/TU_USUARIO/turnoapp.git

    cd turnoapp



Paso 2: Crear y activar el entorno virtual

    python3 -m venv venv

    source venv/bin/activate        # En Linux / macOS

    venv\Scripts\activate           # En Windows



Paso 3: Instalar dependencias

    pip install -r requirements.txt



Paso 4: Configurar variables de entorno

    Crea un archivo .env en la raíz del proyecto (o ajusta config.py) con tus

    credenciales de base de datos, clave secreta y correo SMTP:



    SECRET_KEY=tu_clave_secreta_segura

    MYSQL_HOST=localhost

    MYSQL_USER=tu_usuario_mysql

    MYSQL_PASSWORD=tu_password_mysql

    MYSQL_DB=turnoapp_db

    MAIL_SERVER=smtp.tudominio.com

    MAIL_PORT=587

    MAIL_USERNAME=notificaciones@tudominio.com

    MAIL_PASSWORD=tu_password_correo



Paso 5: Inicializar la base de datos

    Importa el esquema SQL inicial en tu servidor MySQL/MariaDB:

    mysql -u tu_usuario_mysql -p turnoapp_db < database/schema.sql



Paso 6: Ejecutar la aplicación

    python run.py



    La aplicación estará disponible en: http://localhost:5000



--------------------------------------------------------------------------------

5. ESTRUCTURA DEL PROYECTO

--------------------------------------------------------------------------------



turnoapp/

├── turno/

│   └── app/

│       ├── static/

│       │   ├── css/             # Hojas de estilo (sidebar, componentes)

│       │   ├── img/             # Recursos gráficos y fondos

│       │   └── uploads/

│       │       └── profiles/    # Fotos de perfil de empleados

│       ├── templates/

│       │   ├── _sidebar.html    # Barra de navegación lateral

│       │   ├── login.html       # Pantalla de inicio de sesión

│       │   ├── vacaciones.html  # Panel de solicitudes del empleado

│       │   └── gestion_vacaciones.html  # Panel de supervisión y saldos

│       ├── routes.py            # Rutas principales y lógica de negocio

│       └── __init__.py          # Inicialización de la app Flask

├── config.py                    # Configuración general y variables de entorno

├── requirements.txt             # Dependencias de Python

├── run.py                       # Punto de entrada de la aplicación

└── README.txt                   # Documentación del proyecto



--------------------------------------------------------------------------------

6. HOJA DE RUTA (ROADMAP)

--------------------------------------------------------------------------------



- [ ] Notificaciones Web Push mediante Service Workers y VAPID para recordatorios

      automáticos de fichaje de entrada y salida.

- [ ] Contenedorización oficial con Docker y Docker Compose.

- [ ] Módulo de gestión de bajas médicas y permisos especiales con adjuntos.

- [ ] Registro de auditoría (Audit Logs) para trazabilidad de aprobaciones.

- [ ] Suite de pruebas automatizadas (Pytest) para cálculo de saldos y festivos.



--------------------------------------------------------------------------------

7. CONTRIBUCIONES Y LICENCIA

--------------------------------------------------------------------------------



Las contribuciones, reportes de errores (Issues) y sugerencias de mejora

(Pull Requests) son bienvenidos. Para cambios importantes, abre primero un

Issue para discutir la propuesta.



Este proyecto se distribuye bajo la licencia MIT. Consulta el archivo LICENSE

para más detalles.



Desarrollado por Ariel Castro.

================================================================================
