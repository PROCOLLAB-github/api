"""Read questionnaire answers without modifying legacy data or schema snapshots."""


def _schema_labels(schema):
    fields = schema.get("fields") if isinstance(schema, dict) else None
    if not isinstance(fields, list):
        return {}
    labels = {}
    for field in fields:
        if isinstance(field, dict):
            key, label = field.get("id"), field.get("label")
            if isinstance(key, str) and isinstance(label, str) and label.strip():
                labels.setdefault(key, label)
    return labels


def registration_answer_rows(snapshot, answers, *, legacy=None, published=None):
    """Keep snapshot order, and use fallback labels only for stored answers."""
    labels = _schema_labels(snapshot)
    stored_answers = answers if isinstance(answers, dict) else {}
    for key, label in labels.items():
        yield {"key": key, "label": label, "value": stored_answers.get(key)}

    legacy = legacy if isinstance(legacy, dict) else {}
    published_labels = _schema_labels(published)
    for key, value in stored_answers.items():
        if key in labels:
            continue
        field = legacy.get(key)
        legacy_label = field.get("name") if isinstance(field, dict) else None
        if not isinstance(legacy_label, str) or not legacy_label.strip():
            legacy_label = None
        yield {
            "key": key,
            "label": published_labels.get(key) or legacy_label,
            "value": value,
        }

    if answers is not None and not isinstance(answers, dict):
        yield {"key": None, "label": None, "value": answers}
