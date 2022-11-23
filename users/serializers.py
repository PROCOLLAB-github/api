from django.forms.models import model_to_dict
from rest_framework import serializers

from .models import CustomUser, Expert, Investor, Member, Mentor, UserAchievement


class AchievementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAchievement
        fields = ["id", "title", "status"]
        ref_name = "Users"


class KeySkillsField(serializers.Field):
    def to_representation(self, value):
        return [skill.strip() for skill in value.split(",") if skill.strip()]

    def to_internal_value(self, data):
        return ",".join(data)


class CustomListField(serializers.ListField):
    # костыль
    def to_representation(self, data):
        if type(data) == list:
            return data
        return [i.replace("'", "") for i in data.strip("][").split(", ")]


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = [
            "useful_to_project",
        ]


class MentorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mentor
        fields = [
            # "job",
            "useful_to_project",
        ]


class ExpertSerializer(serializers.ModelSerializer):

    preferred_industries = CustomListField(
        child=serializers.CharField(max_length=255),
    )

    class Meta:
        model = Expert
        fields = [
            "preferred_industries",
            "useful_to_project",
        ]


class InvestorSerializer(serializers.ModelSerializer):

    preferred_industries = CustomListField(child=serializers.CharField(max_length=255))

    class Meta:
        model = Investor
        fields = [
            "interaction_process_description",
            "preferred_industries",
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    member = MemberSerializer(required=False)
    investor = InvestorSerializer(required=False)
    expert = ExpertSerializer(required=False)
    mentor = MentorSerializer(required=False)
    achievements = AchievementListSerializer(required=False, many=True)
    key_skills = KeySkillsField(required=False)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "user_type",
            "email",
            "first_name",
            "last_name",
            "patronymic",
            "key_skills",
            "birthday",
            "speciality",
            "organization",
            "about_me",
            "avatar",
            "city",
            "is_active",
            "member",
            "investor",
            "expert",
            "mentor",
            "achievements",
        ]

    def update(self, instance, validated_data):
        if instance.user_type == CustomUser.MEMBER:
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
            print("expert", instance.expert.preferred_industries)
            instance.expert.save()
        elif instance.user_type == CustomUser.MENTOR:
            instance.mentor.__dict__.update(
                validated_data.get("mentor", model_to_dict(instance.mentor))
            )
            instance.mentor.save()

        IMMUTABLE_FIELDS = ("email", "user_type", "is_active", "password")
        USER_TYPE_FIELDS = ("member", "investor", "expert", "mentor")
        RELATED_FIELDS = ("achievements",)

        for attr, value in validated_data.items():
            if attr in IMMUTABLE_FIELDS + USER_TYPE_FIELDS + RELATED_FIELDS:
                continue
            setattr(instance, attr, value)

        instance.save()
        return instance


class UserListSerializer(serializers.ModelSerializer):
    member = MemberSerializer(required=False)
    key_skills = KeySkillsField(required=False)

    def create(self, validated_data):
        user = CustomUser(**validated_data)
        user.set_password(validated_data["password"])
        user.save()

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
            "key_skills",
            "avatar",
            "speciality",
            "birthday",
            "is_active",
            "member",
            "password",
        ]
        extra_kwargs = {"password": {"write_only": True}}


class AchievementDetailSerializer(serializers.ModelSerializer):
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
