-- Ejecutar en pgAdmin sobre la misma base de Pa Picar.
CREATE TABLE IF NOT EXISTS usuarios (
 id BIGSERIAL PRIMARY KEY,
 usuario VARCHAR(80) NOT NULL UNIQUE,
 clave_hash TEXT NOT NULL,
 rol VARCHAR(20) NOT NULL CHECK (rol IN ('administrador','vendedor')),
 activo BOOLEAN NOT NULL DEFAULT TRUE,
 creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
