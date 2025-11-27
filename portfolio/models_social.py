"""
Social features models - User profiles, following, posts, comments, likes
These models will be added to models.py
"""
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from .models import Stock


class UserProfile(models.Model):
    """Extended user profile with social features"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(max_length=500, blank=True, help_text="Short bio about yourself")
    avatar = models.URLField(blank=True, help_text="URL to profile picture")
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    twitter_handle = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
    
    def __str__(self):
        return f"{self.user.username}'s Profile"
    
    @property
    def followers_count(self):
        """Get number of followers"""
        return self.user.followers.count()
    
    @property
    def following_count(self):
        """Get number of users being followed"""
        return self.user.following.count()
    
    @property
    def posts_count(self):
        """Get number of posts"""
        return self.user.posts.count()


class Follow(models.Model):
    """Follow relationship between users"""
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following', db_index=True)
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='followers', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['follower', 'following']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['follower', 'following']),
            models.Index(fields=['following']),
        ]
        verbose_name = "Follow"
        verbose_name_plural = "Follows"
    
    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"


class Post(models.Model):
    """User posts/insights about stocks or investing"""
    POST_TYPE_CHOICES = [
        ('insight', 'Investment Insight'),
        ('analysis', 'Stock Analysis'),
        ('question', 'Question'),
        ('discussion', 'Discussion'),
        ('update', 'Portfolio Update'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts', db_index=True)
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default='insight')
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField(max_length=5000, help_text="Post content")
    
    # Optional stock reference
    stock = models.ForeignKey(Stock, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    
    # Engagement metrics
    likes_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    views_count = models.IntegerField(default=0)
    
    # Moderation
    is_pinned = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['stock', '-created_at']),
            models.Index(fields=['post_type', '-created_at']),
        ]
        verbose_name = "Post"
        verbose_name_plural = "Posts"
    
    def __str__(self):
        return f"{self.user.username} - {self.post_type} ({self.created_at.date()})"
    
    def increment_views(self):
        """Increment view counter"""
        self.views_count += 1
        self.save(update_fields=['views_count'])


class Comment(models.Model):
    """Comments on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments', db_index=True)
    content = models.TextField(max_length=2000)
    likes_count = models.IntegerField(default=0)
    is_edited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
    
    def __str__(self):
        return f"{self.user.username} on {self.post.id}"


class PostLike(models.Model):
    """Likes on posts"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='post_likes', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_likes', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']
        indexes = [
            models.Index(fields=['post', 'user']),
        ]
        verbose_name = "Post Like"
        verbose_name_plural = "Post Likes"
    
    def __str__(self):
        return f"{self.user.username} likes {self.post.id}"
    
    def save(self, *args, **kwargs):
        """Update post likes count when saving"""
        super().save(*args, **kwargs)
        self.post.likes_count = self.post.post_likes.count()
        self.post.save(update_fields=['likes_count'])
    
    def delete(self, *args, **kwargs):
        """Update post likes count when deleting"""
        post = self.post
        super().delete(*args, **kwargs)
        post.likes_count = post.post_likes.count()
        post.save(update_fields=['likes_count'])


class CommentLike(models.Model):
    """Likes on comments"""
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='comment_likes', db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_likes', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['comment', 'user']
        indexes = [
            models.Index(fields=['comment', 'user']),
        ]
        verbose_name = "Comment Like"
        verbose_name_plural = "Comment Likes"
    
    def __str__(self):
        return f"{self.user.username} likes comment {self.comment.id}"
    
    def save(self, *args, **kwargs):
        """Update comment likes count when saving"""
        super().save(*args, **kwargs)
        self.comment.likes_count = self.comment.comment_likes.count()
        self.comment.save(update_fields=['likes_count'])
    
    def delete(self, *args, **kwargs):
        """Update comment likes count when deleting"""
        comment = self.comment
        super().delete(*args, **kwargs)
        comment.likes_count = comment.comment_likes.count()
        comment.save(update_fields=['likes_count'])


