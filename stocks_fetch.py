import json,time
from datetime import datetime,timezone
from pathlib import Path
import yfinance as yf
BASE=Path(__file__).resolve().parent; OUT=BASE/"data"/"stocks.json"
STOCKS=[("NVDA","NVIDIA","AI"),("AMD","AMD","반도체"),("AVGO","Broadcom","반도체"),("MU","Micron","반도체"),("TSM","TSMC","반도체"),("INTC","Intel","반도체"),("QCOM","Qualcomm","반도체"),("MRVL","Marvell","반도체"),("AAPL","Apple","빅테크"),("MSFT","Microsoft","빅테크"),("GOOGL","Alphabet","빅테크"),("AMZN","Amazon","빅테크"),("META","Meta","빅테크"),("TSLA","Tesla","AI"),("PLTR","Palantir","AI"),("IONQ","IonQ","양자"),("RGTI","Rigetti Computing","양자"),("QBTS","D-Wave Quantum","양자"),("RKLB","Rocket Lab","우주항공"),("ASTS","AST SpaceMobile","우주항공"),("LUNR","Intuitive Machines","우주항공"),("RCAT","Red Cat","로봇"),("SERV","Serve Robotics","로봇"),("OKLO","Oklo","에너지"),("SMR","NuScale Power","에너지")]
def num(x):
 try:x=float(x);return x if x==x else None
 except:return None
def get_prices(sy):
 out={}
 try:
  d=yf.download(sy,period="5d",interval="1d",auto_adjust=False,progress=False,threads=True,group_by="column")
  if d is not None and not d.empty and "Close" in d.columns:
   c=d["Close"]
   for s in sy:
    try:
     z=c[s].dropna();p=num(z.iloc[-1]);q=num(z.iloc[-2]) if len(z)>1 else None
     out[s]={"price":p,"change":((p/q)-1)*100 if p is not None and q else None}
    except:pass
 except Exception as e:print("bulk price error:",repr(e))
 for s in sy:
  if s in out and out[s].get("price") is not None:continue
  try:
   z=yf.Ticker(s).history(period="5d",interval="1d",auto_adjust=False)["Close"].dropna()
   if len(z):
    p=num(z.iloc[-1]);q=num(z.iloc[-2]) if len(z)>1 else None;out[s]={"price":p,"change":((p/q)-1)*100 if p is not None and q else None}
  except Exception as e:print(s,"price error:",repr(e))
  time.sleep(.15)
 return out
def financials(s):
 try:
  q=yf.Ticker(s).quarterly_income_stmt
  if q is None or q.empty:return None,None,None
  def pick(names):
   for n in names:
    if n in q.index:
     r=q.loc[n].dropna()
     if len(r):return num(r.iloc[0]),r.index[0]
   return None,None
  rev,rd=pick(["Total Revenue","Operating Revenue"]);op,od=pick(["Operating Income"]);dt=rd or od
  return rev,op,str(dt.date()) if hasattr(dt,"date") else str(dt)[:10] if dt else None
 except Exception as e:print(s,"financial error:",repr(e));return None,None,None
def main():
 OUT.parent.mkdir(parents=True,exist_ok=True);sy=[x[0] for x in STOCKS];ps=get_prices(sy);arr=[]
 for s,n,c in STOCKS:
  rev,op,q=financials(s);p=ps.get(s,{})
  arr.append({"symbol":s,"name":n,"category":c,"price":p.get("price"),"change":p.get("change"),"currency":"USD","revenue":rev,"operatingIncome":op,"quarter":q})
 OUT.write_text(json.dumps({"updated":datetime.now(timezone.utc).isoformat(),"market":"NASDAQ/US","stocks":arr},ensure_ascii=False,indent=2),encoding="utf-8")
 print("Price values:",sum(x["price"] is not None for x in arr),"/",len(arr))
if __name__=="__main__":main()