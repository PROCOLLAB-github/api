from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.forms.models import model_to_dict
from rest_framework import serializers
from django.core.cache import cache

from core.serializers import SkillToObjectSerializer
from core.models import SpecializationCategory, Specialization, Skill, SkillToObject
from core.services import get_views_count
from core.utils import get_user_online_cache_key
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from projects.models import Project, Collaborator
from projects.validators import validate_project
from users.validators import specialization_exists_validator
from users.models import (
    CustomUser,
    Expert,
    Investor,
    Member,
    Mentor,
    UserAchievement,
    UserEducation,
    UserSkillConfirmation,
)

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class AchievementListSerializer(serializers.ModelSerializer[UserAchievement]):
    class Meta:
        model = UserAchievement
        fields = ["id", "title", "status"]
        ref_name = "Users"


class CustomListField(serializers.ListField):
    # костыль
    def to_representation(self, data):
        if isinstance(data, list):
            return data
        return [
            i.replace("'", "") for i in data.strip("][").split(",") if i.replace("'", "")
        ]


class MemberSerializer(serializers.ModelSerializer[Member]):
    class Meta:
        model = Member
        fields = [
            "useful_to_project",
        ]


class MentorSerializer(serializers.ModelSerializer[Mentor]):
    preferred_industries = CustomListField(
        child=serializers.CharField(max_length=255),
    )

    class Meta:
        model = Mentor
        fields = [
            "preferred_industries",
            "useful_to_project",
        ]


class ExpertSerializer(serializers.ModelSerializer[Expert]):
    preferred_industries = CustomListField(
        child=serializers.CharField(max_length=255),
    )

    class Meta:
        model = Expert
        fields = [
            "preferred_industries",
            "useful_to_project",
        ]


class InvestorSerializer(serializers.ModelSerializer[Investor]):
    preferred_industries = CustomListField(child=serializers.CharField(max_length=255))

    class Meta:
        model = Investor
        fields = [
            "interaction_process_description",
            "preferred_industries",
        ]


class SpecializationSerializer(serializers.ModelSerializer[Specialization]):
    class Meta:
        model = SpecializationCategory
        fields = [
            "id",
            "name",
        ]


class UserDataConfirmationSerializer(serializers.ModelSerializer):
    """Information about the User to add to the skill confirmation information."""
    v2_speciality = SpecializationSerializer()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "speciality",
            "v2_speciality",
            "avatar",
        ]


class UserSkillConfirmationSerializer(serializers.ModelSerializer):
    """Represents a work that requires approval of the user's skills."""

    class Meta:
        model = UserSkillConfirmation
        fields = [
            "skill_to_object",
            "confirmed_by",
        ]
        extra_kwargs = {
            "skill_to_object": {"write_only": True},
        }

    def validate(self, attrs):
        """User cant approve own skills."""
        skill_to_object = attrs.get("skill_to_object")
        confirmed_by = self.context["request"].user

        if skill_to_object.content_object == confirmed_by:
            raise serializers.ValidationError("User cant approve own skills.")

        return attrs

    def to_representation(self, instance):
        """Returns correct data about user in `confirmed_by`."""
        data = super().to_representation(instance)
        data.pop("skill_to_object", None)
        data["confirmed_by"] = UserDataConfirmationSerializer(instance.confirmed_by).data
        return data


class UserApproveSkillResponse(serializers.Serializer):
    """For swagger response presentation."""
    confirmed_by = UserDataConfirmationSerializer(read_only=True)


class UserSkillsWithApprovesSerializer(SkillToObjectSerializer):
    """Added field `approves` to response about User skills."""

    approves = serializers.SerializerMethodField(allow_null=True, read_only=True)

    class Meta:
        model = SkillToObject
        fields = [
            "id",
            "name",
            "category",
            "approves",
        ]

    def get_approves(self, obj):
        """Adds information about confirm to the skill."""
        confirmations = (
            UserSkillConfirmation.objects
            .filter(skill_to_object=obj)
            .select_related('confirmed_by')
        )
        return [
            {
                "confirmed_by": UserDataConfirmationSerializer(confirmation.confirmed_by).data,
            }
            for confirmation in confirmations
        ]


