import logging,threading
from sqlalchemy.orm import Session
from shared.core import Base,event,emit
from shared.broker import consume_loop,outbox_loop
from services.loans.app import engine,SessionLocal,Loan
logging.basicConfig(level=logging.INFO)

def handle(db:Session,msg):
    typ=msg['type'];lid=msg['prestamo_id']
    loan=db.query(Loan).filter(Loan.id==lid).with_for_update().first()
    if not loan:
        # Si un préstamo desapareciera, el mensaje se debe investigar desde DLQ.
        raise RuntimeError('Préstamo no encontrado: '+lid)
    if typ=='InventarioReservado':
        if loan.status=='PENDIENTE_INVENTARIO':loan.status='APROBADA';loan.reason=None
        elif loan.status in ('CANCELACION_PENDIENTE','CANCELADA','CANCELADA_RESERVA_VENCIDA'):
            emit(db,'reserva.liberar',event('ReservaLiberacionSolicitada',lid,{'producto_id':loan.product_id}))
    elif typ=='InventarioInsuficiente':
        if loan.status=='PENDIENTE_INVENTARIO':loan.status='CANCELADA_SIN_STOCK';loan.reason='Inventario insuficiente'
    elif typ=='InventarioLiberado':
        if loan.status=='CANCELACION_PENDIENTE':loan.status='CANCELADA';loan.reason='Reserva liberada'
    elif typ=='InventarioEntregado':
        if loan.status=='ENTREGA_PENDIENTE':loan.status='COMPLETADA';loan.reason='Entrega confirmada'
    elif typ=='InventarioExpirado':
        if loan.status in ('APROBADA','PENDIENTE_INVENTARIO','ENTREGA_PENDIENTE'):
            loan.status='CANCELADA_RESERVA_VENCIDA';loan.reason='La reserva venció o dejó de estar disponible'
        elif loan.status=='CANCELACION_PENDIENTE':loan.status='CANCELADA';loan.reason='Reserva liberada por vencimiento'
    else:raise ValueError('Evento desconocido: '+typ)

def main():
    Base.metadata.create_all(engine)
    threading.Thread(target=outbox_loop,args=(SessionLocal,),daemon=True).start()
    consume_loop('loans',SessionLocal,handle)
if __name__=='__main__':main()
