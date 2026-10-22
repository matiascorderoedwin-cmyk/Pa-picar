"""Run with TEST_DATABASE_PORT pointing to a disposable local PostgreSQL cluster."""
import os
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from pedidos_entrega import ZONA_PEDIDOS, validar_entrega, formato_hora_rd


class EntregaTests(unittest.TestCase):
    def test_hora_dominicana_y_limite_de_minuto(self):
        now = datetime(2026, 10, 22, 23, 59, 50, tzinfo=ZONA_PEDIDOS)
        form = dict(modalidad='recoger', fecha_entrega='2026-10-22', hora_entrega='23:59')
        self.assertEqual(validar_entrega(form, now)[4], Decimal('0'))
        form['hora_entrega'] = '23:58'
        with self.assertRaises(ValueError):
            validar_entrega(form, now)
        form.update(fecha_entrega='2026-10-23', hora_entrega='00:00')
        self.assertEqual(validar_entrega(form, now)[3].utcoffset(), timedelta(hours=-4))
        self.assertEqual(formato_hora_rd(datetime(2026, 10, 23, 3, 59, tzinfo=timezone.utc)), '22/10/2026 11:59 PM')

    def test_rechaza_datos_de_entrega_invalidos(self):
        base = dict(modalidad='delivery', direccion_entrega='Calle de prueba 123', fecha_entrega='2026-10-23', hora_entrega='12:00')
        now = datetime(2026, 10, 22, tzinfo=ZONA_PEDIDOS)
        self.assertEqual(validar_entrega(base, now)[4], Decimal('100'))
        for cambio in [dict(modalidad='otro'), dict(direccion_entrega=''), dict(nota='x'*501), dict(fecha_entrega='2026-02-30'), dict(hora_entrega='24:00'), dict(hora_entrega='12:00Z')]:
            with self.subTest(cambio=cambio), self.assertRaises(ValueError):
                validar_entrega(base | cambio, now)


