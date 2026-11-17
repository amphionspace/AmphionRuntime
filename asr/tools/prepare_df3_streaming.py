"""Expose DeepFilterNet3 convolution/GRU state for single-frame ORT inference.
Preserves neural weights. Verifies against the original sequence graphs before writing assets.
"""
import argparse,hashlib,json,tarfile
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper as h, numpy_helper as nh, TensorProto as T

def prune(m):
 producers={o:n for n in m.graph.node for o in n.output};keep=set()
 def visit(x):
  if x not in producers:return
  n=producers[x]
  if n.name in keep:return
  keep.add(n.name)
  for i in n.input:visit(i)
 for o in m.graph.output:visit(o.name)
 nodes=[n for n in m.graph.node if n.name in keep];del m.graph.node[:];m.graph.node.extend(nodes)
 used={i for n in nodes for i in n.input};init=[x for x in m.graph.initializer if x.name in used];del m.graph.initializer[:];m.graph.initializer.extend(init)
 del m.graph.value_info[:]

def convert(original):
 m=onnx.ModelProto();m.CopyFrom(original);old={o:n for n in m.graph.node for o in n.output};new=[];states=[]
 shapes={v.name:[d.dim_value or d.dim_param for d in v.type.tensor_type.shape.dim] for v in m.graph.input}
 for n in m.graph.node:
  if n.op_type=='Conv':
   attrs={a.name:h.get_attribute_value(a) for a in n.attribute};k=attrs['kernel_shape'][0]
   if k>1:
    pad=old[n.input[0]];assert pad.op_type=='Pad';source=pad.input[0];shape=shapes[source].copy();shape[2]=k-1
    name='state_'+str(len(states));states.append((name,shape))
    m.graph.input.append(h.make_tensor_value_info(name,T.FLOAT,shape));m.graph.output.append(h.make_tensor_value_info(name+'_out',T.FLOAT,shape))
    cat=name+'_cat';new.append(h.make_node('Concat',[name,source],[cat],axis=2,name=name+'_concat'))
    for suffix,val in [('start',[1]),('end',[k]),('axis',[2])]:m.graph.initializer.append(nh.from_array(np.array(val,np.int64),name+'_'+suffix))
    new.append(h.make_node('Slice',[cat,name+'_start',name+'_end',name+'_axis'],[name+'_out'],name=name+'_slice'));n.input[0]=cat
  if n.op_type=='GRU':
   attrs={a.name:h.get_attribute_value(a) for a in n.attribute};assert attrs.get('direction',b'forward')==b'forward'
   name='state_'+str(len(states));shape=[1,1,attrs['hidden_size']];states.append((name,shape))
   m.graph.input.append(h.make_tensor_value_info(name,T.FLOAT,shape));m.graph.output.append(h.make_tensor_value_info(name+'_out',T.FLOAT,shape))
   n.input[5]=name;new.append(n);new.append(h.make_node('Identity',[n.output[1]],[name+'_out'],name=name+'_identity'));continue
  new.append(n)
 del m.graph.node[:];m.graph.node.extend(new)
 for v in m.graph.input:
  for d in v.type.tensor_type.shape.dim:
   if d.dim_param=='S':d.dim_value=1
 # Explicit output dimensions are inferred from the rewritten graph.
 for v in list(m.graph.output)[:len(original.graph.output)]:
  for d in v.type.tensor_type.shape.dim:
   if d.dim_param=='S':d.dim_value=1
 prune(m);onnx.checker.check_model(m)
 return m,states

def session(m):
 o=ort.SessionOptions();o.intra_op_num_threads=1;o.inter_op_num_threads=1;o.log_severity_level=3
 return ort.InferenceSession(m.SerializeToString(),o,providers=['CPUExecutionProvider'])

def main():
 a=argparse.ArgumentParser();a.add_argument('--archive',type=Path,required=True);a.add_argument('--output',type=Path,required=True);args=a.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 records=[];rng=np.random.default_rng(20261117)
 with tarfile.open(args.archive) as t:
  for member in t.getmembers():
   if not member.name.endswith('.onnx'):continue
   data=t.extractfile(member).read();original=onnx.load_from_string(data);m,states=convert(original);base=session(original);stream=session(m)
   inputs={}
   for v in base.get_inputs():inputs[v.name]=rng.standard_normal([19 if d=='S' else d for d in v.shape]).astype(np.float32)*.2
   expected=base.run(None,inputs);state={n:np.zeros(sh,np.float32) for n,sh in states};chunks=[[] for _ in expected]
   for ti in range(19):
    frame={v.name:np.take(inputs[v.name],[ti],axis=v.shape.index('S')) for v in base.get_inputs()};got=stream.run(None,{**frame,**state})
    state={n:got[len(expected)+j] for j,(n,_) in enumerate(states)}
    for j in range(len(expected)):chunks[j].append(got[j])
   errors=[]
   for v,e,c in zip(base.get_outputs(),expected,chunks):
    axis=1 if v.name in ['emb','lsnr','coefs','235'] else 2
    actual=np.concatenate(c,axis=axis);err=float(np.max(np.abs(actual-e)));errors.append({'output':v.name,'maxAbsError':err});np.testing.assert_allclose(actual,e,atol=3e-5,rtol=3e-4)
   dest=args.output/('df3_'+Path(member.name).stem+'_stream.onnx');onnx.save(m,str(dest))
   record={'file':dest.name,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'bytes':dest.stat().st_size,'sourceSha256':hashlib.sha256(data).hexdigest(),'states':states,'sequenceParity':errors};records.append(record);print(json.dumps(record),flush=True)
 (args.output/'df3.manifest.json').write_text(json.dumps({'source':'https://github.com/Rikorose/DeepFilterNet','archiveSha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),'modification':'Expose causal convolution history and GRU hidden states; original weights retained','graphs':records},indent=2),encoding='utf8')
if __name__=='__main__':main()
