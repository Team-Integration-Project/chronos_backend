from django.db import models
from django.contrib.auth.models import AbstractUser
from pgvector.django import VectorField

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    facial_embedding = VectorField(dimensions=128,null=True, blank=True)

    def __str__(self):
        return self.username
    

class PasswordResetToken(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=True)

    def __str__(self):
        return f"Token for {self.user.email}"
