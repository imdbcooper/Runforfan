import unittest
from types import SimpleNamespace

try:
    from fastapi import Body, Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, Field

    from app.api.errors import add_exception_handlers
    from app.api.routes import activities as activities_routes
    from app.services import auth as auth_service
except ModuleNotFoundError as exc:
    if exc.name in {"fastapi", "httpx", "pydantic", "pydantic_core", "sqlalchemy", "starlette"}:
        raise unittest.SkipTest("Backend dependencies are required for API error tests") from exc
    raise


class Payload(BaseModel):
    value: int = Field(ge=1)


class FakeDb:
    def scalar(self, _query):
        return None


def override_db():
    yield FakeDb()


class CapturingDb:
    def __init__(self):
        self.query = None

    def scalar(self, query):
        self.query = query
        return None


class ApiErrorTests(unittest.TestCase):
    def make_client(self) -> TestClient:
        app = FastAPI()
        add_exception_handlers(app)

        @app.get("/missing")
        def missing():
            raise HTTPException(status_code=404, detail="Missing resource")

        @app.post("/payload")
        def payload(_payload: Payload = Body(...)):
            return {"ok": True}

        @app.get("/protected")
        def protected(_user=Depends(auth_service.get_current_user)):
            return {"ok": True}

        app.dependency_overrides[auth_service.get_db] = override_db
        return TestClient(app)

    def test_http_exception_uses_api_error_envelope(self):
        response = self.make_client().get("/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Missing resource", "details": None})

    def test_validation_error_uses_api_error_envelope(self):
        response = self.make_client().post("/payload", json={"value": 0})

        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["code"], "validation_error")
        self.assertEqual(body["message"], "Request validation failed")
        self.assertIsInstance(body["details"], list)

    def test_auth_error_uses_api_error_envelope(self):
        response = self.make_client().get("/protected")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"code": "unauthorized", "message": "Bearer token required", "details": None})

    def test_invalid_token_error_uses_api_error_envelope(self):
        response = self.make_client().get("/protected", headers={"Authorization": "Bearer invalid"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"code": "unauthorized", "message": "Invalid token", "details": None})

    def test_activity_lookup_is_user_scoped_and_returns_error_envelope(self):
        app = FastAPI()
        add_exception_handlers(app)
        app.include_router(activities_routes.router, prefix="/api")
        db = CapturingDb()

        def override_activity_db():
            yield db

        app.dependency_overrides[activities_routes.get_current_user] = lambda: SimpleNamespace(id=42)
        app.dependency_overrides[activities_routes.get_db] = override_activity_db

        response = TestClient(app).get("/api/activities/7")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found", "message": "Activity not found", "details": None})
        compiled_query = str(db.query.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("activities.id = 7", compiled_query)
        self.assertIn("activities.user_id = 42", compiled_query)


if __name__ == "__main__":
    unittest.main()
