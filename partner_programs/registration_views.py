from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from collections.abc import Mapping

from partner_programs.management_views import ManagementBase
from partner_programs.serializers.management import StrictFieldsMixin, HttpURLField
from partner_programs.services.management import managed_program
from partner_programs.services import native_registration as service
from project_rates.workspace_views import PrivateView
from users.models import CustomUser


class RegistrationInput(StrictFieldsMixin, serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {"non_field_errors": ["Отправьте объект с полями формы."]}
            )
        return super().to_internal_value(data)


class RegistrationWrite(RegistrationInput):
    revision = serializers.IntegerField(min_value=0)
    draft = serializers.JSONField()


class EnrollmentWrite(RegistrationInput):
    version = serializers.IntegerField(min_value=1)
    answers = serializers.JSONField()


class SignupWrite(EnrollmentWrite):
    first_name = serializers.CharField(
        max_length=255, validators=CustomUser._meta.get_field("first_name").validators
    )
    last_name = serializers.CharField(
        max_length=255, validators=CustomUser._meta.get_field("last_name").validators
    )
    birthday = serializers.DateField(
        validators=CustomUser._meta.get_field("birthday").validators
    )
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(min_length=8, max_length=128, trim_whitespace=False)
    repeat_password = serializers.CharField(max_length=128, trim_whitespace=False)
    accept_policy = serializers.BooleanField()
    accept_age = serializers.BooleanField()

    def validate(self, data):
        if not data["accept_policy"]:
            raise serializers.ValidationError(
                {"accept_policy": "Подтвердите согласие с условиями платформы."}
            )
        if (
            not data["accept_age"]
            or (timezone.now().date() - data["birthday"]).days < 14 * 365
        ):
            raise serializers.ValidationError(
                {"birthday": "Для регистрации участнику должно быть не менее 14 лет."}
            )
        if data["password"] != data["repeat_password"]:
            raise serializers.ValidationError({"repeat_password": "Пароли не совпадают."})
        try:
            validate_password(
                data["password"],
                CustomUser(
                    email=data["email"],
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                ),
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": error.messages})
        return data


class TokenWrite(RegistrationInput):
    token = serializers.CharField(max_length=2000)


def validated(cls, data):
    form = cls(data=data)
    form.is_valid(raise_exception=True)
    return form.validated_data


class RegistrationSettingsView(ManagementBase):
    def get(self, request, pk):
        return Response(service.settings_data(managed_program(pk, request.user)))

    def put(self, request, pk):
        return Response(
            service.save_settings(
                pk, request.user, validated(RegistrationWrite, request.data)
            )
        )


class RegistrationPublishView(ManagementBase):
    def post(self, request, pk):
        return Response(
            service.save_settings(
                pk, request.user, validated(RegistrationWrite, request.data), publish=True
            )
        )


class RegistrationImportView(ManagementBase):
    def post(self, request, pk):
        managed_program(pk, request.user)
        upload = request.FILES.get("file")
        if not upload:
            raise serializers.ValidationError({"file": "Выберите XLSX/CSV файл."})
        return Response(service.import_options(upload))


class ConnectionWrite(RegistrationInput):
    url = HttpURLField(max_length=200)
    comment = serializers.CharField(
        max_length=2000, allow_blank=True, required=False, default=""
    )
    contact = serializers.CharField(
        max_length=500, allow_blank=True, required=False, default=""
    )


class RegistrationConnectionView(ManagementBase):
    def post(self, request, pk):
        data = validated(ConnectionWrite, request.data)
        return Response(service.request_connection(pk, request.user, data))


class RegistrationThrottle(AnonRateThrottle):
    rate = "12/min"
    scope = "program_registration"


class OptionalRegistrationAuthentication(JWTAuthentication):
    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except (InvalidToken, AuthenticationFailed):
            return None


class PublicRegistrationView(PrivateView):
    permission_classes = [AllowAny]
    authentication_classes = [OptionalRegistrationAuthentication]
    throttle_classes = [RegistrationThrottle]

    def get(self, request, pk):
        return Response(service.public_data(service.open_program(pk), request.user))

    def post(self, request, pk):
        return Response(
            service.enroll(pk, request.user, validated(EnrollmentWrite, request.data))
        )


class PublicRegistrationActionView(PublicRegistrationView):
    def get(self, request, pk, action):
        return Response(status=405)

    def post(self, request, pk, action):
        if action == "signup":
            if request.user.is_authenticated:
                raise serializers.ValidationError(
                    "Для своего аккаунта отправьте только анкету."
                )
            return Response(
                service.signup(pk, validated(SignupWrite, request.data)), status=201
            )
        if action in ("confirm", "resend"):
            data = validated(TokenWrite, request.data)
            return Response(getattr(service, action)(pk, data["token"]))
        return Response(status=404)
