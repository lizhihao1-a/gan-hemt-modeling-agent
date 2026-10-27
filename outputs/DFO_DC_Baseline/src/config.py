"""Published search ranges, pinned before accessing held-out test targets."""
FIXED={'TNOM':25,'L':150e-9,'W':50e-6,'NF':4,'NGCON':1,'LDG':1e-6,'LSG':1e-6,
       'TBAR':23e-9,'SHMOD':1,'TRAPMOD':0,'GATEMOD':2,'RDSMOD':1,'RGATEMOD':2}
# name: lower, upper, log10 search. From the pinned author notebook, not best_params.
BOUNDS={
 'RTH0':(31.5,32.5,False),'VOFF':(-2.1,-1.9,False),'NFACTOR':(.2,.5,False),
 'U0':(.15,.3,False),'UA':(1e-8,50e-8,False),'UB':(1e-21,1e-18,True),
 'VSAT':(150e3,250e3,False),'LAMBDA':(100e-6,1500e-6,False),
 'UTE':(-1,-.1,False),'ETA0':(.01,.1,False),'VDSCALE':(2,6,False),
 'CDSCD':(.001,.150,False),'RSC':(.0001,.0015,False),'RDC':(.0001,.0015,False),
 'DELTA':(2,5,False),'THESAT':(1,4,False),
 'NJGD':(2.5,20,False),'RNJGD':(15,30,False),'IGDDIO':(7.5,15,False),
 'RIGDDIO':(10e-9,100e-9,False),'NJGS':(2.5,20,False),'RNJGS':(5,15,False),
 'IGSDIO':(2.5,10,False),'RIGSDIO':(10e-9,100e-9,False),
 'VSATACCS':(10e3,150e3,False),'NS0ACCS':(5e15,5e20,True),
 'NS0ACCD':(5e15,5e20,True),'U0ACCS':(.05,.25,False),'U0ACCD':(.05,.25,False),
 'MEXPACCS':(1,5,False),'MEXPACCD':(1,5,False),
 'IMIN':(1e-15,1e-12,True),'GDSMIN':(1e-12,1e-6,True),
 'UTES':(-17.5,-5,False),'UTED':(-17.5,-5,False)}
ACTIVE=[k for k in BOUNDS if k not in {
 'NJGD','RNJGD','IGDDIO','RIGDDIO','NJGS','RNJGS','IGSDIO','RIGSDIO',
 'IMIN','GDSMIN','UTES','UTED'}]
SEED=20261020
N_STARTS=3
MAX_NFEV=100
ID_FLOOR=1e-4
GM_FLOOR=1e-3
