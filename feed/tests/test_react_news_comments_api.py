from django.test import TestCase
from rest_framework.test import APIClient

from news.models import News, NewsComment
from notifications.models import Notification
from news.tests.helpers import (
    create_news_for,
    create_partner_program,
    create_user,
)
from partner_programs.models import PartnerProgramUserProfile


class ReactNewsCommentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = create_user(prefix="comment-author")
        self.other_user = create_user(prefix="comment-other")
        self.admin = create_user(prefix="comment-admin")
        self.admin.is_staff = True
        self.admin.save(update_fields=["is_staff"])
        self.program = create_partner_program(name="Comment program")
        self.news = create_news_for(self.program, text="Commented post")
        self.list_url = f"/feed/news/{self.news.pk}/comments/"
        self.client.force_authenticate(self.author)

    def detail_url(self, comment: NewsComment, news: News | None = None) -> str:
        return f"/feed/news/{(news or self.news).pk}/comments/{comment.pk}/"

    def test_user_can_create_and_read_comments_oldest_first(self):
        self.program.managers.add(self.other_user)
        first_response = self.client.post(
            self.list_url,
            {"text": "  First comment  "},
            format="json",
        )
        second_response = self.client.post(
            self.list_url,
            {"text": "Second comment"},
            format="json",
        )
        list_response = self.client.get(self.list_url)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(first_response.data["text"], "First comment")
        self.assertFalse(first_response.data["is_edited"])
        self.assertTrue(first_response.data["can_edit"])
        self.assertTrue(first_response.data["can_delete"])
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 2)
        self.assertEqual(
            [item["id"] for item in list_response.data["results"]],
            [first_response.data["id"], second_response.data["id"]],
        )
        self.assertEqual(
            Notification.objects.filter(
                recipient=self.other_user,
                type=Notification.Type.NEWS_COMMENT_CREATED,
            ).count(),
            2,
        )

    def test_author_can_edit_comment_and_user_input_is_preserved(self):
        comment = NewsComment.objects.create(
            news=self.news,
            author=self.author,
            text="Before edit",
        )

        response = self.client.patch(
            self.detail_url(comment),
            {"text": "  After edit  "},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["text"], "After edit")
        self.assertTrue(response.data["is_edited"])
        self.assertNotEqual(
            response.data["datetime_created"],
            response.data["datetime_updated"],
        )

    def test_user_cannot_edit_another_authors_comment(self):
        comment = NewsComment.objects.create(
            news=self.news,
            author=self.other_user,
            text="Other comment",
        )

        response = self.client.patch(
            self.detail_url(comment),
            {"text": "Forbidden edit"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Other comment")

    def test_author_and_admin_can_delete_comment(self):
        author_comment = NewsComment.objects.create(
            news=self.news,
            author=self.author,
            text="Author delete",
        )
        admin_comment = NewsComment.objects.create(
            news=self.news,
            author=self.other_user,
            text="Admin delete",
        )

        author_response = self.client.delete(self.detail_url(author_comment))
        self.client.force_authenticate(self.admin)
        admin_response = self.client.delete(self.detail_url(admin_comment))

        self.assertEqual(author_response.status_code, 204)
        self.assertEqual(admin_response.status_code, 204)
        self.assertFalse(
            NewsComment.objects.filter(
                pk__in=(author_comment.pk, admin_comment.pk)
            ).exists()
        )

    def test_user_cannot_delete_another_authors_comment(self):
        comment = NewsComment.objects.create(
            news=self.news,
            author=self.other_user,
            text="Protected comment",
        )

        response = self.client.delete(self.detail_url(comment))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(NewsComment.objects.filter(pk=comment.pk).exists())

    def test_blank_and_too_long_comments_are_rejected(self):
        blank = self.client.post(
            self.list_url,
            {"text": "   "},
            format="json",
        )
        too_long = self.client.post(
            self.list_url,
            {"text": "x" * 2001},
            format="json",
        )

        self.assertEqual(blank.status_code, 400)
        self.assertIn("text", blank.data)
        self.assertEqual(too_long.status_code, 400)
        self.assertIn("text", too_long.data)
        self.assertFalse(NewsComment.objects.filter(news=self.news).exists())

    def test_comment_id_cannot_be_used_through_another_news(self):
        other_news = create_news_for(self.program, text="Other post")
        comment = NewsComment.objects.create(
            news=self.news,
            author=self.author,
            text="Scoped comment",
        )

        patch_response = self.client.patch(
            self.detail_url(comment, news=other_news),
            {"text": "Wrong scope"},
            format="json",
        )
        delete_response = self.client.delete(self.detail_url(comment, news=other_news))

        self.assertEqual(patch_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        self.assertTrue(NewsComment.objects.filter(pk=comment.pk).exists())

    def test_inaccessible_participant_news_restricts_comments(self):
        internal_news = create_news_for(
            self.program,
            text="Internal comments",
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )
        internal_url = f"/feed/news/{internal_news.pk}/comments/"

        forbidden_list = self.client.get(internal_url)
        forbidden_create = self.client.post(
            internal_url,
            {"text": "Forbidden comment"},
            format="json",
        )
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program,
            user=self.author,
            partner_program_data={},
        )
        allowed_create = self.client.post(
            internal_url,
            {"text": "Participant comment"},
            format="json",
        )

        self.assertEqual(forbidden_list.status_code, 404)
        self.assertEqual(forbidden_create.status_code, 404)
        self.assertEqual(allowed_create.status_code, 201)

    def test_comments_count_tracks_create_and_delete(self):
        created = self.client.post(
            self.list_url,
            {"text": "Counted comment"},
            format="json",
        )

        after_create = self.client.get(f"/feed/news/{self.news.pk}/")
        self.client.delete(f"/feed/news/{self.news.pk}/comments/{created.data['id']}/")
        after_delete = self.client.get(f"/feed/news/{self.news.pk}/")

        self.assertEqual(after_create.data["comments_count"], 1)
        self.assertEqual(after_delete.data["comments_count"], 0)

    def test_deleting_news_cascades_comments(self):
        comment = NewsComment.objects.create(
            news=self.news,
            author=self.author,
            text="Cascade comment",
        )

        self.news.delete()

        self.assertFalse(NewsComment.objects.filter(pk=comment.pk).exists())
