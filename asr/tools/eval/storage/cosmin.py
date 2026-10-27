"""最小 COS 客户端（标准库实现 COS Signature v5），用于列举/下载评测语料。

签名规范：
  SignKey     = HMAC-SHA1(SecretKey, KeyTime)
  HttpString  = method\n uri \n params \n headers \n
  StringToSign= sha1\n SignTime \n SHA1(HttpString) \n
  Signature   = HMAC-SHA1(SignKey, StringToSign)
"""
import configparser, hashlib, hmac, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ini import ini_path

INI = ini_path("COS_INI")
BUCKET = os.environ.get("COS_BUCKET", "anfeiweng-audiollm-resource-1373259071")
REGION = os.environ.get("COS_REGION", "ap-guangzhou")
HOST = f"{BUCKET}.cos.{REGION}.myqcloud.com"

_cp = configparser.ConfigParser()
_cp.read(INI)
AK = _cp["cos"]["access_key"].strip()
SK = _cp["cos"]["secret_key"].strip()

def _sign(method, uri, params, headers):
    now = int(time.time()); t = f"{now-60};{now+900}"
    sign_key = hmac.new(SK.encode(), t.encode(), hashlib.sha1).hexdigest()
    pl = ";".join(sorted(k.lower() for k in params))
    hl = ";".join(sorted(k.lower() for k in headers))
    pstr = "&".join(f"{k.lower()}={urllib.parse.quote(str(params[k]), safe='')}"
                    for k in sorted(params, key=str.lower))
    hstr = "&".join(f"{k.lower()}={urllib.parse.quote(str(headers[k]), safe='')}"
                    for k in sorted(headers, key=str.lower))
    http_string = f"{method.lower()}\n{uri}\n{pstr}\n{hstr}\n"
    sts = f"sha1\n{t}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    sig = hmac.new(sign_key.encode(), sts.encode(), hashlib.sha1).hexdigest()
    return (f"q-sign-algorithm=sha1&q-ak={AK}&q-sign-time={t}&q-key-time={t}"
            f"&q-header-list={hl}&q-url-param-list={pl}&q-signature={sig}")

def request(method, key="/", params=None, want_bytes=False, timeout=120):
    params = params or {}
    # COS v5 签名用未编码的原始路径；URL 用编码后的路径。两者不同，必须分开。
    uri_raw = "/" + key.lstrip("/")
    uri = "/" + urllib.parse.quote(key.lstrip("/"), safe="/")
    headers = {"Host": HOST}
    auth = _sign(method, uri_raw, params, headers)
    q = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
                 for k, v in params.items())
    url = f"https://{HOST}{uri}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", auth)
    req.add_header("Host", HOST)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if want_bytes else r.read().decode("utf-8", "replace")

NS = "{http://www.qcloud.com/document/product/436/7751}"
def _strip(tag): return tag.split("}", 1)[-1]

def listdir(prefix="", delimiter="/", max_keys=1000):
    """返回 (子目录列表, 文件列表[(key,size)])，自动翻页。"""
    dirs, files, token = [], [], None
    while True:
        p = {"list-type": "2", "prefix": prefix, "max-keys": str(max_keys)}
        if delimiter: p["delimiter"] = delimiter
        if token: p["continuation-token"] = token
        root = ET.fromstring(request("GET", "/", p))
        trunc, token = False, None
        for el in root:
            tag = _strip(el.tag)
            if tag == "CommonPrefixes":
                for c in el:
                    if _strip(c.tag) == "Prefix": dirs.append(c.text)
            elif tag == "Contents":
                k = sz = None
                for c in el:
                    if _strip(c.tag) == "Key": k = c.text
                    elif _strip(c.tag) == "Size": sz = int(c.text)
                if k is not None: files.append((k, sz))
            elif tag == "IsTruncated": trunc = (el.text == "true")
            elif tag == "NextContinuationToken": token = el.text
        if not (trunc and token): break
    return dirs, files

def get(key, dest=None):
    data = request("GET", key, want_bytes=True)
    if dest:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f: f.write(data)
        return len(data)
    return data

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ls"
    pre = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "ls":
        d, f = listdir(pre)
        print(f"# 桶 {BUCKET}  前缀 {pre!r}")
        for x in d: print(f"  DIR   {x}")
        for k, s in f[:200]: print(f"  {s:>12}  {k}")
        print(f"# 共 {len(d)} 目录 / {len(f)} 文件")
    elif cmd == "find":
        d, f = listdir(pre, delimiter="")
        print(f"# 递归 {pre!r}: {len(f)} 文件")
        for k, s in f[:400]: print(f"  {s:>12}  {k}")
    elif cmd == "get":
        print(get(pre, sys.argv[3]), "bytes ->", sys.argv[3])
