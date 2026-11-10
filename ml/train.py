"""Entrenamiento reproducible A-F: baseline + 7 candidatos, MLflow, 60/20/20, dos versiones."""
import os,sys,json,time,hashlib,argparse,platform
from pathlib import Path
import numpy as np,pandas as pd,joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score,recall_score,f1_score,roc_auc_score,average_precision_score,brier_score_loss,confusion_matrix,classification_report
from sklearn.base import clone
import sklearn
SEED=42
NUM=['ingresos_mensuales_cop','obligaciones_mensuales_cop','antiguedad_laboral_meses',
'meses_historial_crediticio','creditos_previos','atrasos_previos_30d','porcentaje_pago_puntual',
'monto_solicitado_cop','plazo_meses','cuota_estimada_cop']
CAT=['tipo_empleo'];FEATURES=NUM+CAT
TARGET='incumplimiento_90d'

def metrics(model,x,y,prefix):
    p=model.predict_proba(x)[:,1];pred=(p>=.5).astype(int)
    return {prefix+'_'+key:float(val) for key,val in dict(precision=precision_score(y,pred,zero_division=0),recall=recall_score(y,pred,zero_division=0),f1=f1_score(y,pred,zero_division=0),roc_auc=roc_auc_score(y,p),average_precision=average_precision_score(y,p),brier=brier_score_loss(y,p)).items()}

def choose_threshold(y,prob):
    """Costo puramente didáctico: aprobar moroso=5; rechazar cumplidor=1."""
    scored=[]
    for t in np.linspace(.05,.95,91):
        approve=(prob<t)
        loss=5*int(np.sum(approve & (y==1)))+int(np.sum(~approve & (y==0)))
        scored.append({'threshold':round(float(t),3),'cost':loss,'approved':int(approve.sum())})
    # Los empates favorecen umbral menor: menos aprobaciones de riesgo en el ejemplo ficticio.
    best=min(scored,key=lambda row:(row['cost'],row['threshold']))
    return best,scored

