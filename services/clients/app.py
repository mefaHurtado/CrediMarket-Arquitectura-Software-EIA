import os,csv,io,math
from contextlib import asynccontextmanager
from fastapi import FastAPI,Depends,HTTPException,UploadFile,File
from pydantic import BaseModel,Field
from sqlalchemy import Column,String,Integer,Float,Boolean,UniqueConstraint
from sqlalchemy.orm import Session
from shared.core import Base,database,session_factory,uid,identity,admin,internal,make_hash,check_hash,token
engine=database();SessionLocal=session_factory(engine)
class Customer(Base):
    __tablename__='customers'
    id=Column(String(36),primary_key=True)
    external_id=Column(String(80),unique=True,nullable=True)
    name=Column(String(100),nullable=False)
    income=Column(Integer,nullable=False)
    obligations=Column(Integer,nullable=False)
    employment=Column(String(40),nullable=True)
    tenure=Column(Float,nullable=True)
    history=Column(Float,nullable=True)
    previous=Column(Integer,nullable=False,default=0)
    arrears=Column(Integer,nullable=False,default=0)
    punctual=Column(Float,nullable=True)
    active=Column(Boolean,default=True,nullable=False)
class User(Base):
    __tablename__='users'
    id=Column(String(36),primary_key=True)
    username=Column(String(100),nullable=False,unique=True)
    password_hash=Column(String(200),nullable=False)
    role=Column(String(20),nullable=False)
    customer_id=Column(String(36),nullable=True)

def doc(c):return {'id':c.id,'external_id':c.external_id,'name':c.name,'income':c.income,'obligations':c.obligations,'employment':c.employment,'tenure':c.tenure,'history':c.history,'previous':c.previous,'arrears':c.arrears,'punctual':c.punctual,'active':c.active}
def seed(db):
    if db.query(User).count():return
    for login,password,role,name,values in [
        ('admin',os.environ['DEMO_ADMIN_PASSWORD'],'admin','Administrador CrediMarket',[5000000,100000,'dependiente',50,120,2,0,98]),
        ('cliente_demo',os.environ['DEMO_CLIENT_PASSWORD'],'cliente','Cliente Demostración',[9500000,200000,'dependiente',90,180,4,0,99]),
        ('cliente_riesgo',os.environ['DEMO_RISK_PASSWORD'],'cliente','Cliente Alto Riesgo',[1250000,1100000,'informal',1,3,0,9,30]),
        ('cliente_dos',os.environ['DEMO_SECOND_PASSWORD'],'cliente','Cliente Dos',[9000000,250000,'dependiente',60,130,2,0,99]),
    ]:
        c=Customer(id=uid(),name=name,income=values[0],obligations=values[1],employment=values[2],tenure=values[3],history=values[4],previous=values[5],arrears=values[6],punctual=values[7])
        db.add(c)
        db.add(User(id=uid(),username=login,password_hash=make_hash(password),role=role,customer_id=c.id))
    db.commit()
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:seed(db)
    yield
app=FastAPI(title='CrediMarket · Clientes',lifespan=lifespan,root_path='/api/clientes')
def session():
    with SessionLocal() as db:yield db
class Login(BaseModel):username:str;password:str
class CustomerIn(BaseModel):
    name:str=Field(min_length=2,max_length=100)
    income:int=Field(gt=0,le=100000000)
    obligations:int=Field(ge=0,le=100000000)
    employment:str|None=None
    tenure:float|None=Field(default=None,ge=0,le=600)
    history:float|None=Field(default=None,ge=0,le=600)
    previous:int=Field(default=0,ge=0)
    arrears:int=Field(default=0,ge=0)
    punctual:float|None=Field(default=None,ge=0,le=100)
@app.get('/health')
def health():return {'status':'ok','service':'clients'}
@app.post('/auth/login')
def login(body:Login,db:Session=Depends(session)):
    u=db.query(User).filter_by(username=body.username).first()
    if not u or not check_hash(body.password,u.password_hash):raise HTTPException(401,'Usuario o contraseña incorrectos')
    return {'access_token':token(u.id,u.role,u.customer_id),'role':u.role,'client_id':u.customer_id,'username':u.username}
