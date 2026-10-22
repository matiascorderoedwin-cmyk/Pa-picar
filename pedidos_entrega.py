"""Reglas de entrega compartidas por el formulario y el servidor."""
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

ZONA_PEDIDOS = ZoneInfo('America/Santo_Domingo')
COSTO_DELIVERY = Decimal('100.00')


def ahora_local():
    return datetime.now(ZONA_PEDIDOS)


def validar_entrega(form, ahora=None):
    ahora = ahora or ahora_local()
    modalidad = form.get('modalidad', '')
    if modalidad not in ('recoger', 'delivery'):
        raise ValueError('Selecciona recoger o delivery.')
    nota = form.get('nota', '').strip()
    direccion = form.get('direccion_entrega', '').strip()
    if len(nota) > 500:
        raise ValueError('Los comentarios admiten hasta 500 caracteres.')
    if modalidad == 'delivery' and not 5 <= len(direccion) <= 300:
        raise ValueError('Indica la dirección de entrega (5 a 300 caracteres).')
    fecha, hora = form.get('fecha_entrega', ''), form.get('hora_entrega', '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', fecha) or not re.fullmatch(r'\d{2}:\d{2}', hora):
        raise ValueError('Selecciona una fecha y hora de entrega válidas.')
    try:
        entrega = datetime.strptime(fecha + ' ' + hora, '%Y-%m-%d %H:%M').replace(tzinfo=ZONA_PEDIDOS)
    except ValueError:
        raise ValueError('Selecciona una fecha y hora de entrega válidas.') from None
    # El selector tiene precisión de minutos; el minuto actual es válido.
    if entrega < ahora.replace(second=0, microsecond=0):
        raise ValueError('La entrega no puede ser anterior a la hora actual de República Dominicana.')
    return modalidad, nota, direccion if modalidad == 'delivery' else None, entrega, COSTO_DELIVERY if modalidad == 'delivery' else Decimal('0.00')


def formato_hora_rd(valor):
    if valor is None:
        return 'Sin programar'
    return valor.astimezone(ZONA_PEDIDOS).strftime('%d/%m/%Y %I:%M %p')
