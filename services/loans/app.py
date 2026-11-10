"""Préstamos + inferencia ML. No consulta tablas de otros servicios."""
import os,json,hashlib,threading,math
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import FastAPI,Depends,HTTPException,Header,Response
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import Column,String,Integer,Float,DateTime,Text,UniqueConstraint,func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import httpx,joblib,pandas as pd
from shared.core import Base,database,session_factory,uid,utcnow,event,emit,digest,identity,admin,internal
engine=database(); SessionLocal=session_factory(engine)
MODELS=os.environ.get('MODEL_DIR','/models')
_active={}
_guard=threading.RLock()
class Loan(Base):
    __tablename__='loans'
    id=Column(String(36),primary_key=True)
    actor_id=Column(String(36),nullable=False)
    client_id=Column(String(36),nullable=False,index=True)
    product_id=Column(String(36),nullable=False)
    quantity=Column(Integer,nullable=False)
    term=Column(Integer,nullable=False)
    unit_price=Column(Integer,nullable=False)
    price_version=Column(Integer,nullable=False)
    amount=Column(Integer,nullable=False)
    risk=Column(Float,nullable=False)
    threshold=Column(Float,nullable=False)
    model_version=Column(String(40),nullable=False)
    status=Column(String(40),nullable=False)
    reason=Column(String(200),nullable=True)
    idem_key=Column(String(120),nullable=False)
    request_hash=Column(String(64),nullable=False)
    created=Column(DateTime,default=utcnow)
    updated=Column(DateTime,default=utcnow,onupdate=utcnow)
    __table_args__=(UniqueConstraint('actor_id','idem_key',name='ux_idempotency'),)
class Prediction(Base):
    __tablename__='predictions'
    id=Column(String(36),primary_key=True,default=uid)
    version=Column(String(40))
    probability=Column(Float)
    time=Column(DateTime,default=utcnow)

def read_model(ver=None):
    if ver is None:
        with open(MODELS+'/active.json',encoding='utf-8') as f:ver=json.load(f)['version']
    path=MODELS+'/'+ver+'.joblib';mp=MODELS+'/manifest.'+ver+'.json'
    with open(mp,encoding='utf-8') as f:manifest=json.load(f)
    with open(path,'rb') as f:raw=f.read()
    if hashlib.sha256(raw).hexdigest()!=manifest['artifact_sha256']:
        raise RuntimeError('El hash del modelo no coincide con su manifiesto')
    model=joblib.load(path) # Solo artefactos locales, generados por este proyecto; jamás archivos de usuarios.
    return {'model':model,'manifest':manifest}

def activate(ver=None):
    loaded=read_model(ver)
    with _guard:
        _active.clear();_active.update(loaded)

def selected():
    with _guard:
        if not _active:raise HTTPException(503,'Modelo aún no cargado')
        return dict(_active)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    activate()
    yield
app=FastAPI(title='CrediMarket · Préstamos / riesgo',lifespan=lifespan,root_path='/api/prestamos')
def session():
    with SessionLocal() as db:yield db

class LoanIn(BaseModel):
    cliente_id:str|None=None
    producto_id:str
    cantidad:int=Field(gt=0,le=10)
    plazo_meses:int=Field(ge=6,le=60)
class Features(BaseModel):
    ingresos_mensuales_cop:int=Field(gt=0,le=150000000)
    obligaciones_mensuales_cop:int=Field(ge=0,le=150000000)
    tipo_empleo:str|None=None
    antiguedad_laboral_meses:float|None=Field(default=None,ge=0,le=800)
    meses_historial_crediticio:float|None=Field(default=None,ge=0,le=800)
    creditos_previos:int=Field(ge=0,le=100)
    atrasos_previos_30d:int=Field(ge=0,le=100)
    porcentaje_pago_puntual:float|None=Field(default=None,ge=0,le=100)
    monto_solicitado_cop:int=Field(gt=0,le=200000000)
    plazo_meses:int=Field(ge=6,le=60)
    cuota_estimada_cop:float=Field(gt=0,le=50000000)

class VersionIn(BaseModel):version:str=Field(pattern=r'^v[12]$')
def payment(amount,months):
    r=.018;f=(1+r)**months
    return round(amount*r*f/(f-1),2)
