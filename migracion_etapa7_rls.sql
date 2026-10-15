-- Migración aplicada en Supabase el 15 de octubre de 2026.
-- Proyecto: Pa Picar (qzgfvoujfxpjxvzfgfzw).
-- Las políticas de acceso público no están habilitadas.
-- Evita ejecutar sin revisar el estado de la base del destino.
ALTER TABLE public.productos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ventas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.venta_detalles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.movimientos_inventario ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usuarios ENABLE ROW LEVEL SECURITY;
