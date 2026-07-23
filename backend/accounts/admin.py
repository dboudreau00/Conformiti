from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Role, User

admin.site.register(Role)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Compliance", {"fields": ("role", "job_title")}),)
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
