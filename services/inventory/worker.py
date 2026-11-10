import os,time,logging,threading
from datetime import timedelta
from sqlalchemy.orm import Session
from shared.core import Base,event,emit,utcnow
from shared.broker import consume_loop,outbox_loop
from services.inventory.app import engine,SessionLocal,Item,Reservation,Movement
logging.basicConfig(level=logging.INFO)
TTL=int(os.getenv('RESERVATION_TTL_SECONDS','300'))

def handle(db:Session,msg):
    typ=msg['type']; p=msg['payload'];lid=msg['prestamo_id']
    if typ=='ReservaSolicitada':
        old=db.get(Reservation,lid)
        if old:
            if old.status=='RESERVED':
                emit(db,'inventario.reservado',event('InventarioReservado',lid,{'producto_id':old.product_id,'cantidad':old.quantity},msg['correlation_id']))
            elif old.status in ('TOMBSTONE','RELEASED','EXPIRED'):
                emit(db,'inventario.liberado',event('InventarioLiberado',lid,{'motivo':old.status},msg['correlation_id']))
            return
        s=db.query(Item).filter(Item.product_id==p['producto_id']).with_for_update().first()
        amount=int(p['cantidad'])
        if s and (s.quantity-s.reserved)>=amount:
            s.reserved+=amount
            db.add(Reservation(loan_id=lid,product_id=p['producto_id'],quantity=amount,status='RESERVED',expires=utcnow()+timedelta(seconds=TTL)))
            db.add(Movement(product_id=p['producto_id'],loan_id=lid,type='RESERVA',units=amount))
            emit(db,'inventario.reservado',event('InventarioReservado',lid,{'producto_id':p['producto_id'],'cantidad':amount},msg['correlation_id']))
        else:
            emit(db,'inventario.insuficiente',event('InventarioInsuficiente',lid,{'producto_id':p['producto_id'],'cantidad':amount},msg['correlation_id']))
    elif typ=='ReservaLiberacionSolicitada':
        r=db.query(Reservation).filter(Reservation.loan_id==lid).with_for_update().first()
        if not r:
            db.add(Reservation(loan_id=lid,product_id=p['producto_id'],quantity=0,status='TOMBSTONE'))
        elif r.status=='RESERVED':
            s=db.query(Item).filter(Item.product_id==r.product_id).with_for_update().one()
            s.reserved-=r.quantity;r.status='RELEASED'
            db.add(Movement(product_id=r.product_id,loan_id=lid,type='LIBERACION',units=r.quantity))
        emit(db,'inventario.liberado',event('InventarioLiberado',lid,{'motivo':'cancelacion'},msg['correlation_id']))
    elif typ=='ReservaConfirmacionSolicitada':
        r=db.query(Reservation).filter(Reservation.loan_id==lid).with_for_update().first()
        if r and r.status=='RESERVED' and r.expires>utcnow():
            s=db.query(Item).filter(Item.product_id==r.product_id).with_for_update().one()
            s.reserved-=r.quantity;s.quantity-=r.quantity;r.status='CONFIRMED'
            db.add(Movement(product_id=r.product_id,loan_id=lid,type='SALIDA',units=r.quantity))
            emit(db,'inventario.entregado',event('InventarioEntregado',lid,{'producto_id':r.product_id,'cantidad':r.quantity},msg['correlation_id']))
        else:
            emit(db,'inventario.expirado',event('InventarioExpirado',lid,{'motivo':'reserva_no_disponible'},msg['correlation_id']))
    else:raise ValueError('Tipo de mensaje no soportado: '+typ)

def expiry_loop():
    while True:
        try:
            with SessionLocal() as db:
                # FOR UPDATE SKIP LOCKED: múltiples workers sin doble liberación.
                rows=db.query(Reservation).filter(Reservation.status=='RESERVED',Reservation.expires<utcnow()).with_for_update(skip_locked=True).limit(100).all()
                for r in rows:
                    s=db.query(Item).filter(Item.product_id==r.product_id).with_for_update().one()
                    s.reserved-=r.quantity;r.status='EXPIRED'
                    db.add(Movement(product_id=r.product_id,loan_id=r.loan_id,type='VENCIMIENTO',units=r.quantity))
                    emit(db,'inventario.expirado',event('InventarioExpirado',r.loan_id,{'producto_id':r.product_id}))
                db.commit()
        except Exception as ex:logging.exception('Expiry: %s',ex)
        time.sleep(10)

def main():
    Base.metadata.create_all(engine)
    threading.Thread(target=outbox_loop,args=(SessionLocal,),daemon=True).start()
    threading.Thread(target=expiry_loop,daemon=True).start()
    consume_loop('inventory',SessionLocal,handle)
if __name__=='__main__':main()
