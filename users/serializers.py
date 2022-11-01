from rest_framework import serializers

from .models import CustomUser, Member, Mentor, Expert, Investor


class UserSerializer(serializers.ModelSerializer):
    user_type_fields = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "user_type",
            "email",
            "first_name",
            "last_name",
            "patronymic",
            "avatar",
            "city",
            "password",
            "is_active",
            "user_type_fields",
        ]

    def get_user_type_fields(self, obj):
        # maybe thats not the best way to do it, but it also works

        # user_type_to_serializer = {
        #     "member": MemberSerializer,
        #     "expert": ExpertSerializer,
        #     "investor": InvestorSerializer,
        #     "mentor": MentorSerializer,
        # }
        # for user_type in user_type_to_serializer.keys():
        #     if hasattr(obj, user_type):
        #         serializer = user_type_to_serializer[user_type](getattr(obj, user_type))
        #         return serializer.data

        if obj.user_type == CustomUser.MEMBER:
            return MemberSerializer(obj.member).data
        elif obj.user_type == CustomUser.MENTOR:
            return MentorSerializer(obj.mentor).data
        elif obj.user_type == CustomUser.EXPERT:
            return ExpertSerializer(obj.expert).data
        elif obj.user_type == CustomUser.INVESTOR:
            return InvestorSerializer(obj.investor).data

    def create(self, validated_data):
        user = CustomUser(**validated_data)
        user.set_password(validated_data["password"])
        user.save()

        return user


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = [
            "key_skills",
            "useful_to_project",
            "speciality",
        ]


class MentorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mentor
        fields = [
            "job",
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


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyEmailSerializer(serializers.Serializer):
    result = serializers.JSONField()


class PasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True)
