// Intervalo que comprueba la hora cada minuto
let notifEnviada = false;

setInterval(() => {
  const ahora = new Date();
  const horas   = ahora.getHours();
  const minutos = ahora.getMinutes();

  // Resetea el flag a medianoche para que funcione cada día
  if (horas === 0 && minutos === 0) {
    notifEnviada = false;
  }

  // Lanza la notificación a las 17:40
  if (horas === 17 && minutos === 52 && !notifEnviada) {
    notifEnviada = true;
    self.registration.showNotification('⏰ TurnoApp', {
      body: '¡No olvides fichar la salida!',
      icon: '/static/img/logo.png',   // ← pon tu icono o quita esta línea
      badge: '/static/img/logo.png',
      tag: 'recordatorio-fichaje',    // evita notificaciones duplicadas
      requireInteraction: true        // no desaparece sola
    });
  }
}, 60000); // cada 60 segundos
