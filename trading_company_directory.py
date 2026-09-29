"""Cached SEC company-name directory for the Trading Division selector."""
import time
import httpx
from fastapi import HTTPException, Request
_CACHE={"at":0,"items":[]}

def install(app,auth):
    @app.get("/api/trading/company-directory")
    async def company_directory(req:Request):
        auth(req)
        import os
        ua=os.getenv("SEC_USER_AGENT")
        if not ua:
            return {"items":[],"coverage":"US SEC company-ticker directory; SEC_USER_AGENT not configured","status":"not_configured"}
        if time.time()-_CACHE["at"]>86400 or not _CACHE["items"]:
            try:
                async with httpx.AsyncClient(timeout=18,headers={"User-Agent":ua,"Accept":"application/json"}) as client:
                    response=await client.get("https://www.sec.gov/files/company_tickers.json")
                    response.raise_for_status()
                    data=response.json()
                rows=[{"name":str(x["title"]),"symbol":str(x["ticker"]).upper()} for x in data.values() if x.get("title") and x.get("ticker")]
                _CACHE.update(at=time.time(),items=sorted(rows,key=lambda x:(x["name"].casefold(),x["symbol"])))
            except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
                if not _CACHE["items"]:
                    return {"items":[],"coverage":"US SEC company-ticker directory","status":"unavailable","error":type(exc).__name__}
        return {"items":_CACHE["items"],"coverage":"US SEC company-ticker directory; not all global exchanges, not all private startups; listing/trading status not verified","status":"ok","cached_at_epoch":_CACHE["at"]}
