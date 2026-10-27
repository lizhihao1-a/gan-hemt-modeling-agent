"""A real ngspice subprocess with per-call timeout, bounded retry and audit logs."""
import multiprocessing as mp,os,time,uuid
from pathlib import Path
import numpy as np
from common import event,parameters

class NativeAttemptLimit(Exception):pass

def _worker(conn,root):
    try:
        from spice import Simulator
        sim=Simulator(root,parameters(np.full(23,.5)))
        conn.send({'ready':True,'startup':sim.messages})
        while True:
            request=conn.recv()
            if request['op']=='close':return
            if request.get('fault')=='crash':os._exit(76)
            if request.get('fault')=='timeout':time.sleep(request['sleep_seconds'])
            try:
                a,g,t=sim.simulate(request['parameters'])
                conn.send({'ok':True,'prediction':np.column_stack([a.ravel(),g.ravel()]),'temperature':t.ravel()})
            except Exception as e:conn.send({'ok':False,'error':str(e)})
    except EOFError:pass
    except Exception as e:
        try:conn.send({'ready':False,'error':str(e)})
        except Exception:pass
    finally:conn.close()

class LocalBackend:
    transport='local_process'
    def __init__(self,root,log,timeout=10,retries=1,attempt_limit=None):
        self.root=Path(root).resolve();self.log=Path(log).resolve()
        self.timeout=timeout;self.retries=retries;self.process=None;self.calls=0;self.failures=0
        self.attempt_limit=attempt_limit
    def start(self):
        ctx=mp.get_context('spawn');self.conn,child=ctx.Pipe()
        self.process=ctx.Process(target=_worker,args=(child,str(self.root)),daemon=True)
        self.process.start();child.close()
        if not self.conn.poll(20):self.close();raise TimeoutError('ngspice startup timeout')
        result=self.conn.recv()
        if not result.get('ready'):self.close();raise RuntimeError('ngspice startup failed: '+str(result))
        event(self.log,'backend_started',pid=self.process.pid,transport=self.transport,startup=result['startup'])
    def close(self):
        if self.process is not None:
            if self.process.is_alive():
                try:self.conn.send({'op':'close'})
                except Exception:pass
                self.process.join(.2)
            if self.process.is_alive():self.process.terminate();self.process.join(3)
            self.conn.close();self.process=None
    def simulate(self,x,*,fault_once=None):
        p=parameters(x) # validation before any native invocation
        operation=uuid.uuid4().hex
        for attempt in range(self.retries+1):
            if self.attempt_limit is not None and self.calls>=self.attempt_limit:
                event(self.log,'native_attempt_limit',operation=operation,limit=self.attempt_limit)
                raise NativeAttemptLimit('Real native attempt budget exhausted, including failed attempts and retries')
            if self.process is None or not self.process.is_alive():self.close();self.start()
            self.calls+=1;started=time.perf_counter()
            fault={'crash_once':'crash','timeout_once':'timeout'}.get(fault_once) if attempt==0 else None
            event(self.log,'tool_call',tool='simulate',operation=operation,attempt=attempt,transport=self.transport,
                  parameter_values=p,injected_fault=fault)
            try:
                self.conn.send({'op':'simulate','parameters':p,'fault':fault,'sleep_seconds':self.timeout+.5})
                if not self.conn.poll(self.timeout):raise TimeoutError('ngspice per-call deadline exceeded')
                result=self.conn.recv()
                if not result.get('ok'):raise RuntimeError(result.get('error',str(result)))
                pred=result['prediction'];temp=result['temperature']
                if pred.shape!=(6030,2) or temp.shape!=(6030,) or not np.isfinite(pred).all() or not np.isfinite(temp).all():
                    raise RuntimeError('Malformed/nonfinite simulation result')
                event(self.log,'tool_result',operation=operation,attempt=attempt,ok=True,elapsed_seconds=time.perf_counter()-started)
                return pred,temp
            except (EOFError,BrokenPipeError,OSError,TimeoutError,RuntimeError) as e:
                self.failures+=1
                event(self.log,'tool_result',operation=operation,attempt=attempt,ok=False,error=repr(e),elapsed_seconds=time.perf_counter()-started)
                self.close()
                if attempt==self.retries:raise RuntimeError('Simulation failed after bounded retry') from e
                event(self.log,'backend_retry',operation=operation,next_attempt=attempt+1)
        raise AssertionError('Unreachable')
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class NotConfigured(RuntimeError):pass
class OfficialMCPBackend:
    """Deliberately unavailable until an actual official schema is supplied."""
    def __init__(self,*args,**kwargs):
        raise NotConfigured('Official MCP endpoint, authentication and tool schema are not configured; no call made.')
class DomesticLLMPlanner:
    def __init__(self,*args,**kwargs):
        raise NotConfigured('Domestic LLM provider/model/authentication are not configured; no call made.')