@app.get('/auth/me')
def me(user=Depends(identity)):return user
@app.get('/clientes')
def list_customers(_=Depends(admin),db:Session=Depends(session)):
    return [doc(c) for c in db.query(Customer).order_by(Customer.name).limit(500).all()]
@app.get('/clientes/{cid}')
def get_customer(cid:str,me=Depends(identity),db:Session=Depends(session)):
    if me['role']!='admin' and me['client_id']!=cid:raise HTTPException(403,'No puedes consultar este cliente')
    c=db.get(Customer,cid)
    if not c:raise HTTPException(404,'Cliente no encontrado')
    return doc(c)
@app.get('/internal/clientes/{cid}',dependencies=[Depends(internal)])
def internal_customer(cid:str,db:Session=Depends(session)):
    c=db.get(Customer,cid)
    if not c:raise HTTPException(404,'Cliente no encontrado')
    return doc(c)
@app.post('/clientes',status_code=201)
def create(body:CustomerIn,_=Depends(admin),db:Session=Depends(session)):
    c=Customer(id=uid(),**body.model_dump());db.add(c);db.commit();return doc(c)
@app.put('/clientes/{cid}')
def update(cid:str,body:CustomerIn,me=Depends(identity),db:Session=Depends(session)):
    if me['role']!='admin' and me['client_id']!=cid:raise HTTPException(403,'Sin permiso')
    c=db.get(Customer,cid)
    if not c:raise HTTPException(404,'Cliente no encontrado')
    for k,v in body.model_dump().items():setattr(c,k,v)
    db.commit();return doc(c)

def numeric(v,optional=False):
    if v is None or str(v).strip()=='' or str(v).lower()=='nan':return None if optional else 0
    return float(v)
@app.post('/clientes/importar')
async def import_csv(file:UploadFile=File(...),_=Depends(admin),db:Session=Depends(session)):
    if not file.filename.lower().endswith('.csv'):raise HTTPException(422,'Sube un archivo CSV')
    raw=(await file.read()).decode('utf-8-sig');reader=csv.DictReader(io.StringIO(raw))
    counts={'insertados':0,'actualizados':0,'errores':[]}
    for n,row in enumerate(reader,start=2):
        try:
            ext=(row.get('cliente_id') or row.get('external_id') or '').strip()
            if not ext:raise ValueError('Falta cliente_id')
            c=db.query(Customer).filter(Customer.external_id==ext).first()
            if not c:c=Customer(id=uid(),external_id=ext);db.add(c);counts['insertados']+=1
            else:counts['actualizados']+=1
            c.name=(row.get('name') or 'Cliente '+ext)[:100]
            c.income=int(numeric(row.get('ingresos_mensuales_cop') or row.get('income')))
            c.obligations=int(numeric(row.get('obligaciones_mensuales_cop') or row.get('obligations')))
            c.employment=row.get('tipo_empleo') or row.get('employment') or None
            c.tenure=numeric(row.get('antiguedad_laboral_meses') or row.get('tenure'),True)
            c.history=numeric(row.get('meses_historial_crediticio') or row.get('history'),True)
            c.previous=int(numeric(row.get('creditos_previos') or row.get('previous')))
            c.arrears=int(numeric(row.get('atrasos_previos_30d') or row.get('arrears')))
            c.punctual=numeric(row.get('porcentaje_pago_puntual') or row.get('punctual'),True)
            if c.income<=0 or c.obligations<0:raise ValueError('Valores financieros inválidos')
            db.flush()
        except Exception as ex:
            db.rollback()
            counts['errores'].append({'fila':n,'detalle':str(ex)[:160]})
            # Después del rollback se reconstituye el estado desde filas ya confirmadas.
            continue
        db.commit()
    return counts
