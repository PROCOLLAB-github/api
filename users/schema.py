from drf_yasg import openapi


USER_PK_PARAM = openapi.Parameter(
    "user_pk",
    openapi.IN_PATH,
    description="Id user to confirmed",
    type=openapi.TYPE_INTEGER
)

SKILL_PK_PARAM = openapi.Parameter(
    "skill_pk",
    openapi.IN_PATH,
    description="Id skill user to confirmed",
    type=openapi.TYPE_INTEGER
)
