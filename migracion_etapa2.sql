-- Ejecutar UNA sola vez en pgAdmin, sobre la misma base que contiene productos.
CREATE TABLE IF NOT EXISTS ventas (
 id BIGSERIAL PRIMARY KEY,
 fecha TIMESTAMPTZ NOT NULL DEFAULT now(),
 metodo_pago VARCHAR(30) NOT NULL CHECK (metodo_pago IN ('Efectivo','Transferencia')),
 total NUMERIC(12,2) NOT NULL CHECK (total >= 0)
);
CREATE TABLE IF NOT EXISTS venta_detalles (
 id BIGSERIAL PRIMARY KEY,
 venta_id BIGINT NOT NULL REFERENCES ventas(id),
 producto_id INTEGER REFERENCES productos(id) ON DELETE SET NULL,
 nombre_producto VARCHAR(100) NOT NULL,
 cantidad INTEGER NOT NULL CHECK (cantidad > 0),
 precio_unitario NUMERIC(12,2) NOT NULL CHECK (precio_unitario >= 0),
 subtotal NUMERIC(12,2) NOT NULL CHECK (subtotal >= 0)
);
