-- Permisos por apartado en Pa Picar. Ejecutado primero en Supabase.
-- Permite restringir navegación Y acceso directo a rutas desde Flask.
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS permiso_productos BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS permiso_ventas BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS permiso_pedidos BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS permiso_administracion BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS permiso_reportes BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS permiso_usuarios BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.usuarios ADD COLUMN IF NOT EXISTS es_propietario BOOLEAN NOT NULL DEFAULT FALSE;

-- Este UPDATE se ejecutó UNA SOLA VEZ durante la migración inicial para
-- conservar los privilegios de la cuenta principal preexistente.
-- No volver a ejecutar el UPDATE tras crear usuarios administradores,
-- pues sobreescribiría sus permisos individuales.
-- UPDATE public.usuarios SET permiso_productos=TRUE, permiso_ventas=TRUE,
--     permiso_pedidos=TRUE, permiso_administracion=TRUE,
--     permiso_reportes=TRUE, permiso_usuarios=TRUE,
--     es_propietario=TRUE WHERE rol='administrador';
