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
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=1024*1024)
if os.getenv('COOKIE_SECURE', 'false').lower() == 'true':
    app.config['SESSION_COOKIE_SECURE'] = True



def conectar():
    """Abrir una conexión con la base PostgreSQL existente."""
    return psycopg.connect(
        dbname=os.getenv("DATABASE_NAME", "base_de_pa-picar"),
        user=os.getenv("DATABASE_USER", "postgres"),
        password=os.getenv("DATABASE_PASSWORD", ""),
        host=os.getenv("DATABASE_HOST", "127.0.0.1"),
        port=os.getenv("DATABASE_PORT", "5432"),
        connect_timeout=5,
    )


# Etapa 5: autenticación y roles. Ejecutar migracion_etapa5.sql antes de iniciar.
@app.before_request
def exigir_acceso():
    g.usuario = None
    if request.endpoint == 'static':
        return
    if request.endpoint in ('login', 'logout'):
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

    total_ventas = Decimal('0')
    try:
        with conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("SELECT COALESCE(SUM(total),0) FROM ventas WHERE fecha::date = CURRENT_DATE AND estado = 'Activa'")
                total_ventas = cursor.fetchone()[0]
    except psycopg.Error:
        pass  # La tabla ventas se crea al ejecutar la migración.
    total_unidades = sum(item["cantidad"] or 0 for item in productos)
    return render_template(
        "index.html",
        productos=productos,
        cantidad_productos=len(productos),
        total_unidades=total_unidades,
        base_disponible=base_disponible,
        total_ventas=total_ventas,
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
        return render_template('administracion.html',productos=productos,movimientos=movimientos)
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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Accesible desde otros dispositivos de la misma red privada (modo de pruebas).
    app.run(host="127.0.0.1", port=5000, debug=False)
