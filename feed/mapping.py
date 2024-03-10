from partner_programs.serializers import PartnerProgramListSerializer
from projects.models import Project
from projects.serializers import ProjectListSerializer
from users.models import CustomUser
from users.serializers import UserFeedSerializer
from vacancy.models import Vacancy
from vacancy.serializers import VacancyDetailSerializer

CONTENT_OBJECT_MAPPING: dict[str, str | None] = {
    Project.__name__.lower(): "project",
    CustomUser.__name__.lower(): "news",
    "partnerprogram": None,
    Vacancy.__name__.lower(): "vacancy",
}

CONTENT_OBJECT_SERIALIZER_MAPPING: dict = {
    Project.__name__.lower(): ProjectListSerializer,
    CustomUser.__name__.lower(): UserFeedSerializer,
    "partnerprogram": PartnerProgramListSerializer,
    Vacancy.__name__.lower(): VacancyDetailSerializer,
}
