from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    username = serializers.CharField(source="user.username", read_only=True, default="")

    class Meta:
        model = AuditLog
        fields = [
            "id", "user", "user_name", "username", "action",
            "object_type", "object_id", "detail", "ip_address", "timestamp",
        ]

    def get_user_name(self, obj):
        if not obj.user:
            return "system"
        return obj.user.get_full_name() or obj.user.get_username()
