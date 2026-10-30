from rest_framework import serializers

from accounts.tenancy import CurrentWorkspaceDefault

from .models import JiraBoard, JiraIntegration


class JiraConfigSerializer(serializers.ModelSerializer):
    api_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_token = serializers.SerializerMethodField()

    class Meta:
        model = JiraIntegration
        fields = ["base_url", "email", "api_token", "has_token", "enabled", "updated_at"]

    def get_has_token(self, obj):
        return bool(obj.api_token)

    def validate_api_token(self, value):
        """Bound in BYTES, not characters: the column's width is sized for a 255-byte token."""
        if len(value.encode("utf-8")) > 255:
            raise serializers.ValidationError(
                "API token is too long (limit 255 bytes). Jira tokens are far shorter; "
                "check you pasted a token and not a whole credential blob."
            )
        return value

    def update(self, instance, validated_data):
        # An empty token keeps the saved one only for the host it was issued for: moving base_url with the box
        # empty would otherwise send the saved credential to the new host.
        from urllib.parse import urlsplit

        token = validated_data.pop("api_token", None)
        new_url = validated_data.get("base_url", instance.base_url)
        moved = urlsplit(new_url or "").netloc.lower() != urlsplit(instance.base_url or "").netloc.lower()
        if token:
            instance.api_token = token
        elif moved and instance.api_token:
            instance.api_token = ""
            validated_data["enabled"] = False
        return super().update(instance, validated_data)


class JiraBoardSerializer(serializers.ModelSerializer):
    workspace = serializers.HiddenField(default=CurrentWorkspaceDefault())

    class Meta:
        model = JiraBoard
        fields = ["id", "board_id", "name", "created_at", "workspace"]
