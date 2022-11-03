from django.urls import path

from invites.views import InviteDetail, InviteList

app_name = "invites"

urlpatterns = [
    path("", InviteList.as_view()),
    path("<int:pk>/", InviteDetail.as_view()),
]
