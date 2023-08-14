from django.urls import path

from news.views import NewsList, NewsDetail, NewsDetailSetViewed, NewsDetailSetLiked
from partner_programs.views import (
    PartnerProgramList,
    PartnerProgramDetail,
    PartnerProgramCreateUserAndRegister,
    PartnerProgramRegister,
    PartnerProgramDataSchema,
    PartnerProgramSetLiked,
    PartnerProgramSetViewed,
)

app_name = "partner_programs"

urlpatterns = [
    path("", PartnerProgramList.as_view()),
    path("<int:pk>/", PartnerProgramDetail.as_view()),
    path("<int:pk>/schema/", PartnerProgramDataSchema.as_view()),
    path("<int:pk>/register/", PartnerProgramRegister.as_view()),
    path("<int:pk>/register_new/", PartnerProgramCreateUserAndRegister.as_view()),
    path("<int:pk>/set_liked/", PartnerProgramSetLiked.as_view()),
    path("<int:pk>/set_viewed/", PartnerProgramSetViewed.as_view()),
    path("<int:partnerprogram_pk>/news/", NewsList.as_view()),
    path("<int:partnerprogram_pk>/news/<int:pk>/", NewsDetail.as_view()),
    path(
        "<int:partnerprogram_pk>/news/<int:pk>/set_viewed/", NewsDetailSetViewed.as_view()
    ),
    path(
        "<int:partnerprogram_pk>/news/<int:pk>/set_liked/", NewsDetailSetLiked.as_view()
    ),
]
