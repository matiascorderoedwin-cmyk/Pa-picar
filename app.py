"""Pa Picar: catálogo, facturación y administración de inventario."""
import logging
import os
import secrets
import json
from functools import wraps
from datetime import timedelta
from datetime import datetime
from decimal import Decimal, InvalidOperation

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for, session, abort, g
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


# Etapa 5: autenticación y roles. Ejecutar migracion_etapa5.sql antes de iniciar.
@app.before_request
def exigir_acceso():
    g.usuario = None
    if request.endpoint == 'static':
        return
    if request.endpoint in ('login', 'logout', 'pedidos_publicos', 'enviar_pedido', 'pedido_recibido'):
        return
    uid = session.get('usuario_id')
    if not uid:
        return redirect(url_for('login'))
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id, usuario, rol FROM usuarios WHERE id=%s AND activo=TRUE', (uid,))
                g.usuario = cursor.fetchone()
    except psycopg.Error:
        app.logger.exception('Error verificando sesión')
        abort(503)
    if g.usuario is None:
        session.clear()
        return redirect(url_for('login'))

def solo_admin(fn):
    @wraps(fn)
    def protegido(*args, **kwargs):
        if not g.usuario or g.usuario['rol'] != 'administrador':
            abort(403)
        return fn(*args, **kwargs)
    return protegido

@app.context_processor
def usuario_actual():
    return {'usuario_actual': getattr(g, 'usuario', None)}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if session.get('usuario_id'):
            return redirect(url_for('inicio'))
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
        return redirect(url_for('inicio'))
    flash('Usuario o contraseña incorrectos.', 'error')
    return render_template('login.html'), 401

@app.post('/logout')
def logout():
    validar_csrf()
    session.clear()
    return redirect(url_for('login'))

@app.cli.command('crear-usuario')
def crear_usuario():
    """Crear usuario con solicitud interactiva de contraseña (sin exponerla en consola)."""
    import click
    nombre = click.prompt('Usuario').strip()
    rol = click.prompt('Rol', type=click.Choice(['administrador', 'vendedor']))
    clave = click.prompt('Contraseña (mínimo 12 caracteres)', hide_input=True, confirmation_prompt=True)
    if not (3 <= len(nombre) <= 80) or len(clave) < 12:
        raise click.ClickException('Usuario de 3-80 caracteres y contraseña de 12 o más caracteres.')
    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute('INSERT INTO usuarios(usuario,clave_hash,rol) VALUES (%s,%s,%s)', (nombre,generate_password_hash(clave),rol))
    except psycopg.Error as exc:
        raise click.ClickException('No se pudo crear el usuario. Verifica la migración y que no exista ese nombre.') from exc
    click.echo('Usuario creado correctamente.')

