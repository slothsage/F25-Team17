from django import template

register = template.Library()

@register.filter(name="has_group")
def has_group(user, group_name: str) -> bool:
    """Return True if the user is in the given group name."""
    if user is None:
        return False
    try:
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
    except Exception:
        # For anonymous users or unexpected values
        return False
