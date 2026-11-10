"""Reinyecta EXACTAMENTE el mismo event_id de ReservaSolicitada.
Uso dentro de loans-worker: python scripts/demo_reentrega.py <prestamo_id>
"""
import sys,json
from shared.core import Outbox,database,session_factory
from shared.broker import connect,topology,publish,EX
if len(sys.argv)!=2:raise SystemExit('Uso: demo_reentrega.py PRESTAMO_ID')
loan_id=sys.argv[1];Session=session_factory(database())
with Session() as db:
    rows=db.query(Outbox).filter(Outbox.route=='reserva.solicitada').all()
    original=next((row for row in rows if json.loads(row.body).get('prestamo_id')==loan_id),None)
    if not original:raise SystemExit('No existe comando ReservaSolicitada para '+loan_id)
    if not original.sent:raise SystemExit('Aún no se publicó originalmente; espera que sea enviado')
    body=json.loads(original.body)
con=connect()
try:
    ch=con.channel();topology(ch);ch.confirm_delivery()
    publish(ch,EX,original.route,body)
    print('Reinyectado el MISMO event_id:',body['event_id'],'para',loan_id)
    print('Comprueba inbox de Inventario y que stock/reservas no cambien.')
finally:con.close()
