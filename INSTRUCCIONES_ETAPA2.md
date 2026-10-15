# Pa Picar — Etapa 2

1. Haz copia de seguridad de tu base de datos en pgAdmin.
2. Conserva tu archivo `.env` original. NO lo compartas.
3. En pgAdmin abre Query Tool sobre `base_de_pa-picar` y ejecuta `migracion_etapa2.sql` una sola vez.
4. Detén Flask con Ctrl+C. Copia los archivos nuevos sobre tu carpeta anterior, sin reemplazar tu `.env` (no se incluye en ZIP).
5. Desde la carpeta `sistema-pa-picar`, con `.venv` existente, ejecuta `python app.py`.
6. Abre `http://127.0.0.1:5000/facturar`.

**Prueba:** registra una venta pequeña y verifica que las existencias bajen, que aparezca el recibo y que figure en historial.

**Aviso:** esta es una versión de desarrollo en red privada, sin cuentas de usuario ni controles de acceso. No exponer a Internet ni usar para comprobantes fiscales. Los recibos son internos.
