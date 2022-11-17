from django.forms.models import model_to_dict
from rest_framework import serializers

from .models import CustomUser, Expert, Investor, Member, Mentor, UserAchievement


class AchievementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAchievement
        fields = [
            "id",
            "title",
            "status",
        ]
        ref_name = "Users"


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = [
            "key_skills",
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
    class Meta:
        model = Expert
        fields = [
            "preferred_industries",
            "useful_to_project",
        ]


class InvestorSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "user_type",
            "email",
            "first_name",
            "last_name",
            "patronymic",
            "speciality",
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
            instance.investor.save()
        elif instance.user_type == CustomUser.EXPERT:
            instance.expert.__dict__.update(
                validated_data.get("expert", model_to_dict(instance.expert))
            )
            instance.expert.save()
        elif instance.user_type == CustomUser.MENTOR:
            instance.mentor.__dict__.update(
                validated_data.get("mentor", model_to_dict(instance.mentor))
            )
            instance.mentor.save()

        # maybe it's better to write ALLOWED_UPDATABLE_FIELDS = ["first_name", "last_name", ...]
        IMMUTABLE_FIELDS = ("email", "user_type", "is_active", "password")
        USER_TYPE_FIELDS = ("member", "investor", "expert", "mentor")
        RELATED_FIELDS = ("achievements",)
        for attr, value in validated_data.items():
            if attr in IMMUTABLE_FIELDS + USER_TYPE_FIELDS + RELATED_FIELDS:
                continue
            setattr(instance, attr, value)

        # if "achievements" in validated_data:
        #     instance.achievements.all().delete()
        #     instance.achievements.clear()
        #     for achievement in validated_data["achievements"]:
        #         obj = UserAchievement(**achievement)
        #         obj.save()
        #         instance.achievements.add(obj)
        instance.save()

        return instance


class UserListSerializer(serializers.ModelSerializer):
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
            "avatar",
            "speciality",
            "birthday",
            "is_active",
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
