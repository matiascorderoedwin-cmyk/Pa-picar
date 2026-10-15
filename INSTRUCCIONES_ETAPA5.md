# Pa Picar - Etapa 5, paso 1: inicio de sesión

1. Haz una copia de seguridad de la carpeta del proyecto y de PostgreSQL.
2. Copia `app.py`, `templates/` y `migracion_etapa5.sql` de este paquete a tu proyecto actual. **Conserva** tu carpeta `static/` y tu archivo `.env`; no los sustituyas.
3. En pgAdmin abre la base de datos de Pa Picar, Query Tool, pega `migracion_etapa5.sql` y ejecuta.
4. En la terminal de VS Code, situada en la carpeta que contiene `app.py`, activa el entorno virtual si corresponde y ejecuta: `python -m flask --app app crear-usuario`. Introduce usuario, rol `administrador` y una contraseña nueva de 12 caracteres o más. No publiques esa contraseña.
5. Ejecuta `python app.py` y abre `http://127.0.0.1:5000`. Debe aparecer el inicio de sesión.
6. Puedes crear un usuario vendedor ejecutando otra vez `python -m flask --app app crear-usuario` y eligiendo `vendedor`. El vendedor puede facturar, consultar recibos e historial; la administración, los reportes, la anulación y el alta de productos quedan restringidos al administrador.

**Importante:** este paquete es una primera etapa local, NO una publicación segura en Internet. Falta configurar HTTPS, proxy de confianza, limitación de intentos de inicio de sesión, gestión de usuarios y despliegue de producción. Configura `COOKIE_SECURE=true` solamente al usar HTTPS. No abras el puerto 5000 ni PostgreSQL a Internet.

**Logo:** los archivos entregados no incluyen el archivo de imagen original; el acceso muestra el nombre de marca y su paleta. Para incorporar exactamente el logo, se necesita la imagen como archivo en `static/`.
