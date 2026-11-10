"""p50/p95 y tasa de hits medidos con consultas HTTP reales."""
import os,time,statistics,json,urllib.request,urllib.error
from pathlib import Path
p=Path(__file__).resolve().parents[1]
vars=dict(line.split('=',1) for line in (p/'.env').read_text().splitlines() if '=' in line)
base='http://127.0.0.1:8081/api/'
def request(path,token=None,method='GET',data=None):
    headers={'Authorization':'Bearer '+token} if token else {}
    if data is not None:headers['Content-Type']='application/json'
    r=urllib.request.Request(base+path,method=method,headers=headers,data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(r,timeout=8) as v:return json.load(v)
admin=request('clientes/auth/login',method='POST',data={'username':'admin','password':vars['DEMO_ADMIN_PASSWORD']})['access_token']
products=request('productos/productos');pid=products[0]['id']
before=request('productos/metrics/cache',admin)
samples=[]
for _ in range(100):
    t=time.perf_counter();request('productos/productos/'+pid);samples.append((time.perf_counter()-t)*1000)
after=request('productos/metrics/cache',admin)
samples.sort()
result={'producto_id':pid,'consultas':100,'latencia_p50_ms':round(samples[49],2),'latencia_p95_ms':round(samples[94],2),
        'hit_incremento':after['hit']-before['hit'],'miss_incremento':after['miss']-before['miss'],
        'tasa_hits_en_muestra':round((after['hit']-before['hit'])/100,3),'fallback_incremento':after['fallback']-before['fallback'],
        'advertencia':'Medición de demo en máquina local, sin inferir rendimiento a escala de producción'}
print(json.dumps(result,indent=2,ensure_ascii=False))
(p/'docs'/'medicion_redis_local.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