def write_json(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def main():
    pa=argparse.ArgumentParser();pa.add_argument('--offline',action='store_true')
    args=pa.parse_args()
    root=Path(__file__).resolve().parents[1];out=Path(os.getenv('MODEL_DIR',str(root/'model_artifacts')))
    out.mkdir(parents=True,exist_ok=True)
    source=root/'data'/'prestamos_entrenamiento.csv'
    digest=hashlib.sha256(source.read_bytes()).hexdigest();data=pd.read_csv(source)
    assert len(data)==12000 and TARGET in data.columns
    assert data['solicitud_id'].is_unique and data['cliente_id'].is_unique
    assert set(data[TARGET].unique())=={0,1}
    # Identificadores, tasa constante y etiqueta nunca serán predictores.
    X=data[FEATURES].copy();y=data[TARGET].astype(int)
    trainval,test=train_test_split(data.index,test_size=.20,stratify=y,random_state=SEED)
    train,val=train_test_split(trainval,test_size=.25,stratify=y.loc[trainval],random_state=SEED)
    parts={'train':train.tolist(),'validation':val.tolist(),'test':test.tolist()}
    for key,idx in parts.items():
        pd.DataFrame({'solicitud_id':data.loc[idx,'solicitud_id']}).to_csv(out/(key+'_ids.csv'),index=False)
    # Medidas y EDA sin compartir datos personales.
    eda={'dataset':'prestamos_entrenamiento_v1','sha256':digest,'rows':len(data),'columns':data.columns.tolist(),
         'label_distribution':{str(k):int(v) for k,v in y.value_counts().items()},
         'missing':data.isna().sum().to_dict(), 'duplicates':int(data.duplicated().sum()),
         'excluded_features':['solicitud_id','cliente_id','tasa_mensual_simulada',TARGET],
         'split_sizes':{k:len(v) for k,v in parts.items()}, 'seed':SEED}
    write_json(out/'eda.json',eda)
    preprocessing=ColumnTransformer([
        ('num',Pipeline([('imputer',SimpleImputer(strategy='median')),('scale',StandardScaler())]),NUM),
        ('cat',Pipeline([('imputer',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))]),CAT)
    ])
    models=[('baseline',DummyClassifier(strategy='prior')),
            ('logistic_C02',LogisticRegression(C=.2,max_iter=500,random_state=SEED)),
            ('logistic_C1',LogisticRegression(C=1,max_iter=500,random_state=SEED)),
            ('logistic_C4',LogisticRegression(C=4,max_iter=500,random_state=SEED)),
            ('tree_leaf20',DecisionTreeClassifier(min_samples_leaf=20,max_depth=7,random_state=SEED)),
            ('tree_leaf50',DecisionTreeClassifier(min_samples_leaf=50,max_depth=5,random_state=SEED)),
            ('forest_leaf3',RandomForestClassifier(n_estimators=70,min_samples_leaf=3,max_depth=12,n_jobs=2,random_state=SEED)),
            ('forest_leaf8',RandomForestClassifier(n_estimators=90,min_samples_leaf=8,max_depth=10,n_jobs=2,random_state=SEED))]
    run_mlflow=not args.offline
    if run_mlflow:
        import mlflow
        mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI','http://mlflow:5000'))
        mlflow.set_experiment('CrediMarket-riesgo-sintetico')
    records=[];fitted={}
    for name,est in models:
        started=time.time();pipe=Pipeline([('preprocess',clone(preprocessing)),('estimator',est)])
        pipe.fit(X.loc[train],y.loc[train]); ms=metrics(pipe,X.loc[val],y.loc[val],'val')
        run_id='offline-'+name
        if run_mlflow:
            with mlflow.start_run(run_name=name) as run:
                run_id=run.info.run_id
                mlflow.log_params({'algorithm':name,'seed':SEED,'split':'60/20/20_stratified','dataset_sha256':digest,
                    'dataset_version':'v1','code_version':'entrega_credimarket_v1','preprocess':'median+scale+onehot',
                    'features':','.join(FEATURES),'python':platform.python_version(),'sklearn':sklearn.__version__,
                    'estimator_params':str(est.get_params())[:400]})
                mlflow.log_metrics(ms);mlflow.log_metric('duration_seconds',time.time()-started)
                report={'name':name,'metrics':ms,'matrix_0_5':confusion_matrix(y.loc[val],pipe.predict(X.loc[val])).tolist()}
                temp=out/('report_'+name+'.json');write_json(temp,report)
                mlflow.log_artifact(str(temp),artifact_path='reports')
        records.append({'name':name,'run_id':run_id,**ms,'seconds':round(time.time()-started,2)})
        fitted[name]=pipe
        print(name,round(ms['val_average_precision'],4),flush=True)
    # Regla PREDEFINIDA: AP mayor, desempate Brier menor. Baseline no compite.
    ranked=sorted([x for x in records if x['name']!='baseline'],key=lambda z:(-z['val_average_precision'],z['val_brier']))
    validation_y=y.loc[val].to_numpy();test_y=y.loc[test].to_numpy()
    for version,chosen in zip(['v1','v2'],ranked[:2]):
        model=fitted[chosen['name']]
        p_val=model.predict_proba(X.loc[val])[:,1]
        best,cost_curve=choose_threshold(validation_y,p_val)
        # ÚNICA evaluación de prueba: solo la versión seleccionada v1.
        # v2 queda como candidato alternativo sin consultar el conjunto de prueba.
        if version=='v1':
            test_scores=metrics(model,X.loc[test],test_y,'test')
            p_test=model.predict_proba(X.loc[test])[:,1]
            test_cm=confusion_matrix(test_y,(p_test>=best['threshold']).astype(int)).tolist()
        else:
            test_scores={}
            test_cm=None
        path=out/(version+'.joblib');joblib.dump(model,path,compress=3)
        manifest={'model_version':version,'algorithm':chosen['name'],'run_id':chosen['run_id'],
             'dataset_version':'prestamos_entrenamiento_v1','data_sha256':digest,'features':FEATURES,
             'positive_class':1,'threshold':best['threshold'], 'threshold_cost':best['cost'],
             'fictional_costs':{'aprobar_incumplidor':5,'rechazar_cumplidor':1},
             'validation_mean_probability':float(p_val.mean()),
             'metrics':{**{k:v for k,v in chosen.items() if k.startswith('val_')},**test_scores,'test_confusion_matrix':test_cm},
             'dependencies':{'scikit_learn':sklearn.__version__,'joblib':joblib.__version__},
             'artifact_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        write_json(out/('manifest.'+version+'.json'),manifest)
        write_json(out/('cost_curve.'+version+'.json'),cost_curve)
        # Ejemplo de equivalencia predict() vs objeto exportado
        example=X.loc[[val[0]]];val1=float(model.predict_proba(example)[0,1]);val2=float(joblib.load(path).predict_proba(example)[0,1])
        assert abs(val1-val2)<1e-12
        write_json(out/('sample.'+version+'.json'),{'input':example.where(pd.notna(example),None).iloc[0].to_dict(),'probability':val1})
        if run_mlflow:
            with mlflow.start_run(run_id=chosen['run_id']):
                if test_scores: mlflow.log_metrics(test_scores)
                mlflow.log_metric('selected_threshold',best['threshold'])
                mlflow.log_artifact(str(path),artifact_path='exports')
                mlflow.log_artifact(str(out/('manifest.'+version+'.json')),artifact_path='exports')
    write_json(out/'comparison.json',{'dataset_sha256':digest,'selection_metric':'validation_average_precision','tie_break':'validation_brier_ascending',
      'results':records,'selected_for_v1':ranked[0]['name'],'alternate_v2':ranked[1]['name']})
    # Las 200 solicitudes nuevas SOLO reciben inferencia, jamás entrenamiento ni métricas.
    new=pd.read_csv(root/'data'/'solicitudes_nuevas.csv')
    if not set(FEATURES).issubset(set(new.columns)): raise ValueError('Variables faltantes en solicitudes_nuevas.csv')
    model_v1=fitted[ranked[0]['name']]
    scores=model_v1.predict_proba(new[FEATURES])[:,1]
    threshold=json.loads((out/'manifest.v1.json').read_text())['threshold']
    pd.DataFrame({'solicitud_id':new['solicitud_id'],'cliente_id':new['cliente_id'],
         'probabilidad_incumplimiento':np.round(scores,6),
         'decision_riesgo':['FAVORABLE' if a<threshold else 'DESFAVORABLE' for a in scores],
         'model_version':['v1']*len(new)}).to_csv(out/'solicitudes_nuevas_predicciones.csv',index=False)
    if not (out/'active.json').exists():write_json(out/'active.json',{'version':'v1'})
    print('Listo. Modelo activo:',json.loads((out/'active.json').read_text())['version'],flush=True)
if __name__=='__main__':main()