def features(client,amount,term):
    return Features(ingresos_mensuales_cop=client['income'],obligaciones_mensuales_cop=client['obligations'],
         tipo_empleo=client.get('employment'),antiguedad_laboral_meses=client.get('tenure'),
         meses_historial_crediticio=client.get('history'),creditos_previos=client['previous'],
         atrasos_previos_30d=client['arrears'],porcentaje_pago_puntual=client.get('punctual'),
         monto_solicitado_cop=amount,plazo_meses=term,cuota_estimada_cop=payment(amount,term))
def predict(f:Features):
    a=selected();man=a['manifest']
    df=pd.DataFrame([f.model_dump()]);prob=float(a['model'].predict_proba(df)[0,1])
    return {'probabilidad_incumplimiento':round(prob,6),'decision_riesgo':'FAVORABLE' if prob<man['threshold'] else 'DESFAVORABLE',
            'umbral':man['threshold'],'model_version':man['model_version']}
def doc(l):
    return {'id':l.id,'cliente_id':l.client_id,'producto_id':l.product_id,'cantidad':l.quantity,'plazo_meses':l.term,
            'precio_unitario':l.unit_price,'version_precio':l.price_version,'monto':l.amount,
            'probabilidad_incumplimiento':l.risk,'umbral':l.threshold,'modelo':l.model_version,
            'estado':l.status,'motivo':l.reason,'fecha':str(l.created)}
def authorized(l,me):
    if me['role']!='admin' and me['client_id']!=l.client_id:raise HTTPException(403,'No puedes consultar esta solicitud')
def external(url):
    try:
        with httpx.Client(timeout=httpx.Timeout(3.0,connect=1.5)) as client:
            r=client.get(url,headers={'X-Internal-Token':os.environ['INTERNAL_TOKEN']})
            if r.status_code==404:raise HTTPException(422,'Cliente o producto inexistente')
            r.raise_for_status();return r.json()
    except HTTPException:raise
    except Exception:raise HTTPException(503,'Un servicio de consulta no está disponible; reintenta')

@app.get('/health')
def health():return {'status':'ok','service':'loans'}
@app.get('/ready')
def ready():
    try:
        a=selected()
        with SessionLocal() as db:db.execute(__import__('sqlalchemy').text('SELECT 1'))
        return {'status':'ready','model_version':a['manifest']['model_version']}
    except Exception:raise HTTPException(503,'Modelo o base de datos sin disponibilidad')
@app.get('/modelo/info')
def model_info(_=Depends(admin)):
    m=selected()['manifest']
    return {k:m[k] for k in ['model_version','run_id','data_sha256','features','positive_class','threshold','metrics']}
@app.post('/modelo/activar')
def promote(b:VersionIn,_=Depends(admin)):
    # Promoción explícita; otras instancias se deberían actualizar mediante un control de despliegue.
    try:loaded=read_model(b.version)
    except Exception as ex:raise HTTPException(422,'No se pudo cargar la versión: '+str(ex))
    path=MODELS+'/active.json';tmp=path+'.tmp'
    with open(tmp,'w') as f:json.dump({'version':b.version},f)
    os.replace(tmp,path)
    with _guard:_active.clear();_active.update(loaded)
    return {'activo':b.version,'run_id':loaded['manifest']['run_id']}
@app.post('/riesgo/predict')
def risk_endpoint(body:Features,_=Depends(admin),db:Session=Depends(session)):
    result=predict(body)
    db.add(Prediction(version=result['model_version'],probability=result['probabilidad_incumplimiento']));db.commit()
    return result
@app.get('/modelo/monitor')
def model_monitor(_=Depends(admin),db:Session=Depends(session)):
    v=selected()['manifest']
    q=db.query(func.count(Prediction.id),func.avg(Prediction.probability)).filter(Prediction.version==v['model_version']).one()
    current=float(q[1] or 0);baseline=float(v.get('validation_mean_probability',0))
    return {'version':v['model_version'],'predicciones':int(q[0]),'media_actual':round(current,5),
       'media_validacion':round(baseline,5),'alerta_desplazamiento':bool(q[0]>=10 and abs(current-baseline)>.15),
       'nota':'Indicador descriptivo sobre datos sintéticos, no una validación en población real'}

