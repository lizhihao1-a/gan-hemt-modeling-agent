"""Target isolation, normalized parameter space and atomic artifacts."""
import csv,hashlib,json,os,time,datetime
from pathlib import Path
import numpy as np
from config import FIXED,BOUNDS,ACTIVE,ID_FLOOR,GM_FLOOR

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def atomic_json(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temp,p)
def event(path,kind,**fields):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps({'utc':now(),'event':kind,**fields},ensure_ascii=False,allow_nan=False)+'\n')
def load_data(path):
    rows=list(csv.DictReader(Path(path).open(encoding='utf-8-sig')))
    ix=np.array([int(r['grid_index']) for r in rows],dtype=int)
    y=np.array([[float(r['id_A']),float(r['gm_S'])] for r in rows])
    if len(set(ix))!=len(ix) or not np.isfinite(y).all():raise ValueError('Invalid/duplicate input targets')
    return rows,ix,y
def stencil(i):
    g=i//201
    return (i,i+201) if g==0 else ((i-201,i) if g==29 else (i-201,i+201))
def safe_gm(indices):
    known=set(map(int,indices))
    return np.array([all(j in known for j in stencil(int(i))) for i in indices])
def parameters(x):
    x=np.asarray(x,dtype=float)
    if x.shape!=(len(ACTIVE),) or not np.isfinite(x).all() or np.any(x<0) or np.any(x>1):
        raise ValueError('Parameters must be 23 finite normalized values inside [0,1]')
    p=FIXED.copy()
    for k,(lo,hi,lg) in BOUNDS.items():
        u=float(x[ACTIVE.index(k)]) if k in ACTIVE else .5
        p[k]=float(10**(np.log10(lo)+u*np.log10(hi/lo)) if lg else lo+u*(hi-lo))
    return p
def normalized(p):
    return np.clip(np.array([(np.log10(p[k]/BOUNDS[k][0])/np.log10(BOUNDS[k][1]/BOUNDS[k][0])) if BOUNDS[k][2] else
        (p[k]-BOUNDS[k][0])/(BOUNDS[k][1]-BOUNDS[k][0]) for k in ACTIVE]),0,1)
class Targets:
    def __init__(self,ix,y,scales=None):
        self.ix=np.array(ix);self.y=np.array(y);self.safe=safe_gm(ix)
        self.scales=np.array(scales) if scales is not None else np.array([
            max(float(np.ptp(y[:,0])),ID_FLOOR),
            max(float(np.ptp(y[self.safe,1])),GM_FLOOR) if self.safe.any() else GM_FLOOR])
    def residual(self,prediction):
        p=prediction[self.ix];floors=np.array([ID_FLOOR,GM_FLOOR])
        a=np.arcsinh(p/floors)-np.arcsinh(self.y/floors)
        b=2*(p-self.y)/self.scales
        a[~self.safe,1]=0;b[~self.safe,1]=0
        return np.concatenate([a.ravel(),b.ravel()])
    def cost(self,prediction):return robust_cost(self.residual(prediction))
def robust_cost(r):return float(np.mean(2*.3**2*(np.sqrt(1+(r/.3)**2)-1)))
def metric(y,p,train_scales):
    result={}
    for j,k in enumerate(['id_A','gm_S']):
        if not len(y):result[k]=None;continue
        e=p[:,j]-y[:,j];rmse=float(np.sqrt(np.mean(e*e)));span=float(np.ptp(y[:,j]))
        result[k]={'rmse':rmse,'mae':float(np.mean(abs(e))),
          'nrmse_train_range':rmse/float(train_scales[j]),'nrmse_own_range':rmse/span if span else None}
    return result
def model_card(params):
    return '.model nfet asmhemt (\n'+''.join(f'+ {k}={v:.14g}\n' for k,v in params.items())+'+ )\n'
def manifest(paths,base):return {str(Path(p).relative_to(base)).replace('\\','/'):sha(p) for p in paths}
def assert_manifest(items,base):
    for name,digest in items.items():
        p=Path(base)/name
        if not p.is_file() or sha(p)!=digest:raise RuntimeError('Artifact/input changed: '+name)

class RunLock:
    def __init__(self,path):self.path=Path(path)
    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True,exist_ok=True);self.f=self.path.open('a+b')
        if self.f.seek(0,2)==0:self.f.write(b'0');self.f.flush()
        self.f.seek(0)
        try:msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:self.f.close();raise RuntimeError('Another process owns this run')
        return self
    def __exit__(self,*args):
        import msvcrt
        self.f.seek(0);msvcrt.locking(self.f.fileno(),msvcrt.LK_UNLCK,1);self.f.close()
