from app.schemas.common import ORMModel


class Token(ORMModel):
    access_token: str
    token_type: str = "bearer"
