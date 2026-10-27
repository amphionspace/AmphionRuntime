"""最小 AOSS 客户端（标准库实现 AWS SigV4），用于查找数据集。SenseCore AOSS 为 S3 兼容。"""
import configparser, datetime, hashlib, hmac, os, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ini import ini_path

INI=ini_path("AOSS_INI")
_cp=configparser.ConfigParser(); _cp.read(INI)
AK=_cp["sensecore"]["access_key"].strip(); SK=_cp["sensecore"]["secret_key"].strip()
BUCKET=os.environ.get("AOSS_BUCKET","whai")
ENDPOINT=os.environ.get("AOSS_ENDPOINT","https://aoss.cn-sh-01b.sensecoreapi-oss.cn")
REGION=os.environ.get("AOSS_REGION","cn-sh-01b")
SERVICE="s3"

def _sign(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def request(method="GET", key="", params=None, want_bytes=False, timeout=60):
    params=params or {}
    host=urllib.parse.urlsplit(ENDPOINT).netloc
    # path-style：/bucket/key
    canon_uri="/"+BUCKET+"/"+urllib.parse.quote(key.lstrip("/"), safe="/")
    if key=="" : canon_uri="/"+BUCKET+"/"
    now=datetime.datetime.now(datetime.timezone.utc)
    amzdate=now.strftime("%Y%m%dT%H%M%SZ"); datestamp=now.strftime("%Y%m%d")
    payload_hash=hashlib.sha256(b"").hexdigest()
    cq="&".join(f"{urllib.parse.quote(k,safe='-_.~')}={urllib.parse.quote(str(v),safe='-_.~')}"
                for k,v in sorted(params.items()))
    canon_headers=f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amzdate}\n"
    signed_headers="host;x-amz-content-sha256;x-amz-date"
    canon_req=f"{method}\n{canon_uri}\n{cq}\n{canon_headers}\n{signed_headers}\n{payload_hash}"
    scope=f"{datestamp}/{REGION}/{SERVICE}/aws4_request"
    sts=f"AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n{hashlib.sha256(canon_req.encode()).hexdigest()}"
    k=_sign(("AWS4"+SK).encode(), datestamp); k=_sign(k,REGION); k=_sign(k,SERVICE); k=_sign(k,"aws4_request")
    sig=hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    auth=(f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, SignedHeaders={signed_headers}, Signature={sig}")
    url=f"{ENDPOINT}{canon_uri}"+(f"?{cq}" if cq else "")
    req=urllib.request.Request(url, method=method)
    req.add_header("Authorization",auth); req.add_header("x-amz-date",amzdate)
    req.add_header("x-amz-content-sha256",payload_hash); req.add_header("Host",host)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if want_bytes else r.read().decode("utf-8","replace")

def _t(t): return t.split("}",1)[-1]
def listdir(prefix="", delimiter="/", max_keys=1000):
    dirs=[]; files=[]; token=None
    while True:
        p={"list-type":"2","prefix":prefix,"max-keys":str(max_keys)}
        if delimiter: p["delimiter"]=delimiter
        if token: p["continuation-token"]=token
        root=ET.fromstring(request(params=p))
        trunc=False; token=None
        for el in root:
            t=_t(el.tag)
            if t=="CommonPrefixes":
                for c in el:
                    if _t(c.tag)=="Prefix": dirs.append(c.text)
            elif t=="Contents":
                kk=sz=None
                for c in el:
                    if _t(c.tag)=="Key": kk=c.text
                    elif _t(c.tag)=="Size": sz=int(c.text)
                if kk is not None: files.append((kk,sz))
            elif t=="IsTruncated": trunc=(el.text=="true")
            elif t=="NextContinuationToken": token=el.text
        if not(trunc and token): break
    return dirs, files

if __name__=="__main__":
    pre=sys.argv[1] if len(sys.argv)>1 else ""
    deli=sys.argv[2] if len(sys.argv)>2 else "/"
    d,f=listdir(pre, deli)
    print(f"[{BUCKET}] prefix={pre!r}  {len(d)} 目录 {len(f)} 文件")
    for x in d[:30]: print("    DIR", x.rstrip('/').split('/')[-1])
    for k,s in sorted(f,key=lambda x:-x[1])[:10]: print(f"    {s/1e6:>9.1f}MB {k}")
