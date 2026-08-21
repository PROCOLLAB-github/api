from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory

from files.models import UserFile
from files.typings import FileInfo
from news.models import News
from news.serializers import NewsCreateSerializer

from .helpers import create_partner_program, create_project, create_user


NEWS_IMAGE_LINK = "https://api.selcdn.ru/test/news-image.png"


class NewsAttachmentContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_project_news_accepts_current_user_file_link(self):
        user = create_user(prefix="project-news-attachment-owner")
        project = create_project(leader=user)
        user_file = self.create_user_file(user)
        self.client.force_authenticate(user)

        response = self.client.post(
            f"/projects/{project.id}/news/",
            {
                "text": "News with image",
                "files": [NEWS_IMAGE_LINK],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(list(news.files.all()), [user_file])

    def test_news_serializer_accepts_current_user_file_link(self):
        user = create_user(prefix="serializer-news-attachment-owner")
        user_file = self.create_user_file(user)
        request = APIRequestFactory().post(
            "/projects/1/news/",
            {
                "text": "News with image",
                "files": [NEWS_IMAGE_LINK],
            },
            format="json",
        )
        request.user = user

        serializer = NewsCreateSerializer(
            data={
                "text": "News with image",
                "files": [NEWS_IMAGE_LINK],
            },
            context={
                "request": request,
                "news_context": "project",
            },
        )

        self.assertTrue(UserFile.objects.filter(user=user, link=NEWS_IMAGE_LINK).exists())
        self.assertEqual(UserFile.objects.get(pk=NEWS_IMAGE_LINK), user_file)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["files"], [user_file])

    def test_user_news_accepts_current_user_file_link(self):
        user = create_user(prefix="user-news-attachment-owner")
        user_file = self.create_user_file(user)
        self.client.force_authenticate(user)

        response = self.client.post(
            f"/auth/users/{user.id}/news/",
            {
                "text": "News with image",
                "files": [NEWS_IMAGE_LINK],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(list(news.files.all()), [user_file])

    def test_program_news_accepts_current_user_file_link(self):
        user = create_user(prefix="program-news-attachment-owner")
        program = create_partner_program(manager=user)
        user_file = self.create_user_file(user)
        self.client.force_authenticate(user)

        response = self.client.post(
            f"/programs/{program.id}/news/",
            {
                "text": "News with image",
                "files": [NEWS_IMAGE_LINK],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(list(news.files.all()), [user_file])

    def test_uploaded_file_link_can_be_attached_to_project_news(self):
        user = create_user(prefix="project-news-upload-flow-owner")
        project = create_project(leader=user)
        self.client.force_authenticate(user)
        uploaded_file = SimpleUploadedFile(
            "news-image.png",
            b"image-content",
            content_type="image/png",
        )

        with patch(
            "files.views.FileView.cdn.upload",
            return_value=FileInfo(
                url=NEWS_IMAGE_LINK,
                size=len(b"image-content"),
                name="news-image",
                extension="png",
                mime_type="image/png",
            ),
        ):
            upload_response = self.client.post(
                "/files/",
                {"file": uploaded_file},
                format="multipart",
            )

        self.assertEqual(upload_response.status_code, 201)
        url = upload_response.data["url"]
        user_file = UserFile.objects.get(link=url)
        self.assertEqual(upload_response.data["url"], user_file.link)
        self.assertEqual(user_file.user, user)

        news_response = self.client.post(
            f"/projects/{project.id}/news/",
            {
                "text": "News with image",
                "files": [url],
            },
            format="json",
        )

        self.assertEqual(news_response.status_code, 201, news_response.data)
        news = News.objects.get(pk=news_response.data["id"])
        self.assertEqual(list(news.files.all()), [user_file])

    @staticmethod
    def create_user_file(user):
        return UserFile.objects.create(
            user=user,
            link=NEWS_IMAGE_LINK,
            name="news-image",
            extension="png",
            mime_type="image/png",
            size=1024,
        )
