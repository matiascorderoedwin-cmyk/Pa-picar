-- Etapa 7: pedidos públicos. Ejecutar en Supabase SQL Editor antes de desplegar.
CREATE TABLE IF NOT EXISTS pedidos (
    id BIGSERIAL PRIMARY KEY,
    cliente_nombre VARCHAR(120) NOT NULL,
    cliente_telefono VARCHAR(30) NOT NULL,
    nota VARCHAR(500),
    estado VARCHAR(20) NOT NULL DEFAULT 'Pendiente'
        CHECK (estado IN ('Pendiente', 'Aceptado', 'Rechazado')),
    total_estimado NUMERIC(12,2) NOT NULL CHECK (total_estimado >= 0),
    venta_id BIGINT UNIQUE REFERENCES ventas(id),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    procesado_en TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS pedido_detalles (
    id BIGSERIAL PRIMARY KEY,
    pedido_id BIGINT NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    nombre_producto VARCHAR(120) NOT NULL,
    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(12,2) NOT NULL CHECK (precio_unitario >= 0),
    subtotal NUMERIC(12,2) NOT NULL CHECK (subtotal >= 0)
);
CREATE INDEX IF NOT EXISTS pedidos_estado_fecha_idx ON pedidos(estado, creado_en DESC);
CREATE INDEX IF NOT EXISTS pedido_detalles_pedido_idx ON pedido_detalles(pedido_id);
-- Las tablas se usan desde Flask con credenciales privadas de PostgreSQL.
-- No conceder permisos de escritura anónimos mediante Data API.
