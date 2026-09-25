import json,os
from datetime import datetime,timezone
from pathlib import Path
import requests
BASE=Path(__file__).resolve().parent;OUT=BASE/"data"/"news.json"
CATS={"ai":("AI",["artificial intelligence","generative AI"]),"semiconductor":("반도체",["semiconductor","chip industry"]),"quantum":("양자",["quantum computing","quantum technology"]),"space":("우주항공",["space industry","SpaceX aerospace"]),"robotics":("로봇",["robotics","humanoid robot"]),"energy":("에너지",["nuclear energy","SMR nuclear"]),"bigtech":("빅테크",["Apple Microsoft Google Amazon Meta"])}
def norm(x):
 t=str(x.get("title") or "").strip();u=str(x.get("url") or x.get("link") or "").strip()
 if not t or not u:return None
 s=x.get("source") or {};return {"title":t,"summary":str(x.get("description") or x.get("content") or "")[:300],"press":str(s.get("name") if isinstance(s,dict) else s or "News"),"time":str(x.get("publishedAt") or x.get("published") or ""),"url":u}
def api(url,params,label):
 try:
  r=requests.get(url,params=params,timeout=15);print(label,r.status_code)
  if not r.ok:print(label,"ERROR",r.text[:500]);return []
  return [z for x in r.json().get("articles",[]) if (z:=norm(x))]
 except Exception as e:print(label,"EXCEPTION",repr(e));return []
def main():
 gk=os.getenv("GNEWS_API_KEY","");nk=os.getenv("NEWSAPI_API_KEY","");cats={};providers=set()
 for cid,(title,qs) in CATS.items():
  a=[]
  for q in qs:
   if gk:a+=api("https://gnews.io/api/v4/search",{"q":q,"lang":"en","country":"us","max":10,"apikey":gk},"GNews")
  if a:providers.add("gnews")
  if not a:
   for q in qs:
    if nk:a+=api("https://newsapi.org/v2/everything",{"q":q,"language":"en","sortBy":"publishedAt","pageSize":10,"apiKey":nk},"NewsAPI")
   if a:providers.add("newsapi")
  seen=set();u=[]
  for x in a:
   if x["url"] not in seen:seen.add(x["url"]);u.append(x)
  cats[cid]={"title":title,"source":"gnews" if a and "gnews" in providers else ("newsapi" if a else "none"),"count":len(u[:10]),"news":u[:10]}
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps({"updated":datetime.now(timezone.utc).isoformat(),"provider":",".join(sorted(providers)) or "none","categories":cats},ensure_ascii=False,indent=2),encoding="utf-8")
 print("News counts:",{k:v["count"] for k,v in cats.items()})
if __name__=="__main__":main()