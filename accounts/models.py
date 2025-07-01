from django.db import models
from django.contrib.auth.models import AbstractUser
from pgvector.django import VectorField

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    facial_embedding = VectorField(dimensions=128,null=True, blank=True)

    def __str__(self):
        return self.username

# Create your models here.
