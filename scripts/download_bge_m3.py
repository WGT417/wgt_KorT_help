"""Download public BGE-M3 model files; never sends library text.

  python scripts/download_bge_m3.py          # tokenizer + int8 model for answering queries (0.6GB)
  python scripts/download_bge_m3.py --full   # also the full-precision model that builds the index (2.3GB)
"""
import sys,argparse
from pathlib import Path
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import vector_search as vs

QUERY=[('https://huggingface.co/BAAI/bge-m3/resolve/main/tokenizer.json','tokenizer.json'),
    ('https://huggingface.co/Xenova/bge-m3/resolve/main/onnx/model_quantized.onnx','model_quantized.onnx')]
FULL=[('https://huggingface.co/BAAI/bge-m3/resolve/main/onnx/model.onnx','model.onnx'),
    ('https://huggingface.co/BAAI/bge-m3/resolve/main/onnx/model.onnx_data','model.onnx_data')]

def fetch(url,path):
    part=path.with_name(path.name+'.download')
    with urlopen(url,timeout=60) as response,open(part,'wb') as out:
        total=int(response.headers.get('Content-Length') or 0);done=0
        while chunk:=response.read(1<<22):
            out.write(chunk);done+=len(chunk)
            if total:print(f'\r  {path.name} {done/1e6:,.0f}/{total/1e6:,.0f}MB',end='',flush=True)
    part.replace(path);print()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    vs.MODEL_DIR.mkdir(parents=True,exist_ok=True)
    for url,name in QUERY+(FULL if args.full else []):
        path=vs.MODEL_DIR/name
        if path.exists():print('있음',name);continue
        fetch(url,path)
    print('준비 완료:',vs.MODEL_DIR)

if __name__=='__main__':main()
