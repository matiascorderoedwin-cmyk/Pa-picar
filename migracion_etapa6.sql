-- Ejecutar solo después de respaldar la base y aplicar las etapas anteriores.
-- La aplicación permite merma y devoluciones; el CHECK original debe aceptarlas.
BEGIN;
ALTER TABLE movimientos_inventario
    DROP CONSTRAINT IF EXISTS movimientos_inventario_tipo_check;
ALTER TABLE movimientos_inventario
    ADD CONSTRAINT movimientos_inventario_tipo_check
    CHECK (tipo IN (
        'Diaria', 'Lote', 'Ajuste entrada', 'Ajuste salida',
        'Merma', 'Devolución anulación'
    ));
COMMIT;