class SpecializationsSerializer(serializers.ModelSerializer[SpecializationCategory]):
    specializations = SpecializationSerializer(many=True)

    class Meta:
        model = SpecializationCategory
        fields = ["id", "name", "specializations"]


class SkillsSerializerMixin(serializers.Serializer):
    skills = UserSkillsWithApprovesSerializer(many=True, read_only=True)


class SkillsWriteSerializerMixin(SkillsSerializerMixin):
    skills_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )


class UserProjectsSerializer(serializers.ModelSerializer[Project]):
    short_description = serializers.SerializerMethodField()
    views_count = serializers.SerializerMethodField()
    collaborator = serializers.SerializerMethodField(method_name="get_collaborator")

    def get_collaborator(self, project: Project):
        # TODO: fix me, import in a functon
        from projects.serializers import CollaboratorSerializer

        user = (
            self.context.get("request").user
            if self.context.get("user") is None
            else self.context.get("user")
        )
        try:
            collaborator = project.collaborator_set.get(user=user)
        except Collaborator.DoesNotExist:
            return {}

        return CollaboratorSerializer(collaborator).data

    @classmethod
    def get_views_count(cls, project):
        return get_views_count(project)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "short_description",
            "image_address",
            "industry",
            "views_count",
            "collaborator",
            "is_company",
        ]
        read_only_fields = ["leader", "collaborator", "is_company"]


class UserSubscribedProjectsSerializer(serializers.ModelSerializer[Project]):
    short_description = serializers.SerializerMethodField()
    views_count = serializers.SerializerMethodField()

    @classmethod
    def get_views_count(cls, project):
        return get_views_count(project)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "short_description",
            "image_address",
            "industry",
            "views_count",
            "is_company",
        ]
        read_only_fields = ["leader", "collaborator", "is_company"]


class SubscriptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.IntegerField()
    features_list = serializers.ListField(child=serializers.CharField())


class UserSubscriptionDataSerializer(serializers.Serializer):
    is_subscribed = serializers.BooleanField()
    last_subscription_date = serializers.CharField()
    subscription_date_over = serializers.CharField()
    last_subscription_type = SubscriptionSerializer()
    is_autopay_allowed = serializers.BooleanField()


class UserEducationSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserEducation
        fields = ["organization_name", "description", "entry_year"]


class UserProgramsSerializer(serializers.ModelSerializer):
    year = serializers.SerializerMethodField()

    class Meta:
        model = PartnerProgram
        fields = ["id", "tag", "name", "year"]

    def get_year(self, program: PartnerProgram) -> int | None:
        user_program_profile = PartnerProgramUserProfile.objects.filter(
            user=self.context.get("user"),
            partner_program=program,
        ).first()
        if user_program_profile:
            return user_program_profile.datetime_created.year


