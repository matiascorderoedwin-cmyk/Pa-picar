-- Fecha y tipo de entrega de los pedidos. Conserva todos los anteriores.
-- Los comentarios se guardan en el campo "nota" existente (500 caracteres).
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS tipo_entrega VARCHAR(12);
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS fecha_entrega TIMESTAMPTZ;
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS direccion_entrega VARCHAR(300);
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS costo_delivery NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE public.pedidos DROP CONSTRAINT IF EXISTS pedidos_tipo_entrega_check;
ALTER TABLE public.pedidos ADD CONSTRAINT pedidos_tipo_entrega_check
  CHECK (tipo_entrega IS NULL OR tipo_entrega IN ('recoger', 'delivery'));
ALTER TABLE public.pedidos DROP CONSTRAINT IF EXISTS pedidos_costo_delivery_check;
ALTER TABLE public.pedidos ADD CONSTRAINT pedidos_costo_delivery_check
  CHECK (costo_delivery >= 0);
