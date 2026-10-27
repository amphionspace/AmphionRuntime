"""最小 OBS 客户端（标准库实现华为云 OBS V2 签名），用于查找数据集。

StringToSign = VERB\n Content-MD5\n Content-Type\n Date\n CanonicalizedHeaders CanonicalizedResource
Signature    = Base64(HMAC-SHA1(SK, StringToSign))
Authorization: OBS <AK>:<Signature>
"""
import base64, configparser, hashlib, hmac, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ini import ini_path, remotes_json
from email.utils import formatdate

INI=ini_path("OBS_INI")
_cp=configparser.ConfigParser(); _cp.read(INI)
AK=_cp["obs"]["access_key"].strip(); SK=_cp["obs"]["secret_key"].strip()

def _sign(method, bucket, key, params, date):
    sub=[]
    for k in sorted(params):
        if k in ("prefix","delimiter","max-keys","marker","list-type","continuation-token"):
            continue
        sub.append(k if params[k] is None else f"{k}={params[k]}")
    res=f"/{bucket}/{urllib.parse.quote(key.lstrip('/'), safe='/')}"
    if sub: res += "?" + "&".join(sub)
    sts=f"{method}\n\n\n{date}\n{res}"
    sig=base64.b64encode(hmac.new(SK.encode(), sts.encode(), hashlib.sha1).digest()).decode()
    return f"OBS {AK}:{sig}"

def request(bucket, endpoint, method="GET", key="", params=None, want_bytes=False, timeout=60):
    params=params or {}
    host=urllib.parse.urlsplit(endpoint).netloc
    vhost=f"{bucket}.{host}"
    date=formatdate(usegmt=True)
    auth=_sign(method, bucket, key, params, date)
    q="&".join(f"{urllib.parse.quote(k,safe='')}={urllib.parse.quote(str(v),safe='')}"
               for k,v in params.items() if v is not None)
    url=f"https://{vhost}/{urllib.parse.quote(key.lstrip('/'), safe='/')}" + (f"?{q}" if q else "")
    req=urllib.request.Request(url, method=method)
    req.add_header("Authorization", auth); req.add_header("Date", date); req.add_header("Host", vhost)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if want_bytes else r.read().decode("utf-8","replace")

def _t(tag): return tag.split("}",1)[-1]

def listdir(bucket, endpoint, prefix="", delimiter="/", max_keys=1000):
    dirs=[]; files=[]; marker=None
    while True:
        p={"prefix":prefix,"max-keys":str(max_keys)}
        if delimiter: p["delimiter"]=delimiter
        if marker: p["marker"]=marker
        root=ET.fromstring(request(bucket, endpoint, params=p))
        trunc=False; last=None
        for el in root:
            t=_t(el.tag)
            if t=="CommonPrefixes":
                for c in el:
                    if _t(c.tag)=="Prefix": dirs.append(c.text)
            elif t=="Contents":
                k=sz=None
                for c in el:
                    if _t(c.tag)=="Key": k=c.text
                    elif _t(c.tag)=="Size": sz=int(c.text)
                if k is not None: files.append((k,sz)); last=k
            elif t=="IsTruncated": trunc=(el.text=="true")
            elif t=="NextMarker": marker=el.text
        if not trunc: break
        if not marker: marker=last
        if not marker: break
    return dirs, files

if __name__=="__main__":
    import json
    rem=json.load(open(remotes_json(),encoding="utf-8"))["remotes"]
    pre=sys.argv[1] if len(sys.argv)>1 else ""
    deli=sys.argv[2] if len(sys.argv)>2 else "/"
    for name,v in rem.items():
        if v["provider"]!="obs": continue
        try:
            d,f=listdir(v["bucket"], v["endpoint"], pre, deli)
            print(f"[{v['bucket']}] prefix={pre!r}  {len(d)} 目录 {len(f)} 文件")
            for x in d[:14]: print("    DIR", x.rstrip('/').split('/')[-1])
            for k,s in sorted(f,key=lambda x:-x[1])[:6]: print(f"    {s/1e6:>9.1f}MB {k}")
        except Exception as e:
            print(f"[{v['bucket']}] 错误: {str(e)[:90]}")
