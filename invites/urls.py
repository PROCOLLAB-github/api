from django.urls import path

from invites.views import InviteDetail, InviteList, InviteAccept, InviteDecline

app_name = "invites"

urlpatterns = [
    path("", InviteList.as_view()),
    path("<int:pk>/", InviteDetail.as_view()),
    path("<int:pk>/accept/", InviteAccept.as_view()),
    path("<int:pk>/decline/", InviteDecline.as_view()),
]
