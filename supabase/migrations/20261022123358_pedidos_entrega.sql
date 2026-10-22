-- Aplicar primero en una base Preview aislada, nunca automáticamente al arrancar.
-- Requiere las migraciones históricas de pedidos y ventas del repositorio.
BEGIN;
ALTER TABLE public.pedidos
    ADD COLUMN modalidad TEXT NOT NULL DEFAULT 'recoger',
    ADD COLUMN entrega_en TIMESTAMPTZ,
    ADD COLUMN direccion_entrega VARCHAR(300),
    ADD COLUMN costo_delivery NUMERIC(12,2) NOT NULL DEFAULT 0,
    ADD CONSTRAINT pedidos_modalidad_check CHECK (modalidad IN ('recoger','delivery')),
    ADD CONSTRAINT pedidos_delivery_check CHECK (
        (modalidad = 'recoger' AND costo_delivery = 0 AND direccion_entrega IS NULL)
        OR (modalidad = 'delivery' AND costo_delivery = 100
            AND direccion_entrega IS NOT NULL AND length(btrim(direccion_entrega)) BETWEEN 5 AND 300)
    );
-- Los pedidos históricos conservan sus importes y quedan sin fecha programada.
-- La validación temporal es del servidor: CHECK(now()) no es una restricción estable.
ALTER TABLE public.ventas ADD COLUMN costo_delivery NUMERIC(12,2) NOT NULL DEFAULT 0
    CHECK (costo_delivery IN (0,100));
-- Flask usa PostgreSQL privado; estas tablas no necesitan políticas públicas.
ALTER TABLE public.pedidos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pedido_detalles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ventas ENABLE ROW LEVEL SECURITY;
COMMIT;
