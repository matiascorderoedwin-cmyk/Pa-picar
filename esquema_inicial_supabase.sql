-- SOLO para proyecto Supabase vacío. No reemplaza ni migra los datos existentes.
-- Para migrar desde pgAdmin, primero realiza un respaldo y planifica restauración.
CREATE TABLE IF NOT EXISTS productos (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    precio NUMERIC(12,2) NOT NULL CHECK (precio >= 0),
    cantidad INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0)
);
-- Después ejecutar migracion_etapa2.sql, etapa3, etapa4, etapa5 y etapa6.
