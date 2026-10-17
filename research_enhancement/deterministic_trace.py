"""Create a deterministic varied input trace from an existing reference test-set JSON.
Input format: [{"features": [...], "expected": ...}, ...]; predictions must be precomputed by reference code.
"""
import argparse, json, random
from pathlib import Path

def create(rows,count,seed):
    if not rows or any('features' not in row or 'expected' not in row for row in rows):
        raise ValueError('reference rows must have features and expected prediction')
    rng=random.Random(seed); order=list(range(len(rows))); result=[]
    while len(result)<count:
        rng.shuffle(order)
        result.extend({'row_index':i,'features':rows[i]['features'],'expected':rows[i]['expected']} for i in order)
    return result[:count]

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--reference-json',required=True);ap.add_argument('--out',required=True);ap.add_argument('--count',type=int,default=5000);ap.add_argument('--seed',type=int,default=42)
    a=ap.parse_args();Path(a.out).write_text(json.dumps(create(json.loads(Path(a.reference_json).read_text()),a.count,a.seed),indent=2))
