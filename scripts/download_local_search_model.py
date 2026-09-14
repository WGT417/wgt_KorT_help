"""Download public model assets only; never sends library text."""
import sys
from pathlib import Path
from urllib.request import urlretrieve
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
target=core.DATA/'models'/'multilingual-e5-small';target.mkdir(parents=True,exist_ok=True)
for remote,local in [('model_qint8_avx512_vnni.onnx','model.onnx'),('tokenizer.json','tokenizer.json')]:
 path=target/local
 if path.exists():continue
 print('Download',remote,flush=True)
 urlretrieve('https://huggingface.co/intfloat/multilingual-e5-small/resolve/main/onnx/'+remote,str(path.with_suffix('.download')))
 path.with_suffix('.download').replace(path)
print('Ready',flush=True)
