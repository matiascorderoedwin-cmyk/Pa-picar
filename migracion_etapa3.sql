-- Ejecutar sobre la MISMA base de datos de Pa Picar, después de la etapa 2.
-- No borra productos ni facturas.
CREATE TABLE IF NOT EXISTS movimientos_inventario (
 id BIGSERIAL PRIMARY KEY,
 producto_id INTEGER NOT NULL REFERENCES productos(id),
 fecha TIMESTAMPTZ NOT NULL DEFAULT now(),
 tipo VARCHAR(30) NOT NULL CHECK (tipo IN ('Diaria','Lote','Ajuste entrada','Ajuste salida')),
 cantidad INTEGER NOT NULL CHECK (cantidad <> 0),
 nota VARCHAR(250) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_movimientos_producto_fecha ON movimientos_inventario(producto_id, fecha DESC);
