"""Pruebas de aceptación SIN simulaciones. Ejecutar cuando Docker esté levantado."""
import json,time,uuid,urllib.request,urllib.error,concurrent.futures,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='http://localhost:8080/api/'
ENV=dict(line.split('=',1) for line in (ROOT/'.env').read_text().splitlines() if '=' in line and not line.startswith('#'))

def call(service,path,method='GET',body=None,token=None,key=None,raw=None):
    h={}
    if token:h['Authorization']='Bearer '+token
    if key:h['Idempotency-Key']=key
    if body is not None:
        raw=json.dumps(body).encode();h['Content-Type']='application/json'
    if raw is not None and not h.get('Content-Type'):h['Content-Type']='text/csv'
    req=urllib.request.Request(BASE+service+'/'+path.lstrip('/'),method=method,headers=h,data=raw)
    try:
        with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:
        try:d=json.load(e)
        except:d={'error':str(e)}
        return e.code,d

def login(name,pwd):
    status,d=call('clientes','auth/login','POST',{'username':name,'password':pwd})
    assert status==200,(status,d)
    return d

def wait(lid,t,expected=None):
    last=None
    for _ in range(60):
        status,last=call('prestamos','prestamos/'+lid,token=t)
        if status!=200:raise AssertionError(last)
        if expected and last['estado'] in expected:return last
        if not expected and last['estado'] not in ['PENDIENTE_INVENTARIO','CANCELACION_PENDIENTE','ENTREGA_PENDIENTE']:return last
        time.sleep(.5)
    raise AssertionError('Timeout estado: '+str(last))

def check(label,test):
    if not test:raise AssertionError('FALLO: '+label)
    print('OK:',label)

def main():
    admin=login('admin',ENV['DEMO_ADMIN_PASSWORD']);good=login('cliente_demo',ENV['DEMO_CLIENT_PASSWORD']);second=login('cliente_dos',ENV['DEMO_SECOND_PASSWORD']);bad=login('cliente_riesgo',ENV['DEMO_RISK_PASSWORD'])
    a=admin['access_token'];t1=good['access_token'];t2=second['access_token'];tb=bad['access_token']
    s,product=call('productos','productos','POST',{'name':'PRUEBA ULTIMA UNIDAD '+uuid.uuid4().hex[:6],'category':'Pruebas','price':150000},a)
    check('Producto persistido',s==201)
    pid=product['id']
    s,stock=call('inventario','inventario/entradas','POST',{'product_id':pid,'units':1},a)
    check('Stock 1 disponible',s==200 and stock['available']==1)
    payload={'producto_id':pid,'cantidad':1,'plazo_meses':12}
    def send(token,key):return call('prestamos','prestamos','POST',payload,token,key)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(send,t1,str(uuid.uuid4())),pool.submit(send,t2,str(uuid.uuid4()))]
        results=[x.result() for x in jobs]
    check('POST HTTP 202',all(s==202 for s,_ in results))
    l1=wait(results[0][1]['id'],t1);l2=wait(results[1][1]['id'],t2)
    check('Última unidad: una aprobada, otra sin stock',sorted([l1['estado'],l2['estado']])==['APROBADA','CANCELADA_SIN_STOCK'])
    winner=l1 if l1['estado']=='APROBADA' else l2
    winner_token=t1 if winner==l1 else t2
    wrong_token=t2 if winner_token==t1 else t1
    s,_=call('prestamos','prestamos/'+winner['id'],token=wrong_token)
    check('Rol cliente no accede a solicitud ajena: 403',s==403)
    s,_=call('prestamos','prestamos/'+winner['id']+'/cancelar','POST',{},winner_token)
    check('Cancelación iniciada',s==202)
    check('Liberación confirmada',wait(winner['id'],winner_token,['CANCELADA'])['estado']=='CANCELADA')
    key='idem-'+uuid.uuid4().hex
    s,x=send(t1,key);s2,y=send(t1,key)
    check('Misma key + mismo payload -> mismo préstamo',s==202 and s2==202 and x['id']==y['id'])
    s,z=call('prestamos','prestamos','POST',{**payload,'cantidad':2},t1,key)
    check('Misma key + distinto payload -> 409',s==409)
    s,risk=send(tb,'idem-'+uuid.uuid4().hex)
    check('Solicitante sintético de alto riesgo rechazado sin reserva',s==202 and risk['estado']=='RECHAZADA')
    s,old=call('productos','productos/'+pid)
    s,_=call('productos','productos/'+pid)
    s,stats=call('productos','metrics/cache',token=a)
    check('Redis consulta con HIT / MISS (si Redis está activo)',s==200 and stats['hit']>=1)
    upd={'name':product['name'],'category':product['category'],'price':200000}
    s,new=call('productos','productos/'+pid,'PUT',upd,a)
    s,fresh=call('productos','productos/'+pid)
    check('Precio y versión actualizados + invalidación',new['version']==old['version']+1 and fresh['price']==200000)
    s,model=call('prestamos','modelo/info',token=a)
    check('Modelo y run ID conocidos',s==200 and bool(model['run_id']))
    before=model['model_version'];target='v2' if before=='v1' else 'v1'
    s,other=call('prestamos','modelo/activar','POST',{'version':target},a)
    s,restored=call('prestamos','modelo/activar','POST',{'version':before},a)
    check('Promoción y rollback explícitos',restored['activo']==before)
    print('\nPruebas principales FINALIZADAS. Revisa docs/GUIA_DEMO.md para caída de broker, DLQ e importación de CSV.')
if __name__=='__main__':
    try:main()
    except Exception as ex:
        print('FALLO / BLOQUEADOR:',ex,file=sys.stderr);raise
