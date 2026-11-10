"""Pruebas de lógica locales sin Docker. Sustituyen SOLO transporte externo RabbitMQ/Redis.
NO sustituyen los tests de integración Docker. Se ejecutan sobre SQLite temporal.
"""
import os,sys,types,tempfile,json,hashlib
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
tmp=Path(tempfile.mkdtemp(prefix='credimarket_smoke_'))
os.environ.update({'JWT_SECRET':'smoke_test_only_very_long_secret_for_tests_12345','INTERNAL_TOKEN':'smoke_internal',
'DEMO_ADMIN_PASSWORD':'abc12345','DEMO_CLIENT_PASSWORD':'abc12345','DEMO_RISK_PASSWORD':'abc12345','DEMO_SECOND_PASSWORD':'abc12345',
'CLIENTS_URL':'http://clients','PRODUCTS_URL':'http://products','REDIS_URL':'redis://unused',
'MODEL_DIR':str(ROOT/'model_artifacts')})
# Redis y broker se testean en Docker. Stub local solo para verificar lógica de negocio.
store={}
class FakeRedis:
 def get(self,k):return store.get(k)
 def setex(self,k,ttl,v):store[k]=v
 def delete(self,k):return store.pop(k,None)
class FakeRedisModule:
 Redis=types.SimpleNamespace(from_url=lambda *a,**kw:FakeRedis())
sys.modules['redis']=FakeRedisModule()
sys.modules['pika']=types.ModuleType('pika')
os.environ['DATABASE_URL']='sqlite:///'+str(tmp/'products.db')
from services.products import app as p
os.environ['DATABASE_URL']='sqlite:///'+str(tmp/'clients.db')
from services.clients import app as c
os.environ['DATABASE_URL']='sqlite:///'+str(tmp/'loans.db')
from services.loans import app as l
os.environ['DATABASE_URL']='sqlite:///'+str(tmp/'inventory.db')
from services.inventory import app as i
from services.inventory import worker as iw
from services.loans import worker as lw
from shared.core import Outbox

def login(client,user):
 r=client.post('/auth/login',json={'username':user,'password':'abc12345'});assert r.status_code==200,r.text;return r.json()
def token_headers(data):return {'Authorization':'Bearer '+data['access_token']}
def expect(r,code):assert r.status_code==code,(r.status_code,r.text);return r.json()

def move_loans_outbox():
 with l.SessionLocal() as ld:
  records=ld.query(Outbox).filter_by(sent=False).all()
  for rec in records:
   if not rec.route.startswith('reserva.'):continue
   with i.SessionLocal() as inv:
    iw.handle(inv,json.loads(rec.body));inv.commit()
   rec.sent=True;ld.commit()
def move_inventory_outbox():
 with i.SessionLocal() as inv:
  records=inv.query(Outbox).filter_by(sent=False).all()
  for rec in records:
   if not rec.route.startswith('inventario.'):continue
   with l.SessionLocal() as ld:
    lw.handle(ld,json.loads(rec.body));ld.commit()
   rec.sent=True;inv.commit()

with TestClient(p.app) as P,TestClient(c.app) as C,TestClient(l.app) as L,TestClient(i.app) as I:
 admin=login(C,'admin');good=login(C,'cliente_demo');risk=login(C,'cliente_riesgo');other=login(C,'cliente_dos')
 adminH=token_headers(admin);goodH=token_headers(good);riskH=token_headers(risk);otherH=token_headers(other)
 products=expect(P.get('/productos'),200);pid=products[0]['id']
 # Replace internal inter-service HTTP with test client calls, NOT production behavior.
 def external(url):
  if '/internal/clientes/' in url:
   cid=url.split('/')[-1]
   resp=C.get('/clientes/'+cid,headers=adminH)
  else:
   cid=url.split('/')[-2]
   resp=P.get('/internal/productos/'+cid+'/cotizacion',headers={'X-Internal-Token':'smoke_internal'})
  if resp.status_code!=200:raise RuntimeError(resp.text)
  return resp.json()
 l.external=external
 # Inventario initial load fails in local mode. Enter stock by direct DB.
 with i.SessionLocal() as db:
  db.add(i.Item(product_id=pid,quantity=3,reserved=0));db.commit()
 r=P.get('/productos/'+pid);expect(r,200)
 expect(P.get('/productos/'+pid),200)
 assert p.metrics['hit']>=1
 body={'producto_id':pid,'cantidad':1,'plazo_meses':12}
 H={**goodH,'Idempotency-Key':'test-12345678'}
 first=expect(L.post('/prestamos',json=body,headers=H),202)
 assert first['estado']=='PENDIENTE_INVENTARIO',first
 second=expect(L.post('/prestamos',json=body,headers=H),202)
 assert first['id']==second['id']
 expect(L.post('/prestamos',json={**body,'cantidad':2},headers=H),409)
 expect(L.get('/prestamos/'+first['id'],headers=otherH),403)
 move_loans_outbox();move_inventory_outbox()
 approved=expect(L.get('/prestamos/'+first['id'],headers=goodH),200)
 assert approved['estado']=='APROBADA',approved
 c2=expect(L.post('/prestamos/'+first['id']+'/cancelar',headers=goodH),202)
 move_loans_outbox();move_inventory_outbox()
 final=expect(L.get('/prestamos/'+first['id'],headers=goodH),200)
 assert final['estado']=='CANCELADA',final
 rejected=expect(L.post('/prestamos',json=body,headers={**riskH,'Idempotency-Key':'risk-12345678'}),202)
 assert rejected['estado']=='RECHAZADA',rejected
 second_loan=expect(L.post('/prestamos',json=body,headers={**goodH,'Idempotency-Key':'test-87654321'}),202)
 move_loans_outbox();move_inventory_outbox()
 assert expect(L.get('/prestamos/'+second_loan['id'],headers=goodH),200)['estado']=='APROBADA'
 expect(L.post('/prestamos/'+second_loan['id']+'/entregar',headers=adminH),202)
 move_loans_outbox();move_inventory_outbox()
 assert expect(L.get('/prestamos/'+second_loan['id'],headers=goodH),200)['estado']=='COMPLETADA'
 before=expect(P.get('/productos/'+pid),200)
 updated=expect(P.put('/productos/'+pid,json={'name':'Actualizado','category':'Pruebas','price':400000},headers=adminH),200)
 assert updated['version']==before['version']+1
 assert expect(P.get('/productos/'+pid),200)['price']==400000
 info=expect(L.get('/modelo/info',headers=adminH),200)
 expect(L.post('/modelo/activar',json={'version':'v2'},headers=adminH),200)
 expect(L.post('/modelo/activar',json={'version':'v1'},headers=adminH),200)
 csv_bytes=(ROOT/'data'/'solicitudes_nuevas.csv').read_bytes()
 a=expect(C.post('/clientes/importar',headers=adminH,files={'file':('solicitudes_nuevas.csv',csv_bytes,'text/csv')}),200)
 b=expect(C.post('/clientes/importar',headers=adminH,files={'file':('solicitudes_nuevas.csv',csv_bytes,'text/csv')}),200)
 assert a['insertados']==200 and b['insertados']==0 and b['actualizados']==200,(a,b)
 print('LOCAL SMOKE: 13 validaciones lógicas OK. SQLite/stubs: NO prueba broker/Redis/Postgres reales.')
