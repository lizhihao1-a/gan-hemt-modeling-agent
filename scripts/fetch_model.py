"""Fetch the exact upstream model used by the archived local runs."""
from pathlib import Path
import argparse
import hashlib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://raw.githubusercontent.com/rafapm/dfo_parameter_extraction/a8d945a1d2f70c27998be7d0071cd6602bca02b5/notebooks/HEMT_ex/ngspice_notebook_and_files/asmhemt.va'
SHA256 = '189002cdd52996994cb4dcf7171050374237832f61dbfa1a3a43cc4439c94edc'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', choices=['all','DFO_DC_Baseline','GaN_HEMT_Local_Agent'], default='all')
    args=parser.parse_args()
    with urllib.request.urlopen(URL, timeout=90) as response:
        source=response.read()
    if hashlib.sha256(source).hexdigest()!=SHA256:
        raise RuntimeError('Upstream model hash mismatch; no file written')
    names=['DFO_DC_Baseline','GaN_HEMT_Local_Agent'] if args.project=='all' else [args.project]
    for name in names:
        path=ROOT/'outputs'/name/'models/asmhemt.va'
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=SHA256:
            raise RuntimeError(f'Existing model differs: {name}; preserve it before fetching')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(source)
        print(f'{name}: verified upstream ASM-HEMT source')

if __name__=='__main__': main()
