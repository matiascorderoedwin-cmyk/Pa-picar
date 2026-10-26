"""Pa Picar: catálogo, facturación y administración de inventario."""
import logging
import os
import secrets
import json
import re
import unicodedata
from urllib.parse import urlsplit
from io import BytesIO
from functools import wraps, lru_cache
from datetime import timedelta
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for, session, abort, g, send_file, send_from_directory, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
# A stable secret is required for sessions on serverless deployments.
if os.getenv("VERCEL") and not os.getenv("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY must be configured in Vercel environment variables")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=1024*1024)
if os.getenv('COOKIE_SECURE', 'false').lower() == 'true':
    app.config['SESSION_COOKIE_SECURE'] = True



def conectar():
    """Open PostgreSQL connection, including Supabase's transaction pooler."""
    host = os.getenv("DATABASE_HOST", "127.0.0.1")
    settings = dict(
        dbname=os.getenv("DATABASE_NAME", "base_de_pa-picar"),
        user=os.getenv("DATABASE_USER", "postgres"),
        password=os.getenv("DATABASE_PASSWORD", ""),
        host=host,
        port=os.getenv("DATABASE_PORT", "5432"),
        connect_timeout=10,
        sslmode=os.getenv("DATABASE_SSLMODE", "prefer" if host in ("127.0.0.1", "localhost") else "require"),
    )
    # Supabase transaction pooling is suitable for short-lived serverless requests.
    # Avoid server-side prepared statements with PgBouncer transaction mode.
    if os.getenv("DATABASE_POOLER", "false").lower() == "true":
        settings["prepare_threshold"] = None
    return psycopg.connect(**settings)


# Permisos de secciones: comprobados en el servidor en cada petición.
# Los cambios hechos por un administrador surten efecto en la próxima petición.
PERMISOS = ('productos', 'ventas', 'pedidos', 'administracion', 'reportes', 'usuarios')
ETIQUETAS_PERMISOS = (
    ('productos', 'Productos y catálogo'),
    ('ventas', 'Ventas y facturas'),
    ('pedidos', 'Pedidos de clientes'),
    ('administracion', 'Administración e inventario'),
    ('reportes', 'Reportes detallados'),
    ('usuarios', 'Gestionar cuentas de usuario'),
)
RUTAS_PERMISOS = {
    'inicio': 'productos',
    'agregar_producto': 'productos',
    'facturar': 'ventas',
    'crear_venta': 'ventas',
    'listado_ventas': 'ventas',
    'recibo': 'ventas',
    'anular_venta': 'ventas',
    'pedidos': 'pedidos',
    'procesar_pedido': 'pedidos',
    'avisos_pedidos_estado': 'pedidos',
    'suscribir_avisos_pedidos': 'pedidos',
    'cancelar_avisos_pedidos': 'pedidos',
    'administracion': 'administracion',
    'editar_producto': 'administracion',
    'movimiento_producto': 'administracion',
    'ajustar_existencias_producto': 'administracion',
    'eliminar_producto': 'administracion',
    'recuperar_producto': 'administracion',
    'cambiar_estado_producto': 'administracion',
    'reportes': 'reportes',
    'usuarios_admin': 'usuarios',
    'crear_usuario_web': 'usuarios',
    'actualizar_usuario_web': 'usuarios',
    'activar_usuario_web': 'usuarios',
    'clave_usuario_web': 'usuarios',
}
RUTAS_SOLO_ADMIN = {
    'agregar_producto','administracion','editar_producto',
    'movimiento_producto','ajustar_existencias_producto',
    'eliminar_producto','recuperar_producto',
    'cambiar_estado_producto','anular_venta',
    'usuarios_admin','crear_usuario_web','actualizar_usuario_web',
    'activar_usuario_web','clave_usuario_web',
}
RUTAS_GESTOR = {
    'usuarios_admin','crear_usuario_web','actualizar_usuario_web',
    'activar_usuario_web','clave_usuario_web',
}

def puede_gestionar_usuarios(usuario):
    return bool(
        usuario and usuario['rol'] == 'administrador'
        and usuario['permiso_administracion'] and usuario['permiso_usuarios']
    )

@app.before_request
def exigir_acceso():
    g.usuario = None
    endpoint = request.endpoint
    if endpoint == 'static':
        return
    if endpoint in ('login', 'logout', 'pedidos_publicos', 'enviar_pedido', 'pedido_recibido', 'pwa_icon', 'pwa_service_worker'):
        return
    if endpoint is None:
        abort(404)
    uid = session.get('usuario_id')
    if not uid:
        return redirect(url_for('login'))
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT id, usuario, rol, activo,
                              permiso_productos, permiso_ventas, permiso_pedidos,
                              permiso_administracion, permiso_reportes,
                              permiso_usuarios, es_propietario
                       FROM usuarios WHERE id=%s AND activo=TRUE""",
                    (uid,)
                )
                g.usuario = cursor.fetchone()
    except psycopg.Error:
        app.logger.exception('Error verificando sesión y permisos')
        abort(503)
    if g.usuario is None:
        session.clear()
        return redirect(url_for('login'))

    if endpoint == 'panel':
        return
    permiso = RUTAS_PERMISOS.get(endpoint)
    # Las rutas internas nuevas deben declarar explícitamente su permiso.
    if permiso is None or not g.usuario['permiso_' + permiso]:
        abort(403)
    if endpoint in RUTAS_SOLO_ADMIN and g.usuario['rol'] != 'administrador':
        abort(403)
    if endpoint in RUTAS_GESTOR and not puede_gestionar_usuarios(g.usuario):
        abort(403)

def solo_admin(fn):
    @wraps(fn)
    def protegido(*args, **kwargs):
        if not g.usuario or g.usuario['rol'] != 'administrador':
            abort(403)
        return fn(*args, **kwargs)
    return protegido

def solo_gestor_usuarios(fn):
    @wraps(fn)
    def protegido(*args, **kwargs):
        if not puede_gestionar_usuarios(g.usuario):
            abort(403)
        return fn(*args, **kwargs)
    return protegido

@app.context_processor
def usuario_actual():
    usuario = getattr(g, 'usuario', None)
    return {
        'usuario_actual': usuario,
        'puede_gestionar_usuarios': puede_gestionar_usuarios(usuario),
    }

# PWA para iPhone. Los iconos cuadrados se generan a partir del
# archivo original de la marca (no se modifica el logo existente).
# Las rutas son públicas y no consultan usuarios, sesiones ni pedidos.
@lru_cache(maxsize=3)
def _icono_pwa_png(tamano):
    from PIL import Image, ImageOps
    ruta = os.path.join(app.static_folder, 'logo-pa-picar.png')
    with Image.open(ruta) as original:
        marca = original.convert('RGB')
    fondo = Image.new('RGB', (tamano, tamano), '#f7eee5')
    dibujo = ImageOps.contain(
        marca,
        (int(tamano * 0.94), int(tamano * 0.82)),
        Image.Resampling.LANCZOS
    )
    fondo.paste(dibujo, ((tamano-dibujo.width)//2, (tamano-dibujo.height)//2))
    salida = BytesIO()
    fondo.save(salida, format='PNG', optimize=True)
    return salida.getvalue()


@app.get('/app-icon/<int:size>.png')
def pwa_icon(size):
    if size not in (180, 192, 512):
        abort(404)
    archivo = BytesIO(_icono_pwa_png(size))
    return send_file(
        archivo, mimetype='image/png', max_age=604800,
        download_name=f'pa-picar-{size}.png'
    )


@app.get('/sw.js')
def pwa_service_worker():
    respuesta = send_from_directory(
        app.static_folder, 'pwa/sw.js', mimetype='application/javascript'
    )
    # Permite que el iPhone y otros navegadores busquen actualizaciones.
    respuesta.headers['Cache-Control'] = 'no-cache, max-age=0'
    return respuesta

@app.get('/panel')
def panel():
    """Abre la primera sección autorizada después de iniciar sesión."""
    for endpoint, permiso in (
        ('inicio','productos'),
        ('listado_ventas','ventas'),
        ('pedidos','pedidos'),
        ('administracion','administracion'),
        ('reportes','reportes')
    ):
        if g.usuario['permiso_' + permiso]:
            if endpoint == 'administracion' and g.usuario['rol'] != 'administrador':
                continue
            return redirect(url_for(endpoint))
    return render_template('sin_acceso.html'), 403

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if session.get('usuario_id'):
            return redirect(url_for('panel'))
        return render_template('login.html')
    validar_csrf()
    usuario = request.form.get('usuario', '').strip()
    clave = request.form.get('clave', '')
    if not usuario or len(usuario) > 80 or len(clave) > 256:
        abort(400)
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,usuario,clave_hash,rol FROM usuarios WHERE usuario=%s AND activo=TRUE', (usuario,))
                registro = cursor.fetchone()
    except psycopg.Error:
        app.logger.exception('No fue posible validar acceso')
        flash('No se pudo consultar la base de datos.', 'error')
        return render_template('login.html'), 503
    if registro and check_password_hash(registro['clave_hash'], clave):
        session.clear()
        session.permanent = True
        session['usuario_id'] = registro['id']
        session['csrf'] = secrets.token_hex(24)
        return redirect(url_for('panel'))
    flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('login.html'), 401

@app.post('/logout')
def logout():
    validar_csrf()
    session.clear()
    return redirect(url_for('login'))

@app.cli.command('crear-usuario')
def crear_usuario():
    """Alta por terminal para mantenimiento; la creación normal se hace en Administración."""
    import click
    nombre = click.prompt('Usuario').strip()
    rol = click.prompt('Rol', type=click.Choice(['administrador', 'vendedor']))
    clave = click.prompt('Contraseña (mínimo 12 caracteres)', hide_input=True, confirmation_prompt=True)
    if not (3 <= len(nombre) <= 80) or not (12 <= len(clave) <= 128):
        raise click.ClickException('Usuario de 3-80 caracteres y contraseña de 12-128 caracteres.')
    habilitado = rol == 'administrador'
    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO usuarios(
                        usuario,clave_hash,rol,permiso_productos,permiso_ventas,
                        permiso_pedidos,permiso_administracion,permiso_reportes,
                        permiso_usuarios,es_propietario)
                    VALUES (%s,%s,%s,TRUE,TRUE,%s,%s,%s,FALSE,FALSE)
                """, (nombre, generate_password_hash(clave), rol,
                      habilitado, habilitado, habilitado))
    except psycopg.Error as exc:
        raise click.ClickException('No se pudo crear el usuario. Revisa la base de datos.') from exc
    click.echo('Usuario creado correctamente.')