@unittest.skipUnless(os.getenv('TEST_DATABASE_PORT'), 'Requires disposable local PostgreSQL')
class PedidoIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        import app as application
        cls.module = application
        cls.env = patch.dict(os.environ, dict(DATABASE_HOST='127.0.0.1', DATABASE_PORT=os.environ['TEST_DATABASE_PORT'], DATABASE_NAME='postgres', DATABASE_USER='preview', DATABASE_PASSWORD='', DATABASE_SSLMODE='disable', VERCEL_ENV='development'))
        cls.env.start()
        cls.db = staticmethod(application.conectar)
        cls.database = 'pedidos_test_' + uuid.uuid4().hex
        with cls.db() as conn:
            conn.autocommit = True
            conn.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(cls.database)))
        os.environ['DATABASE_NAME'] = cls.database
        with cls.db() as conn:
            conn.execute('CREATE TABLE productos (id SERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL, precio NUMERIC(12,2) NOT NULL, cantidad INTEGER NOT NULL)')
            for name in ['migracion_etapa2.sql', 'migracion_etapa3.sql', 'migracion_etapa4.sql', 'migracion_etapa5.sql', 'migracion_permisos_usuarios.sql', 'migracion_pedidos_publicos.sql', 'migracion_pedidos_estados.sql', 'migracion_motivo_rechazo.sql']:
                conn.execute(Path(name).read_text(encoding='utf-8'))
            conn.execute("INSERT INTO pedidos(cliente_nombre,cliente_telefono,total,total_estimado) VALUES ('Anterior','8095550100',50,50)")
            migration = next(Path('supabase/migrations').glob('*_pedidos_entrega.sql')).read_text(encoding='utf-8')
            conn.execute(migration)
            assert conn.execute('SELECT total,costo_delivery,entrega_en FROM pedidos').fetchone() == (Decimal('50'),Decimal('0'),None)
            conn.execute("INSERT INTO usuarios(usuario,clave_hash,rol,permiso_pedidos,permiso_ventas) VALUES ('test','unused','administrador',true,true)")
        application.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        import psycopg
        os.environ['DATABASE_NAME'] = 'postgres'
        with cls.db() as conn:
            conn.autocommit = True
            conn.execute(psycopg.sql.SQL('DROP DATABASE {}').format(psycopg.sql.Identifier(cls.database)))
        cls.env.stop()

    def setUp(self):
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as s:
            s['csrf'] = 'test-token'
            s['usuario_id'] = 1
        with self.db() as conn:
            conn.execute('TRUNCATE pedido_detalles,pedidos,venta_detalles,ventas,productos CASCADE')
            conn.execute("INSERT INTO productos(id,nombre,precio,cantidad) VALUES (1,'Pastelito',25,20)")
        self.form = dict(csrf='test-token', nombre='Cliente prueba', telefono='8095550100', items=json.dumps([dict(id=1,cantidad=3)]), modalidad='delivery', direccion_entrega='Calle prueba 123', nota='<script>alert(1)</script>', fecha_entrega=(datetime.now(ZONA_PEDIDOS)+timedelta(days=1)).strftime('%Y-%m-%d'), hora_entrega='12:30')

    def test_pedido_pago_recibo_y_panel(self):
        response = self.client.post('/pedir', data=self.form | dict(total='1',costo_delivery='0'))
        self.assertIn('/pedido-recibido/', response.location)
        with self.db() as conn:
            row = conn.execute('SELECT id,total,costo_delivery,entrega_en,nota FROM pedidos').fetchone()
            self.assertEqual(row[1:3], (Decimal('175'),Decimal('100')))
            self.assertEqual(row[3].astimezone(ZONA_PEDIDOS).hour,12)
            self.assertEqual(conn.execute('SELECT cantidad FROM productos').fetchone()[0],20)
        pid = row[0]
        panel = self.client.get('/pedidos').get_data(as_text=True)
        self.assertIn('Calle prueba 123',panel)
        self.assertIn('&lt;script&gt;',panel)
        for accion in ['aceptar','pagar','pagar']:
            self.client.post(f'/administracion/pedidos/{pid}/{accion}',data=dict(csrf='test-token',metodo_pago='Efectivo'))
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT cantidad FROM productos').fetchone()[0],17)
            venta = conn.execute('SELECT id,total,costo_delivery FROM ventas').fetchall()
            self.assertEqual(len(venta),1)
            self.assertEqual(venta[0][1:],(Decimal('175'),Decimal('100')))
        recibo = self.client.get(f'/recibo/{venta[0][0]}').get_data(as_text=True)
        self.assertIn('Delivery: RD$ 100.00',recibo)
        self.assertIn('Total: RD$ 175.00',recibo)

    def test_recoger_cancelar(self):
        self.client.post('/pedir',data=self.form | dict(modalidad='recoger'))
        with self.db() as conn:
            pid,total,costo,direccion = conn.execute('SELECT id,total,costo_delivery,direccion_entrega FROM pedidos').fetchone()
            self.assertEqual((total,costo,direccion),(Decimal('75'),Decimal('0'),None))
        for accion in ['aceptar','cancelar','cancelar']:
            self.client.post(f'/administracion/pedidos/{pid}/{accion}',data=dict(csrf='test-token'))
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT cantidad FROM productos').fetchone()[0],20)
            self.assertEqual(conn.execute('SELECT count(*) FROM ventas').fetchone()[0],0)

    def test_cantidades_invalidas_y_pasado_no_escriben(self):
        invalid = [dict(items=json.dumps([dict(id=1,cantidad=q)])) for q in [0,-1,1.5,True,'3',101,21]]
        invalid += [dict(items=json.dumps([dict(id=1,cantidad=60),dict(id=1,cantidad=60)])), dict(fecha_entrega='2000-01-01'), dict(modalidad='gratis'), dict(nota='x'*501), dict(direccion_entrega='')]
        for change in invalid:
            with self.subTest(change=change):
                result = self.client.post('/pedir',data=self.form | change)
                self.assertEqual(result.location,'/pedir')
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM pedidos').fetchone()[0],0)

    def test_preview_bloqueado_sin_base_aislada(self):
        import psycopg
        with patch.dict(os.environ, dict(VERCEL_ENV='preview',PREVIEW_DATABASE_ISOLATED='false')):
            with self.assertRaises(psycopg.OperationalError):
                self.db()

    def test_acceso_publico_sin_exponer_pedidos(self):
        client = self.module.app.test_client()
        self.assertEqual(client.get('/pedir').status_code,200)
        self.assertIn('/login',client.get('/pedidos').location)
        self.assertEqual(client.post('/pedir',data=self.form).status_code,400)


if __name__ == '__main__':
    unittest.main()
