"""Primitivas compartidas. Cada servicio solo accede a SU propia base de datos."""
import os, json, time, uuid, hashlib, hmac, secrets
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from fastapi import HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

Base = declarative_base()

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
def iso(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid.uuid4())
def canonical(data): return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',',':'), default=str)
def digest(data): return hashlib.sha256(canonical(data).encode()).hexdigest()

def database():
    url = os.environ['DATABASE_URL']
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, connect_args={'connect_timeout': 3} if url.startswith('postgres') else {})

def session_factory(engine): return sessionmaker(bind=engine, expire_on_commit=False)

class Outbox(Base):
    __tablename__='outbox'
    id=Column(String(36),primary_key=True,default=uid)
    route=Column(String(120),nullable=False)
    body=Column(Text,nullable=False)
    sent=Column(Boolean,default=False,nullable=False,index=True)
    created=Column(DateTime,default=utcnow)

class Inbox(Base):
    __tablename__='inbox'
    event_id=Column(String(36),primary_key=True)
    received=Column(DateTime,default=utcnow)

def event(kind,loan_id,payload,correlation=None):
    return {'event_id':uid(),'type':kind,'schema_version':'1.0','occurred_at':iso(),
            'correlation_id':correlation or loan_id,'prestamo_id':loan_id,'payload':payload}

def emit(db, route, data): db.add(Outbox(id=data['event_id'],route=route,body=canonical(data)))

security=HTTPBearer(auto_error=False)

def token(user,role,client_id=None):
    secret=os.environ['JWT_SECRET']
    data={'sub':str(user),'role':role,'client_id':client_id,'iat':datetime.now(timezone.utc),
          'exp':datetime.now(timezone.utc)+timedelta(hours=8)}
    return jwt.encode(data,secret,algorithm='HS256')

def identity(auth:HTTPAuthorizationCredentials=Depends(security)):
    if not auth: raise HTTPException(401,'Inicia sesión para continuar')
    try: return jwt.decode(auth.credentials,os.environ['JWT_SECRET'],algorithms=['HS256'])
    except jwt.ExpiredSignatureError: raise HTTPException(401,'La sesión venció; vuelve a ingresar')
    except jwt.InvalidTokenError: raise HTTPException(401,'Credenciales inválidas')

def admin(me=Depends(identity)):
    if me.get('role')!='admin': raise HTTPException(403,'Se requiere administrador')
    return me

def internal(x_internal_token: str | None = Header(None)):
    if not x_internal_token or not hmac.compare_digest(x_internal_token,os.environ['INTERNAL_TOKEN']):
        raise HTTPException(403,'Operación interna no autorizada')
    return True

def make_hash(password):
    salt=secrets.token_bytes(16)
    key=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,250000)
    return salt.hex()+':'+key.hex()
def check_hash(password,stored):
    try:
        salt,expected=stored.split(':')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),250000)
        return hmac.compare_digest(actual,bytes.fromhex(expected))
    except Exception:return False