@app.get("/")
def inicio():
    """El panel principal muestra únicamente el catálogo y el alta de productos."""
    productos = []
    base_disponible = True
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT id, nombre, precio, cantidad, activo "
                    "FROM productos WHERE eliminado=FALSE ORDER BY activo DESC, nombre ASC, id ASC"
                )
                productos = cursor.fetchall()
    except psycopg.Error:
        app.logger.exception("No fue posible consultar los productos")
        flash("No se pudo consultar el catálogo de productos.", "error")
        base_disponible = False

    return render_template(
        "index.html",
        productos=productos,
        cantidad_productos=len(productos),
        base_disponible=base_disponible,
    )

@app.post("/productos")
@solo_admin
def agregar_producto():
    validar_csrf()
    nombre = request.form.get("nombre", "").strip()
    precio_texto = request.form.get("precio", "").strip()
    cantidad_texto = request.form.get("cantidad", "").strip()

    try:
        precio = Decimal(precio_texto)
        cantidad = int(cantidad_texto)
        if (
            not nombre
            or len(nombre) > 100
            or not precio.is_finite()
            or not Decimal("0") <= precio <= Decimal("99999999.99")
            or precio.as_tuple().exponent < -2
            or not 0 <= cantidad <= 100000000
        ):
            raise ValueError("Valor fuera del rango permitido")
    except (ValueError, InvalidOperation):
        flash("Verifica el nombre, el precio (hasta 2 decimales) y la cantidad (entero positivo).", "error")
        return redirect(url_for("inicio"))

    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("SELECT id FROM productos WHERE lower(trim(nombre))=lower(%s) LIMIT 1", (nombre,))
                if cursor.fetchone():
                    flash("Ya existe un producto con ese nombre. Edita su precio o registra una reposición.", "error")
                    return redirect(url_for("inicio"))
                cursor.execute(
                    "INSERT INTO productos (nombre, precio, cantidad) "
                    "VALUES (%s, %s, %s)",
                    (nombre, precio, cantidad),
                )
        flash(f"Producto «{nombre}» guardado correctamente.", "success")
    except psycopg.Error:
        app.logger.exception("No fue posible registrar el producto")
        flash("No se pudo guardar. Comprueba la conexión con PostgreSQL.", "error")

    return redirect(url_for("inicio"))


def token_csrf():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    return session['csrf']

app.jinja_env.globals['csrf_token'] = token_csrf


@app.get('/facturar')
def facturar():
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id, nombre, precio, cantidad FROM productos WHERE activo = TRUE AND eliminado=FALSE ORDER BY nombre, id')
                productos = cursor.fetchall()
        return render_template('facturar.html', productos=productos)
    except psycopg.Error:
        app.logger.exception('Error leyendo productos')
        flash('No se pudo cargar el catálogo.', 'error')
        return redirect(url_for('inicio'))


@app.post('/ventas')
def crear_venta():
    if not secrets.compare_digest(request.form.get('csrf',''), session.get('csrf','')):
        abort(400)
    try:
        items = json.loads(request.form.get('items','[]'))
        if not isinstance(items,list) or not 1 <= len(items) <= 100:
            raise ValueError('Agrega al menos un producto')
        cantidades = {}
        for item in items:
            if not isinstance(item,dict) or type(item.get('id')) is not int or type(item.get('cantidad')) is not int:
                raise ValueError('Datos inválidos')
            pid, cant = item['id'], item['cantidad']
            if pid < 1 or not 1 <= cant <= 100000:
                raise ValueError('Cantidad inválida')
            cantidades[pid] = cantidades.get(pid,0) + cant
        if any(q > 100000 for q in cantidades.values()):
            raise ValueError('Cantidad excesiva')
        metodo = request.form.get('metodo','')
        if metodo not in ('Efectivo','Transferencia'):
            raise ValueError('Selecciona el método de pago')
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,precio,cantidad,activo,eliminado FROM productos WHERE id = ANY(%s) ORDER BY id FOR UPDATE', (list(cantidades),))
                productos = cursor.fetchall()
                if len(productos) != len(cantidades):
                    raise ValueError('Hay productos que ya no existen')
                total = Decimal('0')
                detalles=[]
                for producto in productos:
                    q=cantidades[producto['id']]
                    if not producto['activo'] or producto['eliminado']:
                        raise ValueError(f"El producto {producto['nombre']} está desactivado")
                    if producto['cantidad'] is None or producto['cantidad'] < q:
                        raise ValueError(f"No hay suficientes unidades de {producto['nombre']}")
                    subtotal=producto['precio']*q
                    total += subtotal
                    detalles.append((producto,q,subtotal))
                cursor.execute('INSERT INTO ventas (metodo_pago,total) VALUES (%s,%s) RETURNING id', (metodo,total))
                venta_id=cursor.fetchone()['id']
                for producto,q,subtotal in detalles:
                    cursor.execute('INSERT INTO venta_detalles (venta_id,producto_id,nombre_producto,cantidad,precio_unitario,subtotal) VALUES (%s,%s,%s,%s,%s,%s)', (venta_id,producto['id'],producto['nombre'],q,producto['precio'],subtotal))
                    cursor.execute('UPDATE productos SET cantidad=cantidad-%s WHERE id=%s', (q,producto['id']))
        flash(f'Venta #{venta_id} registrada correctamente.', 'success')
        return redirect(url_for('recibo',venta_id=venta_id))
    except (ValueError,TypeError,json.JSONDecodeError) as exc:
        flash(str(exc),'error')
    except psycopg.Error:
        app.logger.exception('No se pudo registrar venta')
        flash('Error de base de datos. Ejecuta primero migracion_etapa2.sql.', 'error')
    return redirect(url_for('facturar'))


