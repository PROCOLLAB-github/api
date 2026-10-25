"""Validate the C00 document and independent mock scenarios, not a running API."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec

ROOT = Path(__file__).resolve().parent
spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
examples = json.loads((ROOT / "examples.json").read_text(encoding="utf-8"))
validate_spec(spec)
schemas = spec["components"]["schemas"]
for schema in schemas.values():
    Draft202012Validator.check_schema(schema)


def check(value, schema):
    wrapper = {"components": spec["components"], **schema}
    Draft202012Validator(wrapper, format_checker=FormatChecker()).validate(value)


operations = {}
for path, item in spec["paths"].items():
    for method, operation in item.items():
        key = operation["operationId"]
        assert key not in operations, key
        operations[key] = operation

names = set()
covered = set()
for scenario in examples["scenarios"]:
    name = scenario["name"]
    assert name not in names, name
    names.add(name)
    operation = operations[scenario["operation_id"]]
    covered.add(scenario["operation_id"])
    if "request" in scenario:
        content = operation["requestBody"]["content"]["application/json"]
        check(scenario["request"], content["schema"])
    response = operation["responses"][str(scenario["status"])]
    if scenario["status"] == 204:
        assert "response" not in scenario, name
    else:
        check(scenario["response"], response["content"]["application/json"]["schema"])
    payload = scenario.get("response", {})
    if "team" in payload and "form" in payload and "submission" in payload:
        team = payload["team"]
        user_ids = [member["user"]["id"] for member in team["members"]]
        assert len(user_ids) == len(set(user_ids)) == team["accepted_count"], name
        captains = [m["user"]["id"] for m in team["members"] if m["is_captain"]]
        assert captains == [payload["captain_id"]], name
        assert (
            team["reserved_count"] == team["accepted_count"] + team["pending_count"]
        ), name
        fields = {field["id"]: field for field in payload["form"]["fields"]}
        assert len(fields) == len(payload["form"]["fields"]), name
        assert payload["form"]["program_id"] == payload["program_id"], name
        ids = [a["field_id"] for a in payload["answers"]]
        assert len(ids) == len(set(ids)), name
        for answer in payload["answers"]:
            field = fields[answer["field_id"]]
            val = answer["value"]
            field_type = field["type"]
            assert (
                isinstance(val, str)
                if field_type in ("text", "textarea", "url", "select", "radio")
                else isinstance(val, bool)
                if field_type == "checkbox"
                else type(val) in (int, float)
                if field_type == "number"
                else isinstance(val, dict) and set(val) == {"url"}
            ), name
            if field_type in ("select", "radio"):
                assert val in field["options"], name
        if payload["submission"]["status"] == "submitted":
            assert team["is_frozen"] and payload["form"]["is_snapshot"], name
            assert payload["submission"]["submitted_at"] is not None, name
            assert not any(payload["permissions"].values()), name
        if payload["readiness"] and payload["readiness"]["is_ready"]:
            answered = {a["field_id"] for a in payload["answers"]}
            assert {f["id"] for f in fields.values() if f["required"]} <= answered, name
            assert (
                team["min_size"] is None or team["accepted_count"] >= team["min_size"]
            ), name
    if "published_at" in payload and "fields" in payload:
        team = payload["team"]
        ids = [row["user"]["id"] for row in team["members"]]
        assert len(set(ids)) == len(ids) == team["accepted_count"], name
        assert sum(row["is_captain"] for row in team["members"]) == 1, name
        fields = {field["id"] for field in payload["fields"]}
        answers = [answer["field_id"] for answer in payload["answers"]]
        assert len(set(answers)) == len(answers) and set(answers) <= fields, name
assert covered == set(operations), (
    "Operations missing examples",
    sorted(set(operations) - covered),
)
print(  # noqa: T201 (CLI report)
    f"PASS: OpenAPI; {len(schemas)} schemas; {len(operations)} operations; {len(names)} scenarios"
)
