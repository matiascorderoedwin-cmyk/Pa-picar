# Pedidos públicos — Preview

Esta rama no se debe fusionar ni promover a producción hasta completar la prueba web.

## Cambios

- Cantidades manuales enteras entre 1 y el menor de 100 y las existencias.
- Comentarios opcionales de hasta 500 caracteres.
- Fecha y hora requeridas, interpretadas en America/Santo_Domingo; el minuto actual es válido.
- Recoger sin recargo o delivery con dirección obligatoria y RD$100.
- El servidor calcula precios, subtotal y recargo; ignora importes enviados por el cliente.
- Administración muestra horario, comentarios, dirección, modalidad y desglose.
- Pago y recibo incluyen delivery, sin descontar inventario por ese servicio.

## Activar el entorno de pruebas

1. Crear una base o rama Supabase separada. No copiar datos personales de producción.
2. Asegurar que contiene el esquema histórico de la aplicación. Las migraciones anteriores están en la raíz y no incluyen la creación inicial de `productos`; esta migración incremental no reconstruye una base vacía.
3. Aplicar una sola vez `supabase/migrations/20261022123358_pedidos_entrega.sql` en esa base aislada, antes de iniciar Preview. No ejecutarla en producción.
4. Configurar las variables `DATABASE_*` de Vercel exclusivamente para la rama `Preview`, con las credenciales de la base aislada, y una `SECRET_KEY` propia. Solo después de verificar el destino, añadir `PREVIEW_DATABASE_ISOLATED=true` en ese mismo ámbito. La aplicación bloquea conexiones de Vercel Preview sin esa confirmación.
5. Desplegar la rama `Preview` como Preview, con productos y usuario de prueba. No cambiar dominios ni promover a producción.
6. Probar `/pedir` en iPhone y escritorio: cantidades vacías/fraccionarias/excesivas, comentarios, fecha pasada, medianoche dominicana y cambios recoger/delivery. En `/pedidos`, aceptar, cancelar y confirmar pagos; verificar existencias y recibo.

La migración preserva pedidos antiguos como recoger, sin horario y sin recargo. No se aplica automáticamente. Las tablas mantienen acceso privado desde Flask mediante PostgreSQL, con RLS habilitado.

## Pruebas automatizadas

`python -m unittest discover -s tests -v` ejecuta validación de horario y entrega.
Para las pruebas completas, iniciar un clúster PostgreSQL **desechable** en localhost con usuario `preview`, base `postgres`, y exportar `TEST_DATABASE_PORT` con su puerto. La suite crea una base temporal con nombre aleatorio, aplica las migraciones, verifica pedidos históricos y elimina esa base al finalizar. El usuario local necesita permiso para crear bases. Nunca usar credenciales de producción para pruebas.

La suite comprueba pedidos, manipulación de importes, cantidades inválidas, XSS escapado, pago duplicado, cancelación, inventario, permisos, recibo y bloqueo de Preview sin aislamiento.
