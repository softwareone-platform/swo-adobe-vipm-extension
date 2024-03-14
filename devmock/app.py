import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from devmock.endpoints import router
from devmock.exceptions import DevmockException

app = FastAPI(
    title="SoftwareOne Marketplace platform - Devmock",
)

@app.post("/oauth/token")
def authentication():
    return {
        "token_type": "Fake",
        "access_token": secrets.token_hex(16),
    }


app.include_router(router, prefix="/v1")




@app.exception_handler(DevmockException)
async def custom_exception_handler(request: Request, exc: DevmockException):
    return JSONResponse(
        exc.to_dict(),
        status_code=exc.status_code,
    )
