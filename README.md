# Pa Picar — Sistema de facturación

Aplicación web para la facturación y administración de un negocio de picaderas. Código de la **Etapa 5**, con la identidad visual oficial de Pa Picar.

## Características

- Inicio y cierre de sesión para perfiles `administrador` y `vendedor`.
- Catálogo de productos, existencias e inventario.
- Registro de ventas por unidad, recibos e historial de facturas.
- Medios de pago: efectivo y transferencia.
- Administración, ajustes de inventario, anulación de ventas e informes.
- Diseño, colores y logo oficial de Pa Picar.

## Tecnologías

Python, Flask, Jinja2, PostgreSQL y Psycopg.

## Ejecución local

1. Instala Python y PostgreSQL y crea la base y la tabla inicial `productos` si no existen (ver requisitos de la Etapa 1 de tu instalación).
2. Crea un entorno virtual e instala las dependencias:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Copia `.env.example` a `.env`, configura la conexión PostgreSQL y una `SECRET_KEY` fuerte. Nunca subas `.env` a GitHub.
4. Haz una **copia de seguridad** de tu base actual. Ejecuta en pgAdmin **solamente las migraciones que falten**, en orden: `migracion_etapa2.sql`, `migracion_etapa3.sql`, `migracion_etapa4.sql`, `migracion_etapa5.sql`. No repitas migraciones ya aplicadas. La tabla `productos` se creó en la Etapa 1 y no se incluye en estas migraciones.
5. Crea tu usuario administrador:

   ```powershell
   .\.venv\Scripts\python.exe -m flask --app app crear-usuario
   ```

6. Inicia la aplicación:

   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```

7. Abre `http://127.0.0.1:5000`.

## Estructura

- `app.py`: autenticación, catálogo, facturación y administración.
- `templates/`: páginas HTML y recibos.
- `static/estilos.css`: estilos base de las etapas anteriores.
- `static/pa-picar-marca.css`: identidad visual oficial.
- `static/logo-pa-picar.png`: logo oficial integrado en la interfaz.
- `migracion_etapa*.sql`: scripts de evolución de la base PostgreSQL.
- `INSTRUCCIONES_*.md`: instrucciones originales por etapa.

## Seguridad y despliegue

Esta versión es para **pruebas locales**. El servidor de Flask no debe exponerse directamente a Internet. Antes de publicar deben configurarse HTTPS, cookies seguras, proxy, limitación de intentos de inicio de sesión, protección de secretos y acceso protegido a PostgreSQL. Supabase y Vercel **todavía no están configurados**. Los recibos son internos y no sustituyen comprobantes fiscales autorizados.

El repositorio contiene exclusivamente código, migraciones, plantillas y recursos visuales. **No** incluye `\.env`, bases de datos, credenciales reales ni dependencias instaladas.

## Siguiente etapa: Supabase + Vercel

La integración se prepara en una rama independiente. No se ha desplegado aún.
Revisa [la guía de despliegue](docs/DESPLIEGUE_SUPABASE_VERCEL.md) antes de migrar datos reales.
