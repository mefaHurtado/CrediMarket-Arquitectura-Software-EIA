import os,json,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI,Depends,HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column,String,Integer,Float,Boolean
from sqlalchemy.orm import Session
import redis
from shared.core import Base,database,session_factory,uid,admin,internal
engine=database(); SessionLocal=session_factory(engine)
log=logging.getLogger(__name__)
class Product(Base):
    __tablename__='products'
    id=Column(String(36),primary_key=True)
    name=Column(String(180),nullable=False)
    category=Column(String(80),nullable=False)
    price=Column(Integer,nullable=False)
    version=Column(Integer,default=1,nullable=False)
    active=Column(Boolean,default=True,nullable=False)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.query(Product).first():
            for x in [('Laptop EIA Pro','Computadores',1800000),('Celular Nova 128GB','Celulares',950000),('Audífonos Atlas','Accesorios',180000)]:
                db.add(Product(id=uid(),name=x[0],category=x[1],price=x[2]))
            db.commit()
    yield

app=FastAPI(title='CrediMarket · Productos',lifespan=lifespan,root_path='/api/productos')
cache=None
metrics={'hit':0,'miss':0,'fallback':0,'invalidations':0}
def redis_cli(): return redis.Redis.from_url(os.environ['REDIS_URL'],socket_connect_timeout=.25,socket_timeout=.25,decode_responses=True)
def session():
    with SessionLocal() as db:yield db
class ProductIn(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    category:str=Field(min_length=2,max_length=80)
    price:int=Field(gt=0,le=100000000)
def doc(p):return {'id':p.id,'name':p.name,'category':p.category,'price':p.price,'version':p.version,'active':p.active}
def invalidate(pid):
    try: redis_cli().delete('productos:v1:'+pid);metrics['invalidations']+=1
    except Exception:metrics['fallback']+=1
@app.get('/health')
def health():return {'status':'ok','service':'products'}
@app.get('/metrics/cache')
def stats(_=Depends(admin)):return metrics
@app.get('/productos')
def list_products(include_inactive:bool=False,db:Session=Depends(session)):
    q=db.query(Product)
    if not include_inactive:q=q.filter(Product.active==True)
    return [doc(p) for p in q.order_by(Product.name).all()]
@app.get('/productos/{pid}')
def get_product(pid:str,db:Session=Depends(session)):
    key='productos:v1:'+pid
    try:
        cached=redis_cli().get(key)
        if cached:
            metrics['hit']+=1
            return json.loads(cached)
        metrics['miss']+=1
    except Exception:metrics['fallback']+=1
    p=db.get(Product,pid)
    if not p:raise HTTPException(404,'Producto no encontrado')
    result=doc(p)
    try:redis_cli().setex(key,30,json.dumps(result))
    except Exception:metrics['fallback']+=1
    return result
@app.get('/internal/productos/{pid}/cotizacion',dependencies=[Depends(internal)])
def quote(pid:str,db:Session=Depends(session)):
    # IMPORTANTE: cotización siempre desde PostgreSQL, jamás desde Redis.
    p=db.get(Product,pid)
    if not p or not p.active: raise HTTPException(404,'Producto inactivo o inexistente')
    return doc(p)
@app.post('/productos',status_code=201)
def create(product:ProductIn,_=Depends(admin),db:Session=Depends(session)):
    p=Product(id=uid(),**product.model_dump()); db.add(p);db.commit();return doc(p)
@app.put('/productos/{pid}')
def update(pid:str,product:ProductIn,_=Depends(admin),db:Session=Depends(session)):
    p=db.get(Product,pid)
    if not p:raise HTTPException(404,'Producto no encontrado')
    for k,v in product.model_dump().items():setattr(p,k,v)
    p.version+=1;db.commit();invalidate(pid);return doc(p)
@app.delete('/productos/{pid}')
def deactivate(pid:str,_=Depends(admin),db:Session=Depends(session)):
    p=db.get(Product,pid)
    if not p:raise HTTPException(404,'Producto no encontrado')
    p.active=False;p.version+=1;db.commit();invalidate(pid);return doc(p)
