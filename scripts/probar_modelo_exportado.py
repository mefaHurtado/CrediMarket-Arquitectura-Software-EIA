"""Corre dentro del contenedor loans: valida equivalencia pipeline vs API predict, sin entrenar."""
import json,joblib,pandas as pd
from pathlib import Path
root=Path('/models');active=json.loads((root/'active.json').read_text())['version']
m=joblib.load(root/(active+'.joblib'));example=json.loads((root/('sample.'+active+'.json')).read_text());p=float(m.predict_proba(pd.DataFrame([example['input']]))[0,1]);
assert abs(p-example['probability'])<1e-10,(p,example['probability'])
print('Pipeline exportado reproducible. Versión:',active,'Probabilidad:',p)
