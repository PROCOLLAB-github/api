from django.urls import path

from partner_programs.views import (
    PartnerProgramList,
    PartnerProgramDetail,
    PartnerProgramCreateUserAndRegister,
    PartnerProgramRegister,
)

app_name = "partner_programs"

urlpatterns = [
    path("", PartnerProgramList.as_view()),
    path("<int:pk>/", PartnerProgramDetail.as_view()),
    path("<int:pk>/register/", PartnerProgramRegister.as_view()),
    path("<int:pk>/register_new/", PartnerProgramCreateUserAndRegister.as_view()),
]
