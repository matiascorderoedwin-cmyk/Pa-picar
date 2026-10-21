-- Alineación no destructiva del esquema existente para pedidos públicos.
-- Ejecutar antes de probar aceptación, cancelación o confirmación de pagos.
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS total NUMERIC(12,2);
UPDATE public.pedidos SET total = total_estimado WHERE total IS NULL;
ALTER TABLE public.pedidos DROP CONSTRAINT IF EXISTS pedidos_estado_check;
ALTER TABLE public.pedidos ADD CONSTRAINT pedidos_estado_check CHECK (estado IN ('Pendiente','Aceptado','Rechazado','Cancelado','Pagado'));
-- El código escribe tanto total_estimado como total para conservar compatibilidad.