@app.get("/")
def inicio():
    productos = []
    base_disponible = True
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT id, nombre, precio, cantidad "
                    "FROM productos WHERE activo = TRUE ORDER BY nombre ASC"
                )
                productos = cursor.fetchall()
    except psycopg.Error:
        app.logger.exception("No fue posible consultar la tabla productos")
        flash("No se pudo consultar PostgreSQL. Revisa la contraseña, el servicio y el nombre de la base.", "error")
        base_disponible = False

    # Resumen diario en hora local de República Dominicana (independiente del huso del servidor).
    resumen = {'total': Decimal('0'), 'facturas': 0, 'efectivo': Decimal('0'), 'transferencia': Decimal('0')}
    ultimas_ventas = []
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(total),0) AS total,
                           COUNT(*) AS facturas,
                           COALESCE(SUM(total) FILTER (WHERE metodo_pago='Efectivo'),0) AS efectivo,
                           COALESCE(SUM(total) FILTER (WHERE metodo_pago='Transferencia'),0) AS transferencia
                    FROM ventas
                    WHERE estado='Activa'
                      AND (fecha AT TIME ZONE 'America/Santo_Domingo')::date =
                          (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santo_Domingo')::date
                """)
                resumen = cursor.fetchone()
                cursor.execute("""
                    SELECT id, fecha AT TIME ZONE 'America/Santo_Domingo' AS fecha_local,
                           total, metodo_pago
                    FROM ventas WHERE estado='Activa'
                    ORDER BY fecha DESC LIMIT 5
                """)
                ultimas_ventas = cursor.fetchall()
    except psycopg.Error:
        app.logger.exception('No se pudo cargar el resumen de ventas')
        flash('No se pudo consultar el resumen de ventas.', 'error')
    total_unidades = sum(item["cantidad"] or 0 for item in productos)
    inventario_bajo = [p for p in productos if (p['cantidad'] or 0) <= 10]
    return render_template(
        "index.html",
        productos=productos,
        cantidad_productos=len(productos),
        total_unidades=total_unidades,
        base_disponible=base_disponible,
        total_ventas=resumen['total'],
        facturas_hoy=resumen['facturas'],
        ventas_efectivo=resumen['efectivo'],
        ventas_transferencia=resumen['transferencia'],
        ultimas_ventas=ultimas_ventas,
        inventario_bajo=inventario_bajo,
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
                cursor.execute('SELECT id, nombre, precio, cantidad FROM productos WHERE activo = TRUE ORDER BY nombre, id')
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
                cursor.execute('SELECT id,nombre,precio,cantidad,activo FROM productos WHERE id = ANY(%s) ORDER BY id FOR UPDATE', (list(cantidades),))
                productos = cursor.fetchall()
                if len(productos) != len(cantidades):
                    raise ValueError('Hay productos que ya no existen')
                total = Decimal('0')
                detalles=[]
                for producto in productos:
                    q=cantidades[producto['id']]
                    if not producto['activo']:
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
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,fecha,metodo_pago,total,estado FROM ventas ORDER BY id DESC LIMIT 100')
                ventas=cursor.fetchall()
        return render_template('ventas.html',ventas=ventas)
    except psycopg.Error:
        flash('Ejecuta primero la migración de la etapa 2.', 'error')
        return redirect(url_for('inicio'))



@app.get('/administracion')
@solo_admin
def administracion():
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,precio,cantidad,activo FROM productos ORDER BY activo DESC,nombre,id')
                productos=cursor.fetchall()
                cursor.execute('SELECT m.id,m.fecha,m.tipo,m.cantidad,m.nota,p.nombre FROM movimientos_inventario m JOIN productos p ON p.id=m.producto_id ORDER BY m.id DESC LIMIT 50')
                movimientos=cursor.fetchall()
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('''SELECT p.id,p.cliente_nombre,p.cliente_telefono,p.total,p.estado,p.creado_en,
                               COALESCE(json_agg(json_build_object('nombre',d.nombre_producto,'cantidad',d.cantidad,'precio',d.precio_unitario)
                               ORDER BY d.id) FILTER (WHERE d.id IS NOT NULL),'[]'::json) AS detalles
                               FROM pedidos p LEFT JOIN pedido_detalles d ON d.pedido_id=p.id
                               GROUP BY p.id ORDER BY p.creado_en DESC LIMIT 100''')
                pedidos=cursor.fetchall()
        return render_template('administracion.html',productos=productos,movimientos=movimientos,pedidos=pedidos)
    except psycopg.Error:
        app.logger.exception('Error en administración')
        flash('No se pudo abrir administración. Ejecuta migracion_etapa3.sql.', 'error')
        return redirect(url_for('inicio'))


def validar_csrf():
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','')):
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
                cursor.execute('UPDATE productos SET nombre=%s,precio=%s WHERE id=%s',(nombre,precio,pid))
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
                cursor.execute('SELECT cantidad FROM productos WHERE id=%s FOR UPDATE',(pid,))
                producto=cursor.fetchone()
                if not producto or producto['cantidad'] is None or producto['cantidad']+cambio<0:
                    raise ValueError('Existencias insuficientes o producto inexistente.')
                cursor.execute('UPDATE productos SET cantidad=cantidad+%s WHERE id=%s',(cambio,pid))
                cursor.execute('INSERT INTO movimientos_inventario (producto_id,tipo,cantidad,nota) VALUES (%s,%s,%s,%s)',(pid,tipo,cambio,nota))
        flash('Movimiento de inventario guardado.','success')
    except (ValueError,TypeError) as exc:
        flash(str(exc) if str(exc) else 'Cantidad o tipo de movimiento inválido.','error')
    except psycopg.Error:
        app.logger.exception('Error registrando movimiento')
        flash('No se pudo guardar el movimiento.','error')
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
                cursor.execute('UPDATE productos SET activo=%s WHERE id=%s', (nuevo == 'true', pid))
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
@solo_admin
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
                cursor.execute('SELECT id,nombre,precio,cantidad FROM productos WHERE activo=TRUE AND cantidad>0 ORDER BY nombre,id')
                productos=cursor.fetchall()
        return render_template('pedir.html',productos=productos)
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
        items=json.loads(request.form.get('items','[]'))
        if not isinstance(items,list) or not 1<=len(items)<=30:
            raise ValueError('Selecciona productos para el pedido.')
        cantidades={}
        for item in items:
            if not isinstance(item,dict) or type(item.get('id')) is not int or type(item.get('cantidad')) is not int:
                raise ValueError('Productos inválidos.')
            pid,cant=item['id'],item['cantidad']
            if pid<1 or not 1<=cant<=100:
                raise ValueError('Cantidad inválida.')
            cantidades[pid]=cantidades.get(pid,0)+cant
        if any(q>100 for q in cantidades.values()):
            raise ValueError('Cantidad excesiva.')
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,nombre,precio,cantidad,activo FROM productos WHERE id=ANY(%s) ORDER BY id', (list(cantidades),))
                productos=cursor.fetchall()
                if len(productos)!=len(cantidades):
                    raise ValueError('Un producto ya no está disponible.')
                total=Decimal('0')
                detalles=[]
                for producto in productos:
                    q=cantidades[producto['id']]
                    if not producto['activo'] or producto['cantidad']<q:
                        raise ValueError('No hay suficientes unidades de '+producto['nombre'])
                    subtotal=producto['precio']*q
                    total+=subtotal
                    detalles.append((producto,q,subtotal))
                cursor.execute('INSERT INTO pedidos(cliente_nombre,cliente_telefono,total,total_estimado,estado) VALUES (%s,%s,%s,%s,%s) RETURNING id', (nombre,telefono,total,total,'Pendiente'))
                pedido_id=cursor.fetchone()['id']
                for producto,q,subtotal in detalles:
                    cursor.execute('INSERT INTO pedido_detalles(pedido_id,producto_id,nombre_producto,cantidad,precio_unitario,subtotal) VALUES (%s,%s,%s,%s,%s,%s)',(pedido_id,producto['id'],producto['nombre'],q,producto['precio'],subtotal))
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
    return render_template('pedido_recibido.html')


@app.post('/administracion/pedidos/<int:pedido_id>/<accion>')
@solo_admin
def procesar_pedido(pedido_id, accion):
    validar_csrf()
    if accion not in ('aceptar', 'rechazar', 'cancelar', 'pagar'):
        abort(404)
    try:
        with conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute('SELECT id,estado FROM pedidos WHERE id=%s FOR UPDATE', (pedido_id,))
                pedido=cursor.fetchone()
                if pedido is None:
                    abort(404)
                estado=pedido['estado']
                if accion in ('aceptar','rechazar') and estado != 'Pendiente':
                    raise ValueError('Solo se pueden aceptar o rechazar pedidos pendientes.')
                if accion in ('pagar','cancelar') and estado != 'Aceptado':
                    raise ValueError('Solo se pueden cobrar o cancelar pedidos aceptados.')
                if accion=='rechazar':
                    cursor.execute("UPDATE pedidos SET estado='Rechazado',procesado_en=now() WHERE id=%s", (pedido_id,))
                    mensaje='Pedido rechazado.'
                else:
                    cursor.execute('SELECT producto_id,cantidad,nombre_producto,precio_unitario FROM pedido_detalles WHERE pedido_id=%s ORDER BY producto_id', (pedido_id,))
                    detalles=cursor.fetchall()
                    if not detalles or any(d['producto_id'] is None for d in detalles):
                        raise ValueError('Pedido sin productos válidos.')
                    if accion=='aceptar':
                        # Reserva de existencias. No crea venta ni ingresos.
                        for d in detalles:
                            cursor.execute('UPDATE productos SET cantidad=cantidad-%s WHERE id=%s AND activo=TRUE AND cantidad >= %s RETURNING id', (d['cantidad'],d['producto_id'],d['cantidad']))
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
                        total=sum((d['precio_unitario']*d['cantidad'] for d in detalles),Decimal('0'))
                        cursor.execute('INSERT INTO ventas(metodo_pago,total) VALUES (%s,%s) RETURNING id',(metodo,total))
                        venta_id=cursor.fetchone()['id']
                        for d in detalles:
                            subtotal=d['precio_unitario']*d['cantidad']
                            cursor.execute('INSERT INTO venta_detalles(venta_id,producto_id,nombre_producto,cantidad,precio_unitario,subtotal) VALUES (%s,%s,%s,%s,%s,%s)',(venta_id,d['producto_id'],d['nombre_producto'],d['cantidad'],d['precio_unitario'],subtotal))
                        # El inventario ya fue descontado al aceptar el pedido.
                        cursor.execute("UPDATE pedidos SET estado='Pagado',venta_id=%s,procesado_en=now() WHERE id=%s",(venta_id,pedido_id))
                        mensaje='Pago confirmado. Venta #'+str(venta_id)+' registrada.'
        flash(mensaje,'success')
    except ValueError as exc:
        flash(str(exc),'error')
    except psycopg.Error:
        app.logger.exception('Error procesando pedido')
        flash('No se pudo procesar el pedido.','error')
    return redirect(url_for('administracion')+'#pedidos')

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Accesible desde otros dispositivos de la misma red privada (modo de pruebas).
    app.run(host="127.0.0.1", port=5000, debug=False)