class UserDetailSerializer(
    serializers.ModelSerializer[CustomUser], SkillsWriteSerializerMixin
):
    member = MemberSerializer(required=False)
    investor = InvestorSerializer(required=False)
    expert = ExpertSerializer(required=False)
    mentor = MentorSerializer(required=False)
    achievements = AchievementListSerializer(required=False, many=True)
    education = UserEducationSerializer(many=True)
    links = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()
    programs = serializers.SerializerMethodField()
    v2_speciality = SpecializationSerializer(read_only=True)
    v2_speciality_id = serializers.IntegerField(
        write_only=True, validators=[specialization_exists_validator]
    )
    dataset_migration_applied = serializers.BooleanField(read_only=True)

    def get_projects(self, user: CustomUser):
        return UserProjectsSerializer(
            [
                collab.project
                for collab in user.collaborations.filter(project__draft=False)
            ],
            context={"request": self.context.get("request"), "user": user},
            many=True,
        ).data

    def get_programs(self, user: CustomUser):
        user_program_profiles = (
            user.partner_program_profiles
            .select_related('partner_program')
            .filter(partner_program__draft=False)
        )
        return UserProgramsSerializer(
            [profile.partner_program for profile in user_program_profiles],
            context={"request": self.context.get("request"), "user": user},
            many=True,
        ).data

    @classmethod
    def get_links(cls, user: CustomUser):
        return [user_link.link for user_link in user.links.all()]

    def get_is_online(self, user: CustomUser):
        request = self.context.get("request")
        if request and request.user.is_authenticated and request.user.id == user.id:
            return True
        cache_key = get_user_online_cache_key(user)
        return cache.get(cache_key, False)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "user_type",
            "email",
            "first_name",
            "last_name",
            "patronymic",
            "skills",
            "skills_ids",
            "birthday",
            "speciality",
            "v2_speciality",
            "v2_speciality_id",
            "organization",  # TODO need to be removed in future.
            "education",
            "about_me",
            "avatar",
            "links",
            "city",
            "is_active",
            "is_online",
            "member",
            "investor",
            "expert",
            "mentor",
            "achievements",
            "verification_date",
            "onboarding_stage",
            "projects",
            "programs",
            "dataset_migration_applied",
        ]

    @transaction.atomic
    def update(self, instance, validated_data):
        IMMUTABLE_FIELDS = ("email", "is_active", "password")
        USER_TYPE_FIELDS = ("member", "investor", "expert", "mentor")
        RELATED_FIELDS = ("achievements",)

        if instance.user_type == CustomUser.MEMBER:
            IMMUTABLE_FIELDS = ("email", "user_type", "is_active", "password")
            instance.member.__dict__.update(
                validated_data.get("member", model_to_dict(instance.member))
            )
            instance.member.save()
        elif instance.user_type == CustomUser.INVESTOR:
            instance.investor.__dict__.update(
                validated_data.get("investor", model_to_dict(instance.investor))
            )
            instance.investor.preferred_industries = validated_data.get(
                "investor", {}
            ).get("preferred_industries", [])
            instance.investor.save()
        elif instance.user_type == CustomUser.EXPERT:
            instance.expert.__dict__.update(
                validated_data.get("expert", model_to_dict(instance.expert))
            )
            instance.expert.preferred_industries = validated_data.get("expert", {}).get(
                "preferred_industries", []
            )
            instance.expert.save()
        elif instance.user_type == CustomUser.MENTOR:
            instance.mentor.__dict__.update(
                validated_data.get("mentor", model_to_dict(instance.mentor))
            )
            instance.mentor.save()

        user_types_to_attr = {
            CustomUser.MEMBER: "member",
            CustomUser.INVESTOR: "investor",
            CustomUser.EXPERT: "expert",
            CustomUser.MENTOR: "mentor",
        }
        user_types_to_model = {
            CustomUser.MEMBER: Member,
            CustomUser.INVESTOR: Investor,
            CustomUser.EXPERT: Expert,
            CustomUser.MENTOR: Mentor,
        }

        education_data = validated_data.pop("education", None)
        if education_data:
            self._update_user_education(instance, education_data)

        for attr, value in validated_data.items():
            if attr in IMMUTABLE_FIELDS + USER_TYPE_FIELDS + RELATED_FIELDS:
                continue
            if attr == "user_type":
                if value == instance.user_type or value not in user_types_to_attr.keys():
                    continue
                # we can't change user type to Member
                if value == CustomUser.MEMBER:
                    continue

                # delete old user type object and attribute
                getattr(instance, user_types_to_attr[instance.user_type]).delete()
                setattr(instance, user_types_to_attr[instance.user_type], None)

                instance.user_type = value

                # create new user type object, attribute sets automatically
                new_user_type = user_types_to_model[value](user=instance)
                new_user_type.save()
            setattr(instance, attr, value)

            if attr == "skills_ids":
                instance.skills.all().delete()

                for skill_id in value:
                    try:
                        skill = Skill.objects.get(id=skill_id)
                    except Skill.DoesNotExist:
                        raise serializers.ValidationError("Skill does not exist")

                    SkillToObject.objects.create(
                        skill=skill,
                        content_type=ContentType.objects.get_for_model(CustomUser),
                        object_id=instance.id,
                    )

        instance.save()

        return instance

    @transaction.atomic
    def _update_user_education(self, instance: CustomUser, data: list[dict]) -> None:
        """
        Update user education.
        `PUT`/ `PATCH` methods require full data about education.
        """
        instance.education.all().delete()
        UserEducation.objects.bulk_create([
            UserEducation(
                user=instance,
                organization_name=organization.get("organization_name"),
                description=organization.get("description"),
                entry_year=organization.get("entry_year"),
            )
            for organization in data
        ])


