"""Minimal synchronous ctypes interface; no PySpice or network needed at run time."""
import ctypes as C
import os
from pathlib import Path
import numpy as np

class Vector(C.Structure):
    _fields_ = [('name',C.c_char_p),('type',C.c_int),('flags',C.c_short),
                ('real',C.POINTER(C.c_double)),('complex',C.c_void_p),('length',C.c_int)]

class Simulator:
    def __init__(self, root, params):
        self.root=Path(root).resolve()
        workspace=self.root.parent.parent
        dll=self.root/'runtime/ngspice.dll'
        if not dll.exists():
            dll=next((workspace/'work/dfo_tools/ngspice_dll').rglob('ngspice.dll'))
        self.dll_dir=os.add_dll_directory(str(dll.parent))
        extra=workspace/'work/dfo_tools/ngspice/Spice64/bin'
        self.bin_dir=os.add_dll_directory(str(extra)) if extra.exists() else None
        self.lib=C.CDLL(str(dll))
        self.messages=[]
        callback=C.CFUNCTYPE(C.c_int,C.c_char_p,C.c_int,C.c_void_p)
        self.on_text=callback(lambda msg,ident,user:self.log(msg))
        exitcb=C.CFUNCTYPE(C.c_int,C.c_int,C.c_bool,C.c_bool,C.c_int,C.c_void_p)
        self.on_exit=exitcb(lambda *args:0)
        self.lib.ngSpice_Init(self.on_text,None,self.on_exit,None,None,None,None)
        self.lib.ngSpice_Command.argtypes=[C.c_char_p]
        self.lib.ngGet_Vec_Info.argtypes=[C.c_char_p]
        self.lib.ngGet_Vec_Info.restype=C.POINTER(Vector)
        self.cmd('set noaskquit')
        self.cmd('set num_threads=1')
        # ngspice command parser keeps literal quotes; a relative path supports spaces in the project path.
        os.chdir(self.root)
        self.cmd('osdi models/asmhemt.osdi')
        model='.model nfet asmhemt ('+' '.join(f'{k}={v:.14g}' for k,v in params.items())+')'
        lines=['DFO 4x50 DC baseline',model,'.temp 25','.options tnom=25 reltol=1e-5 abstol=1e-12',
               'vd d 0 0','vg g 0 0','vs s 0 0','vb b 0 0','N1 di gi s b dt nfet',
               'rth_external dt 0 1e12','r_gate g gi 0.3178','r_drain d di 0.4938','.end']
        self.netlist='\n'.join(lines)+'\n'
        array=(C.c_char_p*(len(lines)+1))(*[s.encode() for s in lines],None)
        self.lib.ngSpice_Circ(array)
        self.cmd('save i(vd) v(g) v(d) v(dt)')

    def log(self,msg):
        self.messages.append(msg.decode(errors='replace'))
        return 0

    def cmd(self,s):
        ret=self.lib.ngSpice_Command(s.encode())
        if ret: raise RuntimeError(f'ngspice command failed ({ret}): {s}\n'+ '\n'.join(self.messages[-8:]))

    def vec(self,name):
        p=self.lib.ngGet_Vec_Info(name.encode())
        if not p: raise RuntimeError('Missing vector '+name+'\n'+'\n'.join(self.messages[-15:]))
        v=p.contents
        return np.ctypeslib.as_array(v.real,shape=(v.length,)).copy()

    def simulate(self,params):
        self.messages=[]
        for k,v in params.items(): self.cmd(f'altermod nfet {k}={v:.14g}')
        self.cmd('dc vd 0 20 0.1 vg -3 -0.1 0.1')
        current=-self.vec('vd#branch').reshape(30,201)
        temp=self.vec('dt').reshape(30,201)
        if not np.isfinite(current).all(): raise RuntimeError('Nonfinite simulation')
        gm=np.gradient(current,0.1,axis=0)
        self.cmd('destroy all')
        return current,gm,temp
