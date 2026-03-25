// turno/app/static/js/login.js
document.addEventListener('DOMContentLoaded', function () {
    const form = document.querySelector('#loginForm');
    const passwordInput = document.querySelector('#password');
    const togglePwd = document.querySelector('#togglePassword');
  
    // Validación Bootstrap
    form.addEventListener('submit', function (e) {
      if (!form.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
      } else {
        // Desactiva botón y muestra spinner
        const btn = form.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = `
          <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
          Entrando...
        `;
      }
      form.classList.add('was-validated');
    }, false);
  
    // Toggle visibilidad de contraseña
    togglePwd.addEventListener('click', function () {
      const type = passwordInput.type === 'password' ? 'text' : 'password';
      passwordInput.type = type;
      this.classList.toggle('bi-eye');
      this.classList.toggle('bi-eye-slash');
    });
  });
  