# Pa Picar — Etapa 3

1. Haz respaldo de PostgreSQL en pgAdmin y detén Flask (Ctrl+C).
2. Copia `app.py`, `static`, `templates` y `requirements.txt` sobre tu proyecto actual. Conserva `.env` y `.venv`.
3. En pgAdmin, abre tu base de datos y ejecuta `migracion_etapa3.sql` desde Query Tool.
4. En VS Code, ejecuta `python app.py`.
5. Abre `http://127.0.0.1:5000/administracion`.

## Prueba

Selecciona Quipes #3, registra una entrada de producción diaria de 5 unidades y verifica que su inventario suba de 30 a 35 y aparezca en el historial.

## Alcance

Esta etapa permite editar nombres y precios y registrar entradas/salidas con historial. No implementa aún anulaciones de ventas ni fusión/eliminación de duplicados. Los dos registros de Quipes permanecen separados para proteger el historial de ventas. La aplicación no incluye login: usar únicamente en red privada y no exponer a Internet.
