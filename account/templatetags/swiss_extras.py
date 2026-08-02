from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a key with spaces."""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def has_split_groups(split_groups):
    """Check if any split groups exist."""
    if split_groups is None:
        return False
    return any(split_groups.get(key) for key in ['Direct Qualifiers', 'Playoff', 'Eliminated'])

@register.filter
def phase_color(phase):
    """Return color class for phase badge."""
    colors = {
        'swiss': 'secondary',
        'split': 'success',
        'playoff': 'warning',
        'knockout': 'primary',
    }
    return colors.get(phase, 'secondary')