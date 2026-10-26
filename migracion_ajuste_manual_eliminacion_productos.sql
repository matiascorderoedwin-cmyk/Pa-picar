-- Pa Picar: ajuste manual de existencias y eliminación recuperable del catálogo.
-- Migración aditiva: no modifica ni borra productos, facturas o pedidos existentes.
ALTER TABLE public.productos
  ADD COLUMN IF NOT EXISTS eliminado boolean NOT NULL DEFAULT false;
ALTER TABLE public.productos
  ADD COLUMN IF NOT EXISTS eliminado_en timestamptz;

-- El movimiento registra la diferencia firmada entre la cantidad anterior y la nueva.
-- Mantener los tipos anteriores para preservar las ventas y sus devoluciones.
ALTER TABLE public.movimientos_inventario
  DROP CONSTRAINT IF EXISTS movimientos_inventario_tipo_check;
ALTER TABLE public.movimientos_inventario
  ADD CONSTRAINT movimientos_inventario_tipo_check
  CHECK (tipo IN ('Diaria','Lote','Ajuste entrada','Ajuste salida','Merma',
                 'Devolución anulación','Ajuste manual'));
