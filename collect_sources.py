import json, re
from datetime import datetime, timezone
from pathlib import Path
import requests

SOURCES={
"min-repo":"https://min-repo.com/tag/%E6%A5%BD%E5%9C%92%E4%B8%8A%E6%96%B0%E5%B1%8B%E5%BA%97/",
"ana-slo":"https://ana-slo.com/%E3%83%9B%E3%83%BC%E3%83%AB%E3%83%87%E3%83%BC%E3%82%BF/%E9%9D%99%E5%B2%A1%E7%9C%8C/%E6%A5%BD%E5%9C%92%E4%B8%8A%E6%96%B0%E5%B1%8B%E5%BA%97-%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%80%E8%A6%A7/",
"d-delta":"https://www.d-deltanet.com/pc/D0101.do?pmc=22021009"
}
# This first-stage collector only records reachability. It intentionally does not
# invent or parse values when a source layout/permission changes.
def main():
    out=json.loads(Path("data.json").read_text(encoding="utf-8"))
    out["updated_at"]=datetime.now(timezone.utc).isoformat()
    out["sources"]={}
    for name,url in SOURCES.items():
        try:
            r=requests.get(url,timeout=25,headers={"User-Agent":"Mozilla/5.0"})
            out["sources"][name]={"ok":r.ok,"status":r.status_code,"checked_at":out["updated_at"]}
        except Exception as e:
            out["sources"][name]={"ok":False,"error":str(e),"checked_at":out["updated_at"]}
    Path("data.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": main()
