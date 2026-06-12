# auth.py
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

class AnonymousSessionUser:
    """
    A lightweight object to represent an authenticated anonymous session.
    Behaves like a user object so DRF permissions still work.
    """
    def __init__(self, anonymous_id):
        self.anonymous_id = anonymous_id
        self.role = "anonymous"

    @property
    def is_authenticated(self):
        return True  # DRF sees this as authenticated

    def __str__(self):
        return f"AnonymousUser({self.anonymous_id})"


class AnonymousJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        if "anonymous_id" in validated_token:
            # Return fake authenticated user object
            return AnonymousSessionUser(validated_token["anonymous_id"])

        # Fallback to normal SimpleJWT logic
        try:
            return super().get_user(validated_token)
        except Exception:
            raise InvalidToken("Invalid token or user not found.")
