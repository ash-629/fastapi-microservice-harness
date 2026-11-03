from uuid import uuid4
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from inventory_service.main import create_app


def test_real_responses_match_schema(tmp_path):
    app = create_app(tmp_path / "db")
    schema = app.openapi()
    with TestClient(app) as client:
        response = client.get("/api/v1/products")
        model = schema["paths"]["/api/v1/products"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        Draft202012Validator({**model, "components": schema["components"]}).validate(
            response.json()
        )
        invalid = client.put(
            "/internal/v1/reservations/" + str(uuid4()), json={"product_id": "x", "quantity": 0}
        )
        Draft202012Validator(
            {"$ref": "#/components/schemas/Error", "components": schema["components"]}
        ).validate(invalid.json())
