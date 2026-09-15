import argparse, sys, types, inspect, json, shutil, hashlib, subprocess
from pathlib import Path
import torch, numpy as np, onnx, onnxruntime as ort
from omegaconf import OmegaConf
parser = argparse.ArgumentParser(description="Export a 173-token, two-step IntMeanFlow student acoustic model.")
parser.add_argument("--distill-source", type=Path, required=True)
parser.add_argument("--checkpoint", type=Path, required=True)
parser.add_argument("--frontend-assets", type=Path, required=True, help="Legacy 150-token frontend asset bundle")
parser.add_argument("--vocos", type=Path, required=True, help="Matching exported 24 kHz Vocos ONNX")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--temperature", type=float, default=0.0)
args = parser.parse_args()
if not np.isfinite(args.temperature) or args.temperature < 0:
 parser.error("temperature must be finite and nonnegative")
SRC=args.distill_source.resolve(); OUT=args.output.resolve()
if OUT == args.frontend_assets.resolve():
 parser.error("output must differ from frontend-assets")
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(SRC))
stub=types.ModuleType('lits.utils.monotonic_align.core')
def unavailable(*a,**k): raise RuntimeError('Training alignment is not used for export')
stub.maximum_path_c=unavailable; stub.maximum_path_constrained_c=unavailable
sys.modules[stub.__name__]=stub
from lits.models.lits import LITS
from meanflow_distill.interval_estimator import IntervalConditionedEstimator
from lits.text.char_symbols.langs.zh_en_rhyme_body_tone_tokens import symbols
from lits.text.bopomofo_utils import split_bpmf_body
from lits.text import text_to_sequence
checkpoint=args.checkpoint
p=torch.load(checkpoint,map_location='cpu',weights_only=False)
h={k:v for k,v in p['hyper_parameters'].items() if k in inspect.signature(LITS.__init__).parameters}
for k in ('encoder','decoder','cfm','data_statistics'): h[k]=OmegaConf.create(h[k])
for k in list(h):
 if k.endswith('_path'): h[k]=None
h['optimizer']=None
model=LITS(**h).eval(); model.decoder.estimator=IntervalConditionedEstimator(model.decoder.estimator)
model.load_state_dict(p['state_dict'],strict=True)
torch.set_num_threads(4)
torch.set_grad_enabled(False)
grid=p['metadata']['student_t_grid']; assert grid==[0.,.5,1.]
assert p['distill_args']['decoder_streaming'] is False
assert len(symbols)==model.n_vocab==173
base=args.frontend_assets
assert args.vocos.is_file(), 'Matching 24 kHz Vocos ONNX is required'
for f in base.iterdir():
 if f.is_dir(): shutil.copytree(f,OUT/f.name,dirs_exist_ok=True)
 elif f.suffix != '.onnx': shutil.copy2(f,OUT/f.name)
shutil.copy2(args.vocos, OUT/'vocos_vocoder.onnx')
(OUT/'zh_en_symbols.json').write_text(json.dumps({'symbols':symbols},ensure_ascii=False,indent=2)+'\n')
old=json.loads((base/'pinyin_to_tokens.json').read_text())['pinyin_to_tokens']; new={}
for k,t in old.items():
 tones=[x for x in t if x in 'ˉˊˇˋ˙']
 if not tones: raise ValueError(k)
 body=''.join(x for x in t if x not in ('_','ˉ','ˊ','ˇ','ˋ','˙'))
 initial,rhyme=split_bpmf_body(body)
 new[k]=[x for x in (initial,rhyme,tones[-1]) if x]
 assert all(x in symbols for x in new[k]),(k,new[k])
(OUT/'pinyin_to_tokens.json').write_text(json.dumps({'pinyin_to_tokens':new},ensure_ascii=False,indent=2)+'\n')
class Acoustic(torch.nn.Module):
 def __init__(self,m): super().__init__(); self.m=m
 def hidden(self,ids,lengths,speaker):
  h=self.m.get_hidden_mel(ids,lengths,spks=speaker)
  mu=self.m.decoder.encode_mu(h['mu_y'],h['y_mask'],finalize=True,streaming=False)
  length=h['y_max_length']
  return mu[:,:,:length],h['y_mask'][:,:,:length],h['spks']
 def solve(self,mu,mask,spks,z):
  x=z
  for r,t in zip(grid[:-1],grid[1:]):
   rv=torch.full((1,),r,dtype=x.dtype,device=x.device); tv=torch.full((1,),t,dtype=x.dtype,device=x.device)
   v=self.m.decoder.estimator(x,mask,mu,tv,spks,None,streaming=False,r=rv)
   x=x+(t-r)*v
  return x*self.m.mel_std+self.m.mel_mean
 def forward(self,token_ids,token_lengths,speaker_id):
  mu,mask,spks=self.hidden(token_ids,token_lengths,speaker_id)
  z=torch.randn_like(mu)*args.temperature
  return self.solve(mu,mask,spks,z),z
