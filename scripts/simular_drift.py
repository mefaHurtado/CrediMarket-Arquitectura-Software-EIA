"""Demuestra una alerta descriptiva de drift en 20 llamadas SIN datos reales."""
import json,urllib.request
from pathlib import Path
p=Path(__file__).resolve().parents[1]
vars=dict(line.split('=',1) for line in (p/'.env').read_text().splitlines() if '=' in line)
base='http://localhost:8080/api/'
def call(path,data=None,tok=None):
 h={}
 if tok:h['Authorization']='Bearer '+tok
 if data is not None:h['Content-Type']='application/json'
 with urllib.request.urlopen(urllib.request.Request(base+path,headers=h,
    data=json.dumps(data).encode() if data is not None else None),timeout=8) as r:return json.load(r)
token=call('clientes/auth/login',{'username':'admin','password':vars['DEMO_ADMIN_PASSWORD']})['access_token']
features={'ingresos_mensuales_cop':1100000,'obligaciones_mensuales_cop':950000,
 'tipo_empleo':'informal','antiguedad_laboral_meses':1,'meses_historial_crediticio':2,
 'creditos_previos':0,'atrasos_previos_30d':9,'porcentaje_pago_puntual':20,
 'monto_solicitado_cop':4000000,'plazo_meses':12,'cuota_estimada_cop':372800}
print('ANTES:',call('prestamos/modelo/monitor',tok=token))
for i in range(20):
 r=call('prestamos/riesgo/predict',features,token)
print('DESPUÉS:',call('prestamos/modelo/monitor',tok=token))
print('La alerta es ilustrativa y no demuestra performance real del modelo ante población humana.')
