from fastapi import Header, HTTPException
from config import settings

# 看请求头里有没有X-API-Key，没有就返回401
async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != settings.app_api_key:
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key")
    return x_api_key