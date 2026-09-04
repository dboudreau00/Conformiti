from rest_framework import serializers

from .models import JiraBoard, JiraIntegration


class JiraConfigSerializer(serializers.ModelSerializer):
    """The token is write-only; `has_token` tells the UI one is saved."""
    api_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_token = serializers.SerializerMethodField()

    class Meta:
        model = JiraIntegration
        fields = ["base_url", "email", "api_token", "has_token", "enabled", "updated_at"]

    def get_has_token(self, obj):
        return bool(obj.api_token)

    def validate_api_token(self, value):
        """Bound in BYTES, not characters.

        The column stores the encryption envelope, whose width was sized for a
        255-*byte* token. 255 non-ASCII characters is up to 1020 UTF-8 bytes and
        would overflow the column — a 500 at write time rather than a 400 here.
        """
        if len(value.encode("utf-8")) > 255:
            raise serializers.ValidationError(
                "API token is too long (limit 255 bytes). Jira tokens are far shorter; "
                "check you pasted a token and not a whole credential blob."
            )
        return value

    def update(self, instance, validated_data):
        # An empty token field means "keep the saved one".
        token = validated_data.pop("api_token", None)
        if token:
            instance.api_token = token
        return super().update(instance, validated_data)


class JiraBoardSerializer(serializers.ModelSerializer):
    class Meta:
        model = JiraBoard
        fields = ["id", "board_id", "name", "created_at"]