wrapper=Acoustic(model).eval()
# Export with noise exposed only for numerical comparison, then remove that output.
def ids_for(s):
 ids,_=text_to_sequence(s,['pinyin_direct_mixed_rhyme_body_tone_cleaners'])
 return torch.tensor([ids],dtype=torch.long)
x=ids_for('ni3 hao3 .'); lens=torch.tensor([x.shape[1]]); sp=torch.tensor([1])
for m in model.modules():
 if hasattr(m,'cos_cached'): m.cos_cached=None
 if hasattr(m,'sin_cached'): m.sin_cached=None
with torch.inference_mode(): wrapper(x,lens,sp)
for m in model.modules():
 if hasattr(m,'cos_cached'): m.cos_cached=None
 if hasattr(m,'sin_cached'): m.sin_cached=None
print('Exporting 173-token whole-utterance IntMeanFlow acoustic graph',flush=True)
path=OUT/'lits_acoustic.onnx'
torch.onnx.export(wrapper,(x,lens,sp),str(path),input_names=['token_ids','token_lengths','speaker_id'],output_names=['mel','initial_noise'],dynamic_axes={'token_ids':{1:'tokens'},'mel':{2:'frames'},'initial_noise':{2:'frames'}},opset_version=17,dynamo=False)
onnx.checker.check_model(str(path))
opt=ort.SessionOptions(); opt.intra_op_num_threads=4; opt.inter_op_num_threads=1
session=ort.InferenceSession(str(path),sess_options=opt,providers=['CPUExecutionProvider'])
reports=[]
for txt,speaker in [('yi1 .',1),('er4 .',1),('ni3 hao3 shi4 jie4 .',1),('HH AH0 L OW1 _ W ER1 L D .',0)]:
 x=ids_for(txt); lengths=torch.tensor([x.shape[1]]); sp=torch.tensor([speaker])
 mel,z=session.run(None,{'token_ids':x.numpy(),'token_lengths':lengths.numpy(),'speaker_id':sp.numpy()})
 with torch.inference_mode():
  mu,mask,se=wrapper.hidden(x,lengths,sp)
  expected=wrapper.solve(mu,mask,se,torch.from_numpy(z)).numpy()
 diff=np.abs(mel-expected)
 assert np.isfinite(mel).all()
 assert diff.mean()<0.005 and diff.max()<0.1,(txt,float(diff.mean()),float(diff.max()))
 reports.append({'text':txt,'speaker':speaker,'tokens':x.tolist()[0],'shape':list(mel.shape),'mean_abs':float(diff.mean()),'max_abs':float(diff.max())})
 np.save(OUT/f'validation-mel-{len(reports)}.npy',mel)
 print(reports[-1],flush=True)
g=onnx.load(str(path)); del g.graph.output[1:]; onnx.save(g,str(path)); onnx.checker.check_model(str(path))
manifest=json.loads((base/'manifest.json').read_text())
for k in list(manifest):
 if k.startswith('stream') or k in ('hidden_encoder_model',): manifest.pop(k)
manifest.update(model_id='dingqiao_intmeanflow_student_0010000_vocos24k',model_type='lits_intmeanflow_utterance',supports_streaming=False,acoustic_model={'file':'lits_acoustic.onnx','format':'onnx'},vocoder_model={'file':'vocos_vocoder.onnx','format':'onnx'},vocoder_type='vocos',sample_rate=24000,hop_length=384,frontend_paradigm='rhyme_body_tone_173',prepend_sil=True,student_t_grid=grid,inference_temperature=args.temperature,checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
# Inventory is finalized after all reports and frontend fixtures have been written.
manifest['files']=[{'name':f.relative_to(OUT).as_posix(),'size_bytes':f.stat().st_size} for f in OUT.rglob('*') if f.is_file() and f.name not in ('manifest.json',) and f.suffix!='.npy']
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
report={'source_commit':'d878405d1a2c10eef0aefe5eb3227ca1fd3de2eb','checkpoint_sha256':manifest['checkpoint_sha256'],'state_dict_strict':True,'vocabulary':173,'supports_streaming':False,'student_t_grid':grid,'inference_temperature':args.temperature,'training_temperature':float(p['distill_args']['temperature']),'validation':reports}
(OUT/'export_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
golden={'scope':'Training phonetic-cleaner oracle; not full Android raw-text frontend coverage.', 'vocabulary':173,
 'cases':[{'label':f'training_oracle_{i+1}', 'text':r['text'], 'cleaned_text':' '.join(symbols[x] for x in r['tokens']), 'token_ids':r['tokens'], 'token_length':len(r['tokens'])} for i,r in enumerate(reports)]}
(OUT/'frontend_golden.json').write_text(json.dumps(golden,ensure_ascii=False,indent=2)+'\n')
manifest['files']=[{'name':f.relative_to(OUT).as_posix(),'size_bytes':f.stat().st_size} for f in sorted(OUT.rglob('*')) if f.is_file() and f.name != 'manifest.json' and f.suffix != '.npy']
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print('ACOUSTIC EXPORT VERIFIED',flush=True)
