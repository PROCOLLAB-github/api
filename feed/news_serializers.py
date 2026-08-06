from rest_framework import serializers

from files.serializers import UserFileSerializer
from news.models import News, NewsComment
from partner_programs.models import PartnerProgram
from projects.models import Project
from users.models import CustomUser

from feed.news_selectors import NEWS_SOURCES


class ReactNewsFeedQuerySerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=NEWS_SOURCES, default="program")
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        trim_whitespace=True,
    )


class ReactNewsSourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    image_address = serializers.URLField(allow_null=True)


class ReactNewsFeedItemSerializer(serializers.ModelSerializer[News]):
    source_type = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()
    files = UserFileSerializer(many=True)
    likes_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)
    views_count = serializers.IntegerField(read_only=True)
    is_user_liked = serializers.BooleanField(read_only=True)

    def get_source_type(self, obj: News) -> str:
        if isinstance(obj.content_object, PartnerProgram):
            return "program"
        if isinstance(obj.content_object, Project):
            return "project"
        return "user"

    def get_source(self, obj: News) -> dict:
        source = obj.content_object
        if isinstance(source, CustomUser):
            name = f"{source.first_name} {source.last_name}".strip()
            image_address = source.avatar
        else:
            name = source.name
            image_address = source.image_address
        return ReactNewsSourceSerializer(
            {
                "id": source.pk,
                "name": name,
                "image_address": image_address,
            }
        ).data

    class Meta:
        model = News
        fields = (
            "id",
            "source_type",
            "source",
            "text",
            "files",
            "audience",
            "datetime_created",
            "datetime_updated",
            "likes_count",
            "comments_count",
            "views_count",
            "is_user_liked",
        )


class SetReactNewsLikedSerializer(serializers.Serializer):
    is_liked = serializers.BooleanField()


class NewsCommentInputSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=2000,
        allow_blank=False,
        trim_whitespace=True,
    )


class NewsCommentAuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    image_address = serializers.URLField(allow_null=True)


class NewsCommentResponseSerializer(serializers.ModelSerializer[NewsComment]):
    author = serializers.SerializerMethodField()
    datetime_updated = serializers.SerializerMethodField()
    is_edited = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    def get_author(self, obj: NewsComment) -> dict:
        return NewsCommentAuthorSerializer(
            {
                "id": obj.author_id,
                "name": f"{obj.author.first_name} {obj.author.last_name}".strip(),
                "image_address": obj.author.avatar,
            }
        ).data

    def get_datetime_updated(self, obj: NewsComment):
        return obj.datetime_updated or obj.datetime_created

    def get_is_edited(self, obj: NewsComment) -> bool:
        return obj.datetime_updated is not None

    def get_can_edit(self, obj: NewsComment) -> bool:
        request = self.context["request"]
        return obj.author_id == request.user.pk

    def get_can_delete(self, obj: NewsComment) -> bool:
        request = self.context["request"]
        return bool(
            obj.author_id == request.user.pk
            or request.user.is_staff
            or request.user.is_superuser
        )

    class Meta:
        model = NewsComment
        fields = (
            "id",
            "author",
            "text",
            "datetime_created",
            "datetime_updated",
            "is_edited",
            "can_edit",
            "can_delete",
        )
