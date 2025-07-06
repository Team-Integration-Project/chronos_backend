from django.db import models
from django.contrib.auth.models import AbstractUser
from pgvector.django import VectorField
from enum import Enum

class UserRole(Enum):
    USER = "user"
    ADMIN = "admin"

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    facial_embedding = VectorField(dimensions=128,null=True, blank=True)
    role = models.CharField(max_length=10, choices=[(role.value, role.value) for role in UserRole], default=UserRole.USER.value)

    def __str__(self):
        return self.username

    @property
    def is_Admin(self):
        return self.role == UserRole.ADMIN.value
    

class PasswordResetToken(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=True)

    def __str__(self):
        return f"Token for {self.user.email}"
