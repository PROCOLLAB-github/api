from rest_framework import serializers


def serialize_response(
    serializer_class: type[serializers.Serializer],
    payload,
    *,
    many: bool = False,
):
    serializer = serializer_class(data=payload, many=many)
    serializer.is_valid(raise_exception=True)
    return serializer.data
