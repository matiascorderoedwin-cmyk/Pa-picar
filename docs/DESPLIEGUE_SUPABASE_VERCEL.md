# Pa Picar · Despliegue Supabase + Vercel

Esta rama **prepara** la integración; no se ha creado, migrado ni desplegado ningún servicio.

## Antes de empezar: no perder los datos

Realiza un respaldo comprobable de PostgreSQL local. La base actual puede contener
productos, usuarios y ventas. No la sustituyas por una base vacía ni ejecutes
migraciones ya aplicadas. Nunca publiques `.env`, contraseñas o cadenas de conexión.

## Supabase: PostgreSQL

1. Crea tu proyecto en Supabase.
2. En su panel, abre **Connect → Transaction pooler**, recomendado para
   aplicaciones serverless, y copia privadamente la **cadena PostgreSQL**.
3. Usa como `DATABASE_URL` la cadena real que te proporciona Supabase.
   El pooler de transacciones suele utilizar el puerto 6543 y un usuario
   como `postgres.PROJECT_REF`; nunca inventes el host.
4. Configura `DATABASE_SSLMODE=require` (puedes usar
   `verify-full` con el certificado adecuado para validación adicional).
5. Si necesitas importar productos y ventas existentes, primero planifica
   una restauración completa con IDs y secuencias. No ejecutes scripts de
   inicialización sobre una base importada sin revisar el esquema.

### Solo si el proyecto Supabase está vacío

Ejecuta una vez y en orden, desde SQL Editor:
1. `esquema_inicial_supabase.sql` (tabla inicial `productos`).
2. `migracion_etapa2.sql` (ventas y detalles).
3. `migracion_etapa3.sql` (movimientos).
4. `migracion_etapa4.sql` (estados de productos y ventas).
5. `migracion_etapa5.sql` (usuarios).
6. `migracion_etapa6.sql` (mermas y devoluciones).

Para crear la primera cuenta, desde un equipo con Python y acceso seguro a
Supabase, ejecuta `python -m flask --app app crear-usuario` y elige
`administrador`. No guardes su contraseña en el repositorio.

## Vercel: aplicación Flask

1. Importa desde GitHub `matiascorderoedwin-cmyk/Pa-picar`.
2. Vercel reconoce `app.py` y `requirements.txt` sin `vercel.json`.
3. En **Settings → Environment Variables**, configura:
   - `DATABASE_URL` (cadena privada del Transaction pooler).
   - `DATABASE_SSLMODE=require`.
   - `SECRET_KEY` (clave aleatoria estable, de alta entropía).
   - `COOKIE_SECURE=true` (el código también lo fuerza en Vercel).
4. El código utiliza `templates/` y los estilos/imágenes están en
   `public/static/`, para servirlos por el CDN de Vercel.
5. Mantén distintas las variables de pruebas y producción.

## Validación antes de publicar para usuarios reales

- Verifica el logo, la pantalla de login y HTTPS.
- Comprueba que el rol vendedor no puede acceder a administración ni reportes.
- Valida inventario, recibos, zona horaria y ventas solo con datos de prueba.
- Haz respaldo y prueba de restauración antes de operar con datos reales.
- **Bloqueante de seguridad:** implementar y probar un límite de intentos de
  contraseña; el login original aún no tiene protección contra fuerza bruta.
- No expongas el puerto local de Flask ni PostgreSQL a Internet.

## Documentación oficial

- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://vercel.com/docs/frameworks/backend/flask
- https://www.psycopg.org/psycopg3/docs/advanced/prepare.html
