from django.forms.models import model_to_dict
from rest_framework import serializers

from .models import CustomUser, Expert, Investor, Member, Mentor


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = [
            "key_skills",
            "useful_to_project",
            "preferred_industries",
        ]


class MentorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mentor
        fields = [
            "useful_to_project",
            "first_additional_role",
            "second_additional_role",
        ]


class ExpertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expert
        fields = [
            "preferred_industries",
            "useful_to_project",
            "first_additional_role",
            "second_additional_role",
        ]


class InvestorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Investor
        fields = [
            "interaction_process_description",
            "preferred_industries",
            "first_additional_role",
            "second_additional_role",
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    member = MemberSerializer(required=False)
    investor = InvestorSerializer(required=False)
    expert = ExpertSerializer(required=False)
    mentor = MentorSerializer(required=False)

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
            "is_active",
            "member",
            "investor",
            "expert",
            "mentor",
        ]

    def update(self, instance, validated_data):
        IMMUTABLE_FIELDS = ("email", "is_active", "password")
        USER_TYPE_FIELDS = ("member", "investor", "expert", "mentor")

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

        for attr, value in validated_data.items():
            if attr in IMMUTABLE_FIELDS + USER_TYPE_FIELDS:
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
            "user_type",
            "email",
            "first_name",
            "last_name",
            "patronymic",
            "avatar",
            "is_active",
            "password",
        ]
        extra_kwargs = {"password": {"write_only": True}}


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyEmailSerializer(serializers.Serializer):
    result = serializers.JSONField()


class PasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True)