@app.post('/prestamos',status_code=202)
def submit(b:LoanIn,response:Response,idempotency_key:str=Header(...,alias='Idempotency-Key',min_length=8,max_length=120),
           me=Depends(identity),db:Session=Depends(session)):
    cid=me.get('client_id') if me['role']!='admin' else (b.cliente_id or me.get('client_id'))
    if not cid or (me['role']!='admin' and b.cliente_id and b.cliente_id!=cid):raise HTTPException(403,'Solo puedes solicitar a tu nombre')
    normalized={'cliente_id':cid,'producto_id':b.producto_id,'cantidad':b.cantidad,'plazo_meses':b.plazo_meses}
    h=digest(normalized)
    old=db.query(Loan).filter_by(actor_id=me['sub'],idem_key=idempotency_key).first()
    if old:
        if old.request_hash!=h:raise HTTPException(409,'Idempotency-Key utilizado con otro contenido')
        return doc(old)
    if b.plazo_meses not in (6,12,18,24,36,48,60):raise HTTPException(422,'Plazo no permitido')
    c=external(os.environ['CLIENTS_URL']+'/internal/clientes/'+cid)
    p=external(os.environ['PRODUCTS_URL']+'/internal/productos/'+b.producto_id+'/cotizacion')
    if not c['active']:raise HTTPException(422,'El cliente está inactivo')
    amount=int(p['price'])*b.cantidad
    f=features(c,amount,b.plazo_meses)
    pred=predict(f)
    favorable=pred['decision_riesgo']=='FAVORABLE'
    loan=Loan(id=uid(),actor_id=me['sub'],client_id=cid,product_id=b.producto_id,quantity=b.cantidad,term=b.plazo_meses,
             unit_price=p['price'],price_version=p['version'],amount=amount,risk=pred['probabilidad_incumplimiento'],
             threshold=pred['umbral'],model_version=pred['model_version'],status='PENDIENTE_INVENTARIO' if favorable else 'RECHAZADA',
             reason=None if favorable else 'Riesgo superior al umbral ficticio',idem_key=idempotency_key,request_hash=h)
    db.add(loan)
    db.add(Prediction(version=pred['model_version'],probability=pred['probabilidad_incumplimiento']))
    if favorable:emit(db,'reserva.solicitada',event('ReservaSolicitada',loan.id,{'producto_id':b.producto_id,'cantidad':b.cantidad}))
    try:db.commit()
    except IntegrityError:
        db.rollback()
        old=db.query(Loan).filter_by(actor_id=me['sub'],idem_key=idempotency_key).one()
        if old.request_hash!=h:raise HTTPException(409,'Idempotency-Key utilizado con otro contenido')
        return doc(old)
    return doc(loan)

@app.get('/prestamos')
def list_loans(me=Depends(identity),db:Session=Depends(session)):
    q=db.query(Loan)
    if me['role']!='admin':q=q.filter(Loan.client_id==me['client_id'])
    return [doc(l) for l in q.order_by(Loan.created.desc()).limit(300).all()]
@app.get('/prestamos/{lid}')
def get_loan(lid:str,me=Depends(identity),db:Session=Depends(session)):
    l=db.get(Loan,lid)
    if not l:raise HTTPException(404,'Préstamo no encontrado')
    authorized(l,me);return doc(l)
@app.post('/prestamos/{lid}/cancelar',status_code=202)
def cancel(lid:str,me=Depends(identity),db:Session=Depends(session)):
    l=db.query(Loan).filter(Loan.id==lid).with_for_update().first()
    if not l:raise HTTPException(404,'Préstamo no encontrado')
    authorized(l,me)
    if l.status=='CANCELACION_PENDIENTE':return doc(l)
    if l.status not in ('APROBADA','PENDIENTE_INVENTARIO'):raise HTTPException(409,'No se puede cancelar en este estado')
    l.status='CANCELACION_PENDIENTE'
    emit(db,'reserva.liberar',event('ReservaLiberacionSolicitada',l.id,{'producto_id':l.product_id}))
    db.commit();return doc(l)
@app.post('/prestamos/{lid}/entregar',status_code=202)
def deliver(lid:str,_=Depends(admin),db:Session=Depends(session)):
    l=db.query(Loan).filter(Loan.id==lid).with_for_update().first()
    if not l:raise HTTPException(404,'Préstamo no encontrado')
    if l.status!='APROBADA':raise HTTPException(409,'Solo se entrega un préstamo aprobado')
    l.status='ENTREGA_PENDIENTE'
    emit(db,'reserva.confirmar',event('ReservaConfirmacionSolicitada',l.id,{'producto_id':l.product_id}))
    db.commit();return doc(l)
