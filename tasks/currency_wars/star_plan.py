"""Fix at most two three-star carries for an entire game."""
import re


def build_star_plan(guide_targets, title=''):
    names = list(guide_targets)
    # A title's carry name breaks ties between explicit guide three-stars.
    # Prefer a complete longer name (大黑塔) to its substring (黑塔).
    caption = re.sub(r'【[^】]*】', '', title)
    compact = lambda value: re.sub(r'[^\w\u4e00-\u9fff]', '', value)
    caption = compact(caption)
    mentioned = {name for name in names if compact(name) and compact(name) in caption}
    explicit = [name for name in names if guide_targets[name] >= 3]
    if explicit:
        candidates = explicit
        reason = 'guide_three_stars'
    elif mentioned:
        candidates = list(mentioned)
        reason = 'title_carry'
    else:
        candidates = names[:1]
        reason = 'first_guide_carry'
    candidates.sort(key=lambda name: (name not in mentioned, -len(compact(name)) if name in mentioned else 0, names.index(name)))
    cores = candidates[:2] if explicit else candidates[:1]
    return dict(version=1, cores=cores, primary=cores[0] if cores else None,
                targets={name: 3 if name in cores else 2 for name in names}, reason=reason)