@app.get('/recibo/<int:venta_id>')
def recibo(venta_id):
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT * FROM ventas WHERE id=%s',(venta_id,))
                venta=cursor.fetchone()
                if venta is None: abort(404)
                cursor.execute('SELECT * FROM venta_detalles WHERE venta_id=%s ORDER BY id',(venta_id,))
                detalles=cursor.fetchall()
        return render_template('recibo.html',venta=venta,detalles=detalles)
    except psycopg.Error:
        abort(500)


@app.get('/ventas')
def listado_ventas():
    """Historial de facturas y totales de ventas en hora de República Dominicana."""
    periodo = request.args.get('periodo', 'todas')
    filtros = {
        'todas': 'TRUE',
        'hoy': """(fecha AT TIME ZONE 'America/Santo_Domingo')::date =
                  (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')::date""",
        'semana': """(fecha AT TIME ZONE 'America/Santo_Domingo') >=
                     date_trunc('week', CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')""",
        'mes': """(fecha AT TIME ZONE 'America/Santo_Domingo') >=
                  date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')""",
    }
    if periodo not in filtros:
        periodo = 'todas'

    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT
                        COALESCE(SUM(total) FILTER (WHERE (fecha AT TIME ZONE 'America/Santo_Domingo')::date =
                            (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')::date), 0) AS hoy,
                        COUNT(*) FILTER (WHERE (fecha AT TIME ZONE 'America/Santo_Domingo')::date =
                            (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')::date) AS facturas_hoy,
                        COALESCE(SUM(total) FILTER (WHERE (fecha AT TIME ZONE 'America/Santo_Domingo') >=
                            date_trunc('week', CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')), 0) AS semana,
                        COUNT(*) FILTER (WHERE (fecha AT TIME ZONE 'America/Santo_Domingo') >=
                            date_trunc('week', CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')) AS facturas_semana,
                        COALESCE(SUM(total) FILTER (WHERE (fecha AT TIME ZONE 'America/Santo_Domingo') >=
                            date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')), 0) AS mes,
                        COUNT(*) FILTER (WHERE (fecha AT TIME ZONE 'America/Santo_Domingo') >=
                            date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')) AS facturas_mes,
                        COALESCE(SUM(total) FILTER (WHERE metodo_pago='Efectivo'
                            AND (fecha AT TIME ZONE 'America/Santo_Domingo')::date =
                                (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')::date), 0) AS efectivo_hoy,
                        COALESCE(SUM(total) FILTER (WHERE metodo_pago='Transferencia'
                            AND (fecha AT TIME ZONE 'America/Santo_Domingo')::date =
                                (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')::date), 0) AS transferencia_hoy
                    FROM ventas WHERE estado = 'Activa'
                """)
                resumen = cursor.fetchone()
                # La condición se elige de un diccionario fijo, nunca se construye
                # directamente a partir de texto de un usuario.
                cursor.execute(f"""
                    SELECT id,
                           fecha AT TIME ZONE 'America/Santo_Domingo' AS fecha_local,
                           metodo_pago, total, estado
                    FROM ventas WHERE {filtros[periodo]}
                    ORDER BY fecha DESC, id DESC LIMIT 100
                """)
                ventas = cursor.fetchall()
        return render_template('ventas.html',ventas=ventas,resumen=resumen,periodo=periodo)
    except psycopg.Error:
        app.logger.exception('Error consultando historial de ventas')
        flash('No fue posible consultar las ventas.', 'error')
        return redirect(url_for('inicio'))


# Avisos Web Push con permiso explícito; la clave privada está en Vercel.
PUSH_PUBLIC_KEY = os.getenv('PUSH_VAPID_PUBLIC_KEY', '')

def suscripcion_push_valida(datos):
    if not isinstance(datos,dict) or not isinstance(datos.get('keys'),dict):
        raise ValueError('Suscripción inválida.')
    endpoint=datos.get('endpoint')
    if not isinstance(endpoint,str) or len(endpoint)>4000 or not endpoint.startswith('https://'):
        raise ValueError('Endpoint inválido.')
    partes=urlsplit(endpoint)
    host=(partes.hostname or '').lower()
    if not (host.endswith('.push.apple.com') or host=='fcm.googleapis.com'
            or host=='updates.push.services.mozilla.com'
            or host.endswith('.notify.windows.com')):
        raise ValueError('Proveedor de avisos no autorizado.')
    if partes.username or partes.password or partes.port or partes.fragment:
        raise ValueError('Endpoint inválido.')
    claves=datos['keys']
    for clave in ('p256dh','auth'):
        valor=claves.get(clave)
        if not isinstance(valor,str) or not re.fullmatch(r'[A-Za-z0-9_-]{15,250}',valor):
            raise ValueError('Claves de avisos inválidas.')
    return {'endpoint':endpoint,'keys':{'p256dh':claves['p256dh'],'auth':claves['auth']}}

def enviar_notificacion_push(suscripcion,titulo,mensaje,destino):
    privada=os.getenv('PUSH_VAPID_PRIVATE_KEY','')
    if not privada:
        return False
    try:
        from pywebpush import webpush
        webpush(
            subscription_info=suscripcion,
            data=json.dumps({'title':titulo,'body':mensaje,'url':destino}),
            vapid_private_key=privada,
            vapid_claims={'sub':'https://pa-picar.vercel.app'},
            ttl=300,timeout=2
        )
        return True
    except Exception:
        app.logger.warning('No se pudo entregar un aviso push al dispositivo')
        return False

def avisar_pedido_a_empleados(pedido_id):
    if not os.getenv('PUSH_VAPID_PRIVATE_KEY'):
        return
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT s.endpoint,s.p256dh,s.auth FROM suscripciones_push s
                    JOIN usuarios u ON u.id=s.usuario_id
                    WHERE u.activo=TRUE AND u.permiso_pedidos=TRUE AND s.origen=%s
                    ORDER BY s.creado_en DESC LIMIT 5
                """,(request.host_url.rstrip('/'),))
                destinos=cursor.fetchall()
        for d in destinos:
            enviar_notificacion_push(
                {'endpoint':d['endpoint'],
                 'keys':{'p256dh':d['p256dh'],'auth':d['auth']}},
                'Nuevo pedido · Pa Picar',
                f'Pedido #{pedido_id} pendiente de revisión',
                '/pedidos?estado=Pendiente'
            )
    except psycopg.Error:
        app.logger.exception('No se pudieron consultar suscripciones push')

@app.get('/pedidos/avisos/estado')
def avisos_pedidos_estado():
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT COUNT(*) AS pendientes, COALESCE(MAX(id),0) AS ultimo_id
                    FROM pedidos WHERE estado='Pendiente'
                """)
                actual=cursor.fetchone()
        respuesta=jsonify({'pendientes':actual['pendientes'],'ultimo_id':actual['ultimo_id']})
        respuesta.headers['Cache-Control']='no-store'
        return respuesta
    except psycopg.Error:
        app.logger.exception('Error consultando avisos')
        abort(503)

@app.post('/pedidos/avisos/suscribir')
def suscribir_avisos_pedidos():
    validar_csrf()
    try:
        datos=(request.get_json(silent=True) or {}).get('subscription')
        sub=suscripcion_push_valida(datos)
    except ValueError:
        abort(400)
    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO suscripciones_push(usuario_id,endpoint,p256dh,auth,origen)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT(endpoint) DO UPDATE SET
                        usuario_id=EXCLUDED.usuario_id,p256dh=EXCLUDED.p256dh,
                        auth=EXCLUDED.auth,origen=EXCLUDED.origen,creado_en=now()
                """,(g.usuario['id'],sub['endpoint'],sub['keys']['p256dh'],
                     sub['keys']['auth'],request.host_url.rstrip('/')))
        return jsonify({'ok':True})
    except psycopg.Error:
        app.logger.exception('Error registrando avisos')
        abort(503)

@app.post('/pedidos/avisos/desactivar')
def cancelar_avisos_pedidos():
    validar_csrf()
    endpoint=(request.get_json(silent=True) or {}).get('endpoint')
    if not isinstance(endpoint,str) or len(endpoint)>4000:
        abort(400)
    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM suscripciones_push WHERE usuario_id=%s AND endpoint=%s',
                    (g.usuario['id'],endpoint)
                )
        return jsonify({'ok':True})
    except psycopg.Error:
        app.logger.exception('Error desactivando avisos')
        abort(503)

@app.get('/pedidos')
def pedidos():
    """Panel de pedidos separado del inventario, con filtros por estado."""
    estados = ('Pendiente', 'Aceptado', 'Rechazado', 'Pagado', 'Cancelado')
    estado = request.args.get('estado', 'Todos')
    if estado not in ('Todos',) + estados:
        estado = 'Todos'
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT estado, COUNT(*) AS cantidad FROM pedidos GROUP BY estado")
                conteos = {fila['estado']: fila['cantidad'] for fila in cursor.fetchall()}
                cursor.execute("""
                    SELECT p.id,p.cliente_nombre,p.cliente_telefono,p.total,p.estado,
                           p.creado_en,p.creado_en AT TIME ZONE 'America/Santo_Domingo' AS creado_en_local,
                           p.procesado_en,p.motivo_rechazo,p.venta_id,
                           p.tipo_entrega,p.fecha_entrega AT TIME ZONE 'America/Santo_Domingo' AS fecha_entrega_local,
                           p.direccion_entrega,p.costo_delivery,p.nota,
                           COALESCE(
                             json_agg(json_build_object('nombre',d.nombre_producto,
                                                       'cantidad',d.cantidad,
                                                       'precio',d.precio_unitario)
                                      ORDER BY d.id)
                             FILTER (WHERE d.id IS NOT NULL), '[]'::json
                           ) AS detalles
                    FROM pedidos p
                    LEFT JOIN pedido_detalles d ON d.pedido_id=p.id
                    WHERE (%s = 'Todos' OR p.estado = %s)
                    GROUP BY p.id
                    ORDER BY p.creado_en DESC,p.id DESC
                    LIMIT 100
                """, (estado, estado))
                lista = cursor.fetchall()
        return render_template('pedidos.html',pedidos=lista,conteos=conteos,estado=estado,estados=estados,push_public_key=PUSH_PUBLIC_KEY)
    except psycopg.Error:
        app.logger.exception('Error consultando pedidos')
        flash('No fue posible consultar los pedidos.', 'error')
        return redirect(url_for('inicio'))

@app.get('/administracion')
@solo_admin
def administracion():
    """Ajustes de productos, movimientos y existencias; pedidos se ven en /pedidos."""
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,precio,cantidad,activo FROM productos WHERE eliminado=FALSE ORDER BY activo DESC,nombre,id')
                productos = cursor.fetchall()
                cursor.execute('SELECT id,nombre,cantidad,eliminado_en FROM productos WHERE eliminado=TRUE ORDER BY eliminado_en DESC NULLS LAST,id DESC')
                eliminados = cursor.fetchall()
                cursor.execute('''SELECT m.id,m.fecha,m.tipo,m.cantidad,m.nota,p.nombre
                                  FROM movimientos_inventario m JOIN productos p ON p.id=m.producto_id
                                  ORDER BY m.id DESC LIMIT 50''')
                movimientos = cursor.fetchall()
        # Indicadores de inventario solo sobre los productos activos, como
        # el resumen anterior del panel principal.
        productos_activos = [p for p in productos if p['activo']]
        total_unidades = sum((p['cantidad'] or 0) for p in productos_activos)
        inventario_bajo = [p for p in productos_activos if (p['cantidad'] or 0) <= 10]
        return render_template(
            'administracion.html',
            productos=productos,
            eliminados=eliminados,
            movimientos=movimientos,
            total_unidades=total_unidades,
            cantidad_productos_activos=len(productos_activos),
            inventario_bajo=inventario_bajo,
        )
    except psycopg.Error:
        app.logger.exception('Error en administración')
        flash('No se pudo abrir administración. Comprueba la conexión y las tablas de inventario.', 'error')
        return redirect(url_for('inicio'))

def validar_csrf():
    # Los formularios clásicos usan form; los permisos de notificaciones usan JSON.
    token=request.form.get('csrf','')
    if request.is_json:
        datos=request.get_json(silent=True)
        token=datos.get('csrf','') if isinstance(datos,dict) else ''
    if not isinstance(token,str) or not secrets.compare_digest(token,session.get('csrf','')):
        abort(400)


@app.post('/administracion/producto/<int:pid>/editar')
@solo_admin
def editar_producto(pid):
    validar_csrf()
    nombre=request.form.get('nombre','').strip()
    try:
        precio=Decimal(request.form.get('precio',''))
        if not nombre or len(nombre)>100 or not precio.is_finite() or precio<0 or precio>Decimal('99999999.99') or precio.as_tuple().exponent < -2:
            raise ValueError()
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute('SELECT id FROM productos WHERE lower(trim(nombre))=lower(%s) AND id<>%s LIMIT 1',(nombre,pid))
                if cursor.fetchone():
                    flash('Otro producto ya tiene ese nombre.','error')
                    return redirect(url_for('administracion'))
                cursor.execute('UPDATE productos SET nombre=%s,precio=%s WHERE id=%s AND eliminado=FALSE',(nombre,precio,pid))
                if cursor.rowcount!=1: raise ValueError()
        flash('Producto actualizado correctamente.','success')
    except (ValueError,InvalidOperation):
        flash('Verifica el nombre y el precio (máximo dos decimales).','error')
    except psycopg.Error:
        app.logger.exception('Error editando producto')
        flash('No fue posible actualizar el producto.','error')
    return redirect(url_for('administracion'))


@app.post('/administracion/producto/<int:pid>/movimiento')
@solo_admin
def movimiento_producto(pid):
    validar_csrf()
    tipo=request.form.get('tipo','')
    nota=request.form.get('nota','').strip()
    try:
        cantidad=int(request.form.get('cantidad',''))
        if tipo not in ('Diaria','Lote','Ajuste entrada','Ajuste salida','Merma') or not 1<=cantidad<=1000000 or len(nota)>250:
            raise ValueError()
        cambio=-cantidad if tipo in ('Ajuste salida','Merma') else cantidad
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT cantidad FROM productos WHERE id=%s AND eliminado=FALSE FOR UPDATE',(pid,))
                producto=cursor.fetchone()
                if not producto or producto['cantidad'] is None or producto['cantidad']+cambio<0:
                    raise ValueError('Existencias insuficientes o producto inexistente.')
                cursor.execute('UPDATE productos SET cantidad=cantidad+%s WHERE id=%s AND eliminado=FALSE',(cambio,pid))
                cursor.execute('INSERT INTO movimientos_inventario (producto_id,tipo,cantidad,nota) VALUES (%s,%s,%s,%s)',(pid,tipo,cambio,nota))
        flash('Movimiento de inventario guardado.','success')
    except (ValueError,TypeError) as exc:
        flash(str(exc) if str(exc) else 'Cantidad o tipo de movimiento inválido.','error')
    except psycopg.Error:
        app.logger.exception('Error registrando movimiento')
        flash('No se pudo guardar el movimiento.','error')
    return redirect(url_for('administracion'))




@app.post('/administracion/producto/<int:pid>/ajustar-existencias')
@solo_admin
def ajustar_existencias_producto(pid):
    """Establecer el inventario exacto y guardar la diferencia en el historial."""
    validar_csrf()
    texto=request.form.get('nueva_cantidad','').strip()
    nota=request.form.get('nota','').strip()
    try:
        if not texto.isdecimal() or len(texto)>9 or len(nota)>160:
            raise ValueError('Indica una cantidad entera válida y una nota de hasta 160 caracteres.')
        nueva=int(texto)
        if nueva>100000000:
            raise ValueError('La cantidad debe estar entre 0 y 100,000,000 unidades.')
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,cantidad FROM productos WHERE id=%s AND eliminado=FALSE FOR UPDATE',(pid,))
                producto=cursor.fetchone()
                if not producto:
                    raise ValueError('No se encontró el producto en el inventario activo.')
                anterior=producto['cantidad']
                diferencia=nueva-anterior
                if diferencia:
                    cursor.execute('UPDATE productos SET cantidad=%s WHERE id=%s AND eliminado=FALSE',(nueva,pid))
                    descripcion=f'Existencia anterior: {anterior}; nueva: {nueva}.'
                    if nota:
                        descripcion+=' '+nota
                    cursor.execute(
                        'INSERT INTO movimientos_inventario (producto_id,tipo,cantidad,nota) VALUES (%s,%s,%s,%s)',
                        (pid,'Ajuste manual',diferencia,descripcion)
                    )
        if diferencia:
            flash(f'Existencia de «{producto["nombre"]}» ajustada de {anterior} a {nueva} unidades.','success')
        else:
            flash('La cantidad ya coincide con la existencia registrada; no hubo cambios.','success')
    except (ValueError,TypeError) as exc:
        flash(str(exc) or 'Revisa la cantidad introducida.','error')
    except psycopg.Error:
        app.logger.exception('Error ajustando existencias exactas')
        flash('No fue posible guardar el ajuste de existencias.','error')
    return redirect(url_for('administracion'))


@app.post('/administracion/producto/<int:pid>/eliminar')
@solo_admin
def eliminar_producto(pid):
    """Retirar del catálogo sin borrar facturas, pedidos ni movimientos históricos."""
    validar_csrf()
    if request.form.get('confirmacion')!='ELIMINAR':
        abort(400)
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre FROM productos WHERE id=%s AND eliminado=FALSE FOR UPDATE',(pid,))
                producto=cursor.fetchone()
                if not producto:
                    raise ValueError('El producto ya no se encuentra en el catálogo.')
                # Un pedido sin resolver necesita conservar su producto disponible
                # o debe ser rechazado/cancelado antes de retirarlo.
                cursor.execute("""
                    SELECT 1 FROM pedido_detalles d
                    JOIN pedidos p ON p.id=d.pedido_id
                    WHERE d.producto_id=%s AND p.estado IN ('Pendiente','Aceptado')
                    LIMIT 1
                """,(pid,))
                if cursor.fetchone():
                    raise ValueError('Este producto está en un pedido pendiente o aceptado. Resuelve ese pedido antes de eliminarlo.')
                cursor.execute(
                    'UPDATE productos SET eliminado=TRUE,activo=FALSE,eliminado_en=now() WHERE id=%s AND eliminado=FALSE',
                    (pid,)
                )
        flash(f'Producto «{producto["nombre"]}» eliminado del catálogo. Puedes recuperarlo abajo.','success')
    except ValueError as exc:
        flash(str(exc),'error')
    except psycopg.Error:
        app.logger.exception('Error eliminando producto del catálogo')
        flash('No se pudo eliminar el producto.','error')
    return redirect(url_for('administracion'))


@app.post('/administracion/producto/<int:pid>/recuperar')
@solo_admin
def recuperar_producto(pid):
    """Recuperación explícita: se mantiene desactivado hasta que se reactive."""
    validar_csrf()
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    'UPDATE productos SET eliminado=FALSE,eliminado_en=NULL,activo=FALSE WHERE id=%s AND eliminado=TRUE RETURNING nombre',
                    (pid,)
                )
                recuperado=cursor.fetchone()
                if not recuperado:
                    raise ValueError('No se encontró un producto eliminado con ese identificador.')
        flash(f'Producto «{recuperado["nombre"]}» recuperado como inactivo. Actívalo cuando quieras ponerlo a la venta.','success')
    except ValueError as exc:
        flash(str(exc),'error')
    except psycopg.Error:
        app.logger.exception('Error recuperando producto')
        flash('No se pudo recuperar el producto.','error')
    return redirect(url_for('administracion'))


@app.post('/administracion/producto/<int:pid>/estado')
@solo_admin
def cambiar_estado_producto(pid):
    validar_csrf()
    nuevo = request.form.get('activo')
    if nuevo not in ('true','false'):
        abort(400)
    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute('UPDATE productos SET activo=%s WHERE id=%s AND eliminado=FALSE', (nuevo == 'true', pid))
                if cursor.rowcount != 1:
                    abort(404)
        flash('Estado del producto actualizado.', 'success')
    except psycopg.Error:
        app.logger.exception('Error cambiando estado del producto')
        flash('No se pudo cambiar el estado.', 'error')
    return redirect(url_for('administracion'))


@app.post('/ventas/<int:venta_id>/anular')
@solo_admin
def anular_venta(venta_id):
    validar_csrf()
    motivo = request.form.get('motivo','').strip()
    devolver = request.form.get('devolver') == 'si'
    if not motivo or len(motivo) > 250:
        flash('Indica un motivo de anulación (máximo 250 caracteres).', 'error')
        return redirect(url_for('listado_ventas'))
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,estado FROM ventas WHERE id=%s FOR UPDATE', (venta_id,))
                venta = cursor.fetchone()
                if venta is None:
                    abort(404)
                if venta['estado'] != 'Activa':
                    flash('La factura ya fue anulada.', 'error')
                    return redirect(url_for('listado_ventas'))
                cursor.execute('SELECT producto_id,nombre_producto,cantidad FROM venta_detalles WHERE venta_id=%s ORDER BY producto_id', (venta_id,))
                detalles = cursor.fetchall()
                if devolver:
                    ids = sorted({d['producto_id'] for d in detalles if d['producto_id'] is not None})
                    if ids:
                        cursor.execute('SELECT id FROM productos WHERE id = ANY(%s) ORDER BY id FOR UPDATE', (ids,))
                        existentes = {r['id'] for r in cursor.fetchall()}
                        if len(existentes) != len(ids):
                            raise ValueError('No se pueden devolver unidades: falta un producto original.')
                    for d in detalles:
                        if d['producto_id'] is None:
                            # No se devuelve inventario por el servicio de delivery.
                            if d['nombre_producto'] == 'Servicio de delivery':
                                continue
                            raise ValueError('No se pueden devolver unidades: falta un producto original.')
                        cursor.execute('UPDATE productos SET cantidad=cantidad+%s WHERE id=%s', (d['cantidad'],d['producto_id']))
                        cursor.execute('INSERT INTO movimientos_inventario (producto_id,tipo,cantidad,nota) VALUES (%s,%s,%s,%s)', (d['producto_id'],'Devolución anulación',d['cantidad'],f'Factura #{venta_id}: {motivo}'[:250]))
                cursor.execute("UPDATE ventas SET estado='Anulada',anulada_en=now(),motivo_anulacion=%s,inventario_devuelto=%s WHERE id=%s", (motivo,devolver,venta_id))
        flash(f'Factura #{venta_id} anulada correctamente.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except psycopg.Error:
        app.logger.exception('Error anulando factura')
        flash('No se pudo anular la factura.', 'error')
    return redirect(url_for('listado_ventas'))


@app.get('/reportes')
def reportes():
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""SELECT date_trunc('day',fecha)::date AS dia,
                           COUNT(*) AS facturas, COALESCE(SUM(total),0) AS total
                           FROM ventas WHERE estado='Activa' AND fecha >= CURRENT_DATE - INTERVAL '29 days'
                           GROUP BY 1 ORDER BY 1 DESC""")
                dias = cursor.fetchall()
                cursor.execute("""SELECT COALESCE(SUM(total),0) AS total,
                           COUNT(*) AS facturas FROM ventas
                           WHERE estado='Activa' AND fecha::date=CURRENT_DATE""")
                hoy = cursor.fetchone()
                cursor.execute("""SELECT COALESCE(SUM(total),0) AS total FROM ventas
                           WHERE estado='Activa' AND fecha >= date_trunc('week',CURRENT_TIMESTAMP)""")
                semana = cursor.fetchone()['total']
                cursor.execute("""SELECT COALESCE(SUM(total),0) AS total FROM ventas
                           WHERE estado='Activa' AND fecha >= date_trunc('month',CURRENT_TIMESTAMP)""")
                mes = cursor.fetchone()['total']
                cursor.execute("""SELECT d.nombre_producto, SUM(d.cantidad) AS unidades
                           FROM venta_detalles d JOIN ventas v ON v.id=d.venta_id
                           WHERE v.estado='Activa' GROUP BY d.nombre_producto
                           ORDER BY unidades DESC LIMIT 10""")
                populares = cursor.fetchall()
        return render_template('reportes.html',dias=dias,hoy=hoy,semana=semana,mes=mes,populares=populares)
    except psycopg.Error:
        app.logger.exception('Error cargando reportes')
        flash('No se pudieron consultar los reportes. Ejecuta la migración de Etapa 4.', 'error')
        return redirect(url_for('inicio'))

# Pedidos públicos: no requieren iniciar sesión. Los datos se validan en servidor.
@app.get('/pedir')
def pedidos_publicos():
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,precio,cantidad FROM productos WHERE activo=TRUE AND eliminado=FALSE AND cantidad>=5 ORDER BY nombre,id')
                productos=cursor.fetchall()
        return render_template('pedir.html',productos=productos,push_public_key=PUSH_PUBLIC_KEY)
    except psycopg.Error:
        app.logger.exception('Error mostrando catálogo público')
        abort(503)


@app.post('/pedir')
def enviar_pedido():
    validar_csrf()
    if request.form.get('sitio_web', ''):
        abort(400)
    nombre=request.form.get('nombre','').strip()
    telefono=request.form.get('telefono','').strip()
    if not 2<=len(nombre)<=100 or not 7<=len(telefono)<=30 or not all(c.isdigit() or c in '+- ()' for c in telefono):
        flash('Revisa tu nombre y teléfono.', 'error')
        return redirect(url_for('pedidos_publicos'))
    try:
        comentarios=request.form.get('comentarios','').strip()
        tipo_entrega=request.form.get('tipo_entrega','')
        direccion_entrega=request.form.get('direccion_entrega','').strip()
        fecha_texto=request.form.get('fecha_hora_entrega','').strip()
        if len(comentarios)>500:
            raise ValueError('El comentario no debe exceder 500 caracteres.')
        if tipo_entrega not in ('recoger','delivery'):
            raise ValueError('Selecciona recoger en el local o delivery.')
        if tipo_entrega == 'delivery':
            if not 10<=len(direccion_entrega)<=300:
                raise ValueError('Indica una dirección de entrega de 10 a 300 caracteres.')
        else:
            direccion_entrega=None
        if not fecha_texto:
            raise ValueError('Selecciona la fecha y hora para recibir el pedido.')
        try:
            fecha_seleccionada=datetime.strptime(fecha_texto,'%Y-%m-%dT%H:%M')
        except ValueError:
            raise ValueError('Fecha y hora inválidas.') from None
        zona_rd=ZoneInfo('America/Santo_Domingo')
        fecha_entrega=fecha_seleccionada.replace(tzinfo=zona_rd)
        ahora_rd=datetime.now(zona_rd)
        if fecha_entrega < ahora_rd-timedelta(minutes=2):
            raise ValueError('La fecha y hora solicitadas no pueden estar en el pasado (hora de República Dominicana).')
        if fecha_entrega > ahora_rd+timedelta(days=60):
            raise ValueError('Solo puedes programar pedidos dentro de los próximos 60 días.')
        costo_delivery=Decimal('100.00') if tipo_entrega=='delivery' else Decimal('0.00')
        items=json.loads(request.form.get('items','[]'))
        if not isinstance(items,list) or not 1<=len(items)<=30:
            raise ValueError('Selecciona productos para el pedido.')
        cantidades={}
        variantes={}
        for item in items:
            if not isinstance(item,dict) or type(item.get('id')) is not int or type(item.get('cantidad')) is not int:
                raise ValueError('Productos inválidos.')
            pid,cant=item['id'],item['cantidad']
            relleno=item.get('relleno','')
            if not isinstance(relleno,str) or relleno not in ('','pizza','atun','pollo'):
                raise ValueError('Relleno inválido.')
            if pid<1 or not 1<=cant<=100:
                raise ValueError('Cantidad inválida.')
            cantidades[pid]=cantidades.get(pid,0)+cant
            clave=(pid,relleno)
            variantes[clave]=variantes.get(clave,0)+cant
        if any(q>100 for q in cantidades.values()):
            raise ValueError('Cantidad excesiva.')
        cliente_push=None
        try:
            datos_push=request.form.get('push_subscription','')
            if datos_push and len(datos_push)<=5000:
                cliente_push=suscripcion_push_valida(json.loads(datos_push))
        except (ValueError,TypeError,KeyError,json.JSONDecodeError):
            cliente_push=None
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,precio,cantidad,activo,eliminado FROM productos WHERE id=ANY(%s) ORDER BY id FOR SHARE', (list(cantidades),))
                productos=cursor.fetchall()
                if len(productos)!=len(cantidades):
                    raise ValueError('Un producto ya no está disponible.')
                total=Decimal('0')
                detalles=[]
                por_id={p['id']:p for p in productos}
                for producto in productos:
                    q=cantidades[producto['id']]
                    if q < 5:
                        raise ValueError('El mínimo es de 5 unidades por producto.')
                    if not producto['activo'] or producto['eliminado'] or producto['cantidad']<q:
                        raise ValueError('No hay suficientes unidades de '+producto['nombre'])
                for (pid,relleno),q in variantes.items():
                    producto=por_id[pid]
                    nombre_norm=''.join(
                        c for c in unicodedata.normalize('NFD',producto['nombre'].casefold())
                        if unicodedata.category(c)!='Mn'
                    )
                    es_tartico='tartic' in nombre_norm
                    if es_tartico and relleno not in ('pizza','atun','pollo'):
                        raise ValueError('Elige relleno Pizza, Atún o Pollo para los tarticos.')
                    if not es_tartico and relleno:
                        raise ValueError('Solo se puede elegir relleno para los tarticos.')
                    nombre_detalle=producto['nombre']
                    if relleno:
                        bonito={'pizza':'Pizza','atun':'Atún','pollo':'Pollo'}[relleno]
                        nombre_detalle+=f' (relleno: {bonito})'
                    if len(nombre_detalle)>120:
                        raise ValueError('El nombre del producto es demasiado largo.')
                    subtotal=producto['precio']*q
                    total+=subtotal
                    detalles.append((producto,q,subtotal,relleno or None,nombre_detalle))
                total+=costo_delivery
                cursor.execute('''
                    INSERT INTO pedidos(
                        cliente_nombre,cliente_telefono,nota,
                        tipo_entrega,direccion_entrega,fecha_entrega,costo_delivery,
                        total,total_estimado,estado
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                ''', (nombre,telefono,comentarios or None,tipo_entrega,direccion_entrega,
                      fecha_entrega,costo_delivery,total,total,'Pendiente'))
                pedido_id=cursor.fetchone()['id']
                for producto,q,subtotal,relleno,nombre_detalle in detalles:
                    cursor.execute('''
                        INSERT INTO pedido_detalles(
                          pedido_id,producto_id,nombre_producto,cantidad,
                          precio_unitario,subtotal,relleno
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ''',(pedido_id,producto['id'],nombre_detalle,q,producto['precio'],subtotal,relleno))
        session['ultimo_pedido_confirmado']=pedido_id
        if cliente_push:
            enviar_notificacion_push(
                cliente_push,'¡Pedido recibido! · Pa Picar',
                f'Recibimos tu pedido #{pedido_id}. Lo confirmaremos por WhatsApp.',
                f'/pedido-recibido/{pedido_id}'
            )
        avisar_pedido_a_empleados(pedido_id)
        return redirect(url_for('pedido_recibido',pedido_id=pedido_id))
    except (ValueError,TypeError,json.JSONDecodeError) as exc:
        flash(str(exc),'error')
    except psycopg.Error:
        app.logger.exception('Error guardando pedido público')
        flash('No se pudo registrar el pedido. Intenta de nuevo.', 'error')
    return redirect(url_for('pedidos_publicos'))


@app.get('/pedido-recibido/<int:pedido_id>')
def pedido_recibido(pedido_id):
    # No mostrar datos personales ni detalles de pedidos por ID público.
    visible=session.get('ultimo_pedido_confirmado')==pedido_id
    return render_template('pedido_recibido.html',numero_pedido=pedido_id if visible else None)


@app.post('/administracion/pedidos/<int:pedido_id>/<accion>')
def procesar_pedido(pedido_id, accion):
    validar_csrf()
    if accion not in ('aceptar', 'rechazar', 'cancelar', 'pagar'):
        abort(404)
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,estado,costo_delivery FROM pedidos WHERE id=%s FOR UPDATE', (pedido_id,))
                pedido=cursor.fetchone()
                if pedido is None:
                    abort(404)
                estado=pedido['estado']
                if accion in ('aceptar','rechazar') and estado != 'Pendiente':
                    raise ValueError('Solo se pueden aceptar o rechazar pedidos pendientes.')
                if accion in ('pagar','cancelar') and estado != 'Aceptado':
                    raise ValueError('Solo se pueden cobrar o cancelar pedidos aceptados.')
                if accion=='rechazar':
                    motivo_rechazo = request.form.get('motivo_rechazo', '').strip()
                    if not 5 <= len(motivo_rechazo) <= 250:
                        raise ValueError('Explica el motivo del rechazo (5 a 250 caracteres).')
                    cursor.execute(
                        "UPDATE pedidos SET estado='Rechazado',motivo_rechazo=%s,procesado_en=now() WHERE id=%s",
                        (motivo_rechazo,pedido_id)
                    )
                    mensaje='Pedido rechazado con motivo registrado.'
                else:
                    cursor.execute('SELECT producto_id,cantidad,nombre_producto,precio_unitario FROM pedido_detalles WHERE pedido_id=%s ORDER BY producto_id', (pedido_id,))
                    detalles=cursor.fetchall()
                    if not detalles or any(d['producto_id'] is None for d in detalles):
                        raise ValueError('Pedido sin productos válidos.')
                    if accion=='aceptar':
                        # Reserva de existencias. No crea venta ni ingresos.
                        for d in detalles:
                            cursor.execute('UPDATE productos SET cantidad=cantidad-%s WHERE id=%s AND activo=TRUE AND eliminado=FALSE AND cantidad >= %s RETURNING id', (d['cantidad'],d['producto_id'],d['cantidad']))
                            if cursor.fetchone() is None:
                                raise ValueError('No hay existencias suficientes para '+d['nombre_producto'])
                        cursor.execute("UPDATE pedidos SET estado='Aceptado',procesado_en=now() WHERE id=%s",(pedido_id,))
                        mensaje='Pedido aceptado. Inventario reservado; aún no se registró una venta.'
                    elif accion=='cancelar':
                        # Devuelve la reserva; operación atómica con cambio de estado.
                        for d in detalles:
                            cursor.execute('UPDATE productos SET cantidad=cantidad+%s WHERE id=%s RETURNING id',(d['cantidad'],d['producto_id']))
                            if cursor.fetchone() is None:
                                raise ValueError('No se pudo devolver el inventario: producto inexistente.')
                        cursor.execute("UPDATE pedidos SET estado='Cancelado',procesado_en=now() WHERE id=%s",(pedido_id,))
                        mensaje='Pedido cancelado. Unidades devueltas al inventario.'
                    else:
                        metodo=request.form.get('metodo_pago','')
                        if metodo not in ('Efectivo','Transferencia'):
                            raise ValueError('Selecciona un método de pago válido.')
                        costo_delivery=pedido['costo_delivery'] or Decimal('0')
                        total=sum((d['precio_unitario']*d['cantidad'] for d in detalles),Decimal('0')) + costo_delivery
                        cursor.execute('INSERT INTO ventas(metodo_pago,total) VALUES (%s,%s) RETURNING id',(metodo,total))
                        venta_id=cursor.fetchone()['id']
                        for d in detalles:
                            subtotal=d['precio_unitario']*d['cantidad']
                            cursor.execute('INSERT INTO venta_detalles(venta_id,producto_id,nombre_producto,cantidad,precio_unitario,subtotal) VALUES (%s,%s,%s,%s,%s,%s)',(venta_id,d['producto_id'],d['nombre_producto'],d['cantidad'],d['precio_unitario'],subtotal))
                        if costo_delivery > 0:
                            # Línea de servicio para que la factura y los reportes
                            # incluyan delivery, sin modificar inventario de productos.
                            cursor.execute('''
                                INSERT INTO venta_detalles(
                                    venta_id,producto_id,nombre_producto,cantidad,
                                    precio_unitario,subtotal
                                ) VALUES (%s,NULL,%s,1,%s,%s)
                            ''',(venta_id,'Servicio de delivery',costo_delivery,costo_delivery))
                        # El inventario ya fue descontado al aceptar el pedido.
                        cursor.execute("UPDATE pedidos SET estado='Pagado',venta_id=%s,procesado_en=now() WHERE id=%s",(venta_id,pedido_id))
                        mensaje='Pago confirmado. Venta #'+str(venta_id)+' registrada.'
        flash(mensaje,'success')
    except ValueError as exc:
        flash(str(exc),'error')
    except psycopg.Error:
        app.logger.exception('Error procesando pedido')
        flash('No se pudo procesar el pedido.','error')
    return redirect(url_for('pedidos', estado={'aceptar':'Aceptado','rechazar':'Rechazado',
                                                'cancelar':'Cancelado','pagar':'Pagado'}[accion]))

# Administración de usuarios: solo administradores autorizados pueden gestionar
# cuentas. El propietario original no se puede editar ni desactivar desde esta UI.
def permisos_desde_formulario(rol):
    if rol not in ('administrador', 'vendedor'):
        raise ValueError('Selecciona un tipo de usuario válido.')
    permisos = {clave: request.form.get('permiso_' + clave) == 'on'
                for clave in PERMISOS}
    if rol == 'vendedor' and (permisos['administracion'] or permisos['usuarios']):
        raise ValueError('Para dar acceso a Administración, selecciona el rol administrador.')
    if permisos['usuarios'] and not permisos['administracion']:
        raise ValueError('Gestionar usuarios requiere el acceso a Administración.')
    if permisos['usuarios'] and not g.usuario['es_propietario']:
        raise ValueError('Solo el propietario puede delegar la gestión de usuarios.')
    for clave, permitido in permisos.items():
        if permitido and not g.usuario['permiso_' + clave]:
            raise ValueError('No puedes otorgar un permiso que no tienes.')
    return permisos

@app.get('/administracion/usuarios')
@solo_gestor_usuarios
def usuarios_admin():
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT id, usuario, rol, activo, creado_en, es_propietario,
                           permiso_productos, permiso_ventas, permiso_pedidos,
                           permiso_administracion, permiso_reportes, permiso_usuarios
                    FROM usuarios ORDER BY es_propietario DESC, usuario ASC
                """)
                usuarios = cursor.fetchall()
        return render_template('usuarios.html', usuarios=usuarios,
                               permisos_disponibles=ETIQUETAS_PERMISOS)
    except psycopg.Error:
        app.logger.exception('Error consultando usuarios')
        flash('No se pudieron cargar los usuarios.', 'error')
        return redirect(url_for('administracion'))

@app.post('/administracion/usuarios/nuevo')
@solo_gestor_usuarios
def crear_usuario_web():
    validar_csrf()
    nombre = request.form.get('usuario','').strip()
    clave = request.form.get('clave','')
    rol = request.form.get('rol','vendedor')
    try:
        if not 3 <= len(nombre) <= 80 or not all(
                c.isalnum() or c in '_.-' for c in nombre):
            raise ValueError('El usuario debe tener entre 3 y 80 letras, números, punto, guion o _.')
        if not 12 <= len(clave) <= 128:
            raise ValueError('La contraseña debe tener entre 12 y 128 caracteres.')
        permisos = permisos_desde_formulario(rol)
        if not any(permisos.values()):
            raise ValueError('Selecciona al menos un apartado o desactiva posteriormente la cuenta.')
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id FROM usuarios WHERE lower(usuario)=lower(%s) LIMIT 1', (nombre,))
                if cursor.fetchone():
                    raise ValueError('Ya existe un usuario con ese nombre.')
                cursor.execute("""
                    INSERT INTO usuarios(
                       usuario,clave_hash,rol,activo,permiso_productos,
                       permiso_ventas,permiso_pedidos,permiso_administracion,
                       permiso_reportes,permiso_usuarios,es_propietario)
                    VALUES (%s,%s,%s,TRUE,%s,%s,%s,%s,%s,%s,FALSE)
                """, (nombre,generate_password_hash(clave),rol,
                      *(permisos[p] for p in PERMISOS)))
        flash('Usuario creado con los accesos seleccionados.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except psycopg.Error:
        app.logger.exception('Error creando usuario')
        flash('No fue posible crear el usuario. Revisa el nombre y vuelve a intentar.', 'error')
    return redirect(url_for('usuarios_admin'))

@app.post('/administracion/usuarios/<int:uid>/permisos')
@solo_gestor_usuarios
def actualizar_usuario_web(uid):
    validar_csrf()
    if uid == g.usuario['id']:
        abort(403)
    rol = request.form.get('rol','')
    try:
        permisos = permisos_desde_formulario(rol)
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,es_propietario,permiso_usuarios FROM usuarios WHERE id=%s FOR UPDATE',(uid,))
                objetivo=cursor.fetchone()
                if not objetivo:
                    abort(404)
                if objetivo['es_propietario']:
                    abort(403)
                if objetivo['permiso_usuarios'] and not g.usuario['es_propietario']:
                    abort(403)
                cursor.execute("""
                    UPDATE usuarios SET rol=%s,permiso_productos=%s,
                        permiso_ventas=%s,permiso_pedidos=%s,
                        permiso_administracion=%s,permiso_reportes=%s,
                        permiso_usuarios=%s WHERE id=%s
                """,(rol,*(permisos[p] for p in PERMISOS),uid))
        flash('Accesos del usuario actualizados.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except psycopg.Error:
        app.logger.exception('Error actualizando permisos')
        flash('No se pudieron guardar los cambios.', 'error')
    return redirect(url_for('usuarios_admin'))

@app.post('/administracion/usuarios/<int:uid>/estado')
@solo_gestor_usuarios
def activar_usuario_web(uid):
    validar_csrf()
    if uid == g.usuario['id']:
        abort(403)
    habilitar = request.form.get('activo') == 'true'
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,es_propietario,permiso_usuarios FROM usuarios WHERE id=%s FOR UPDATE',(uid,))
                objetivo=cursor.fetchone()
                if not objetivo:
                    abort(404)
                if objetivo['es_propietario']:
                    abort(403)
                if objetivo['permiso_usuarios'] and not g.usuario['es_propietario']:
                    abort(403)
                cursor.execute('UPDATE usuarios SET activo=%s WHERE id=%s',(habilitar,uid))
        flash('Cuenta activada.' if habilitar else 'Cuenta desactivada. Su sesión dejará de tener acceso.', 'success')
    except psycopg.Error:
        app.logger.exception('Error al cambiar estado del usuario')
        flash('No se pudo cambiar el estado de la cuenta.', 'error')
    return redirect(url_for('usuarios_admin'))

@app.post('/administracion/usuarios/<int:uid>/contrasena')
@solo_gestor_usuarios
def clave_usuario_web(uid):
    validar_csrf()
    if uid == g.usuario['id']:
        abort(403)
    clave = request.form.get('clave','')
    if not 12 <= len(clave) <= 128:
        flash('La contraseña debe tener entre 12 y 128 caracteres.', 'error')
        return redirect(url_for('usuarios_admin'))
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,es_propietario,permiso_usuarios FROM usuarios WHERE id=%s FOR UPDATE',(uid,))
                objetivo=cursor.fetchone()
                if not objetivo:
                    abort(404)
                if objetivo['es_propietario']:
                    abort(403)
                if objetivo['permiso_usuarios'] and not g.usuario['es_propietario']:
                    abort(403)
                cursor.execute('UPDATE usuarios SET clave_hash=%s WHERE id=%s',
                               (generate_password_hash(clave),uid))
        flash('Contraseña actualizada.', 'success')
    except psycopg.Error:
        app.logger.exception('Error actualizando contraseña')
        flash('No se pudo cambiar la contraseña.', 'error')
    return redirect(url_for('usuarios_admin'))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Accesible desde otros dispositivos de la misma red privada (modo de pruebas).
    app.run(host="127.0.0.1", port=5000, debug=False)
