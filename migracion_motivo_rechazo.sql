-- Motivo administrativo de rechazo, sin cambiar pedidos existentes.
ALTER TABLE public.pedidos ADD COLUMN IF NOT EXISTS motivo_rechazo VARCHAR(250);