class UserChatSerializer(serializers.ModelSerializer[CustomUser]):
    is_online = serializers.SerializerMethodField()

    def get_is_online(self, user: CustomUser):
        request = self.context.get("request")
        if request and request.user.is_authenticated and request.user.id == user.id:
            return True
        cache_key = get_user_online_cache_key(user)
        return cache.get(cache_key, False)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "patronymic",
            "avatar",
            "is_active",
            "is_online",
        ]


class UserListSerializer(
    serializers.ModelSerializer[CustomUser], SkillsWriteSerializerMixin
):
    member = MemberSerializer(required=False)
    is_online = serializers.SerializerMethodField()

    def get_is_online(self, user: CustomUser) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated and request.user.id == user.id:
            return True

        cache_key = get_user_online_cache_key(user)
        is_online = cache.get(cache_key, False)
        return is_online

    def create(self, validated_data) -> CustomUser:
        user = CustomUser(**validated_data)
        user.set_password(validated_data["password"])
        user.save()

        for skill_id in validated_data.get("skills_ids", []):
            try:
                skill = Skill.objects.get(id=skill_id)
            except Skill.DoesNotExist:
                raise serializers.ValidationError("Skill does not exist")

            SkillToObject.objects.create(
                skill=skill,
                content_type=ContentType.objects.get_for_model(CustomUser),
                object_id=user.id,
            )

        return user

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "email",
            "user_type",
            "first_name",
            "last_name",
            "patronymic",
            "skills",
            "skills_ids",
            "avatar",
            "speciality",
            "birthday",
            "is_active",
            "is_online",
            "member",
            "onboarding_stage",
            "verification_date",
            "password",
        ]
        extra_kwargs = {
            "password": {"write_only": True},
            "onboarding_stage": {"read_only": True},
            "verification_date": {"read_only": True},
        }


class UserFeedSerializer(serializers.ModelSerializer, SkillsSerializerMixin):
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "email",
            "user_type",
            "first_name",
            "last_name",
            "patronymic",
            "skills",
            "speciality",
        ]


class AchievementDetailSerializer(serializers.ModelSerializer[UserAchievement]):
    class Meta:
        model = UserAchievement
        fields = [
            "id",
            "title",
            "status",
            "user",
        ]
        ref_name = "Users"


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyEmailSerializer(serializers.Serializer):
    result = serializers.JSONField()


class PasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True)


class ResendVerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class UserProjectListSerializer(serializers.ModelSerializer[Project]):
    views_count = serializers.SerializerMethodField(method_name="count_views")
    short_description = serializers.SerializerMethodField()

    @classmethod
    def count_views(cls, project):
        return get_views_count(project)

    @classmethod
    def get_short_description(cls, project):
        return project.get_short_description()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "leader",
            "short_description",
            "image_address",
            "industry",
            "views_count",
            "draft",
            "is_company",
        ]

        read_only_fields = ["leader", "views_count", "is_company"]

    def is_valid(self, *, raise_exception=False):
        return super().is_valid(raise_exception=raise_exception)

    def validate(self, data):
        super().validate(data)
        return validate_project(data)


class UserCloneDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = "__all__"


class CustomObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        return token


class RemoteBuySubSerializer(serializers.Serializer):
    subscription_id = serializers.IntegerField()
    redirect_url = serializers.CharField(required=False)
