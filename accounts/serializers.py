from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

User = get_user_model()

DUPLICATE_EMAIL = "A user with that email already exists."


class UserSerializer(serializers.ModelSerializer):
    """Public view of a user. Never includes the password."""

    class Meta:
        model = User
        fields = ["id", "username", "email", "is_organiser"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "is_organiser"]
        # is_organiser is output only: a value sent by the client is ignored.
        read_only_fields = ["id", "is_organiser"]
        extra_kwargs = {"email": {"required": True, "allow_blank": False}}

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(DUPLICATE_EMAIL)
        return email

    def validate(self, attrs):
        # Unsaved user so the similarity validator can compare the password
        # against the username and email.
        candidate = User(username=attrs.get("username"), email=attrs.get("email"))
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        try:
            # Savepoint so a failed insert doesn't break an outer transaction.
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError as exc:
            # Two sign-ups with the same email racing past validate_email:
            # the database constraint catches the second one.
            raise serializers.ValidationError({"email": [DUPLICATE_EMAIL]}) from exc


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
