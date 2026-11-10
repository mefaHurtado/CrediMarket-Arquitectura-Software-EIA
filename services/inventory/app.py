import os
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import FastAPI,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import Column,String,Integer,DateTime,CheckConstraint
from sqlalchemy.orm import Session
import httpx
from shared.core import Base,database,session_factory,uid,utcnow,admin,event,emit
engine=database(); SessionLocal=session_factory(engine)
class Item(Base):
    __tablename__='stock'
    product_id=Column(String(36),primary_key=True)
    quantity=Column(Integer,nullable=False,default=0)
    reserved=Column(Integer,nullable=False,default=0)
    __table_args__=(CheckConstraint('quantity>=0'),CheckConstraint('reserved>=0'),CheckConstraint('reserved<=quantity'))
class Reservation(Base):
    __tablename__='reservations'
    loan_id=Column(String(36),primary_key=True)
    product_id=Column(String(36),nullable=False)
    quantity=Column(Integer,nullable=False)
    status=Column(String(30),nullable=False)
    expires=Column(DateTime,nullable=True)
class Movement(Base):
    __tablename__='movements'
    id=Column(String(36),primary_key=True,default=uid)
    product_id=Column(String(36),nullable=False)
    loan_id=Column(String(36),nullable=True)
    type=Column(String(40),nullable=False)
    units=Column(Integer,nullable=False)
    created=Column(DateTime,default=utcnow)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        try:
            with httpx.Client(timeout=4) as client:
                resp=client.get(os.environ['PRODUCTS_URL']+'/productos');resp.raise_for_status()
                # Precarga SOLO en la creación inicial; no inventa stock al reiniciar.
                if db.query(Item).count()==0:
                    for idx,p in enumerate(resp.json()):
                        amount=5 if idx else 2
                        db.add(Item(product_id=p['id'],quantity=amount,reserved=0))
                    db.commit()
        except Exception as ex:print('No se pudo precargar inventario:',ex,flush=True)
    yield
app=FastAPI(title='CrediMarket · Inventario',lifespan=lifespan,root_path='/api/inventario')
def session():
    with SessionLocal() as db:yield db
class StockChange(BaseModel):
    product_id:str
    units:int=Field(gt=0,lt=100000)
def item_doc(s):return {'product_id':s.product_id,'quantity':s.quantity,'reserved':s.reserved,'available':s.quantity-s.reserved}
@app.get('/health')
def health():return {'status':'ok','service':'inventory'}
@app.get('/inventario')
def get_stock(_=Depends(admin),db:Session=Depends(session)):
    return [item_doc(i) for i in db.query(Item).order_by(Item.product_id).all()]
@app.post('/inventario/entradas')
def entry(b:StockChange,_=Depends(admin),db:Session=Depends(session)):
    # El producto se valida por API: no se consultan tablas ajenas.
    try:
        with httpx.Client(timeout=3) as client:
            r=client.get(os.environ['PRODUCTS_URL']+'/internal/productos/'+b.product_id+'/cotizacion',headers={'X-Internal-Token':os.environ['INTERNAL_TOKEN']});r.raise_for_status()
    except Exception:raise HTTPException(422,'El producto no está disponible en el catálogo')
    s=db.query(Item).filter(Item.product_id==b.product_id).with_for_update().first()
    if not s:s=Item(product_id=b.product_id,quantity=0,reserved=0);db.add(s)
    s.quantity+=b.units;db.add(Movement(product_id=b.product_id,type='ENTRADA',units=b.units));db.commit()
    return item_doc(s)
@app.get('/inventario/reservas')
def reservations(_=Depends(admin),db:Session=Depends(session)):
    return [{'prestamo_id':x.loan_id,'producto_id':x.product_id,'cantidad':x.quantity,'estado':x.status,'vence':str(x.expires) if x.expires else None} for x in db.query(Reservation).order_by(Reservation.expires.desc()).limit(300)]
@app.get('/inventario/movimientos')
def movements(_=Depends(admin),db:Session=Depends(session)):
    return [{'id':x.id,'producto_id':x.product_id,'prestamo_id':x.loan_id,'tipo':x.type,'unidades':x.units,'fecha':str(x.created)} for x in db.query(Movement).order_by(Movement.created.desc()).limit(300)]
