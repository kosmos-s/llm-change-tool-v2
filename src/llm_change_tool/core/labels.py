"""One registry for UI, original JSON adapter, validation and provider output."""

import copy
import hashlib
import json
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, model_validator

RESOURCE = files("llm_change_tool").joinpath("resources")
SCHEMA_BYTES = RESOURCE.joinpath("label_schemas/label_schema_v1.json").read_bytes()
SCHEMA = json.loads(SCHEMA_BYTES)
FIELDS = SCHEMA["labels"]
KEYS = tuple(f["key"] for f in FIELDS)
SCHEMA_HASH = hashlib.sha256(SCHEMA_BYTES).hexdigest()


def canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def strict_json(raw: bytes):
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp949"
        text = raw.decode(encoding)

    def pairs(values):
        obj = {}
        for k, v in values:
            if k in obj:
                raise ValueError(f"duplicate JSON key: {k}")
            obj[k] = v
        return obj

    def invalid(value):
        raise ValueError(f"non-finite JSON: {value}")

    data = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data, encoding


def bit(value):
    if isinstance(value, bool):
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    if isinstance(value, str) and value.lower() in ("o", "x", "0", "1"):
        return int(value.lower() in ("o", "1"))
    raise ValueError(f"invalid binary label: {value!r}")


def validate_labels(labels, *, policy=True):
    if set(labels) != set(KEYS):
        raise ValueError("Label keys do not match schema")
    if any(type(v) is not int or v not in (0, 1) for v in labels.values()):
        raise ValueError("Labels must be integer 0 or 1")
    for f in FIELDS:
        if f.get("parent") and labels[f["key"]] and not labels[f["parent"]]:
            raise ValueError("Detail requires parent label")
        if policy and "fixed" in f and labels[f["key"]] != f["fixed"]:
            raise ValueError(f"Guideline excludes {f['key']}")
    return labels


def validate_draft(labels):
    """Unresolved source values and hierarchy are permitted only before DONE."""
    if set(labels) != set(KEYS):
        raise ValueError("Label keys do not match schema")
    if any(v is not None and (type(v) is not int or v not in (0, 1)) for v in labels.values()):
        raise ValueError("Draft labels must be 0, 1 or null")
    return labels


def original_labels(doc):
    result = {}
    for f in FIELDS:
        value = doc
        for key in f["path"]:
            if not isinstance(value, dict) or key not in value:
                raise ValueError(f"Missing original label: {'.'.join(f['path'])}")
            value = value[key]
        result[f["key"]] = bit(value)
    return validate_labels(result, policy=False)


def import_labels(doc):
    """Preserve unknown source values; only absent inactive details imply zero."""
    result, issues = {}, []
    for f in FIELDS:
        value = doc
        missing = False
        for key in f["path"]:
            if not isinstance(value, dict) or key not in value:
                missing = True
                break
            value = value[key]
        if missing and f.get("parent") and result.get(f["parent"]) == 0:
            result[f["key"]] = 0
            continue
        try:
            if missing:
                raise ValueError("missing label")
            result[f["key"]] = bit(value)
        except ValueError:
            result[f["key"]] = None
            issues.append(f["key"] + ": missing or invalid label")
    try:
        validate_labels(result, policy=False)
    except ValueError as exc:
        issues.append(str(exc))
    return result, issues


def effective_doc(raw: bytes, labels: dict, reason: str, reason_en: str | None = None):
    validate_labels(labels)
    doc, _ = strict_json(raw)
    doc = copy.deepcopy(doc)
    source_labels, source_issues = import_labels(doc)
    labels_changed = bool(source_issues) or source_labels != labels
    if labels_changed and not reason.strip():
        raise ValueError("라벨을 수정한 경우 최종 판단의 한국어 근거를 입력하세요.")
    # A blank confirmation of unchanged labels preserves the original explanation.
    korean = reason if reason.strip() else doc.get("reason_ko", "")
    explanation_changed = labels_changed or korean != doc.get("reason_ko", "")
    for f in FIELDS:
        parent = doc
        for key in f["path"][:-1]:
            if not isinstance(parent.get(key), dict):
                parent[key] = {}
            parent = parent[key]
        old = parent.get(f["path"][-1], 0)
        value = labels[f["key"]]
        parent[f["path"][-1]] = (
            bool(value)
            if isinstance(old, bool)
            else (value if type(old) is int else ("o" if value else "x"))
        )
    doc["reason_ko"] = korean
    # Never silently attach the source's English explanation to a different decision.
    if reason_en is not None or explanation_changed:
        doc["reason"] = reason_en or ""
        if "reason_en" in doc:
            doc["reason_en"] = reason_en or ""
    original_labels(doc)
    return doc


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    labels: dict[str, int]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=10000)
    review_required: bool

    @model_validator(mode="after")
    def valid_labels(self):
        validate_labels(self.labels)
        return self


def prompt_text():
    text = RESOURCE.joinpath("prompts/prompt_v5_guideline_20260324.txt").read_text(encoding="utf-8")
    # Keep guideline rules verbatim; replace only the transport contract.
    return text.split("반드시 아래 JSON 형식으로만 답한다.")[0] + (
        "\n응답은 labels(모든 라벨 0/1), confidence, reason(한국어), review_required만 포함한다. "
        "change/class는 출력하지 않는다. labels keys: " + ", ".join(KEYS)
    )
