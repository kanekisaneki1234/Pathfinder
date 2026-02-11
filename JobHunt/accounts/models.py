from django.db import models
from django.conf import settings

# Create your models here.

class RoadmapStep(models.Model):
    STATUS_CHOICES = [
        ("todo", "Not Started"),
        ("doing", "In Progress"),
        ("done", "Completed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roadmap_steps"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="todo"
    )
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.title} ({self.user.username})"

class Job(models.Model):
    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)

    description = models.TextField()
    requirements = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} at {self.company}"
