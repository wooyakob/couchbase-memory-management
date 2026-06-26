from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter(prefix="/api/cluster", tags=["cluster"])


class ClusterProxyRequest(BaseModel):
    endpoint: str
    api_key: str
    model: str = ""
    prompt: str


@router.post("")
async def cluster_proxy(req: ClusterProxyRequest):
    url = req.endpoint.rstrip("/") + "/v1/chat/completions"
    payload = {
        "messages": [{"role": "user", "content": req.prompt}],
        "max_tokens": 1024,
        "stream": False,
    }
    if req.model:
        payload["model"] = req.model

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            res = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {req.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Could not reach Capella endpoint: {e}")

    try:
        data = res.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=f"Non-JSON response from Capella (HTTP {res.status_code})",
        )

    if not res.is_success:
        msg = (
            data.get("error", {}).get("message")
            or data.get("message")
            or f"Capella Model Service error (HTTP {res.status_code})"
        )
        raise HTTPException(status_code=res.status_code, detail=msg)

    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if not text:
        raise HTTPException(status_code=502, detail="Capella returned an empty response")

    return {"text": text}
