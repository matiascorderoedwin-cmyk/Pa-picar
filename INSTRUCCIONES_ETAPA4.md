# Pa Picar — Etapa 4

## Antes de instalar
1. Haz una copia de seguridad de PostgreSQL en pgAdmin (Backup).
2. Detén Flask con Ctrl+C.
3. Copia `app.py` y la carpeta `templates` de este paquete a tu proyecto actual, reemplazando los anteriores. Conserva tus carpetas `static`, `.venv` y tu archivo `.env`.
4. En pgAdmin, selecciona la base de datos que contiene `productos`, `ventas`, `venta_detalles` y `movimientos_inventario`. Abre `migracion_etapa4.sql` en Query Tool y ejecútala **una sola vez**. No vuelvas a ejecutar las migraciones anteriores.
5. Inicia el servidor con `python app.py` desde la carpeta del proyecto.
6. Abre `/administracion`, `/ventas`, `/reportes` y `/facturar`.

## Pruebas recomendadas
- Desactiva un producto y comprueba que no aparezca al facturar. Reactívalo.
- Registra una merma de 1 unidad y verifica el historial.
- Registra una venta de prueba y anúlala con devolución; comprueba el inventario y que el reporte excluye esa factura.

**Advertencia:** esta es una versión local de pruebas, sin autenticación de usuarios. No exponer en Internet ni usar como comprobante fiscal autorizado.
