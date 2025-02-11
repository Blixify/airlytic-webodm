import datetime
import math
import logging
import time
from django import template
from webodm import settings
from django.utils.translation import gettext as _

register = template.Library()
logger = logging.getLogger('app.logger')

@register.simple_tag
def task_options_docs_link():
    return settings.TASK_OPTIONS_DOCS_LINK

@register.simple_tag
def gcp_docs_link():
    return '<a href="%s" target="_blank">' % settings.GCP_DOCS_LINK

@register.simple_tag
def reset_password_link():
    return settings.RESET_PASSWORD_LINK

@register.simple_tag
def has_external_auth():
    return settings.EXTERNAL_AUTH_ENDPOINT != ""

@register.filter
def disk_size(megabytes):
    k = 1000
    k2 = k ** 2
    k3 = k ** 3
    if megabytes <= k2:
        return str(round(megabytes / k, 2)) + ' GB'
    elif megabytes <= k3:
        return str(round(megabytes / k2, 2)) + ' TB'
    else:
        return str(round(megabytes / k3, 2)) + ' PB'

@register.simple_tag
def percentage(num, den, maximum=None):
    if den == 0:
        return 100
    perc = max(0, num / den * 100)
    if maximum is not None:
        perc = min(perc, maximum)
    return perc

@register.simple_tag(takes_context=True)
def quota_exceeded_grace_period(context):
    deadline = context.request.user.profile.get_quota_deadline()
    now = time.time()
    if deadline is None:
        deadline = now + settings.QUOTA_EXCEEDED_GRACE_PERIOD * 60 * 60
    diff = max(0, deadline - now)
    if diff >= 60*60*24*2:
        return _("in %(num)s days") % {"num": math.floor(diff / (60*60*24))}
    elif diff >= 60*60*2:
        return _("in %(num)s hours") % {"num": math.floor(diff / (60*60))}
    elif diff > 1:
        return _("in %(num)s minutes") % {"num": math.floor(diff / 60)}
    else:
        return _("very soon")
    

@register.simple_tag
def is_single_user_mode():
    return settings.SINGLE_USER_MODE

@register.simple_tag
def is_desktop_mode():
    return settings.DESKTOP_MODE

@register.simple_tag
def is_dev_mode():
    return settings.DEV

@register.simple_tag(takes_context=True)
def settings_image_url(context, image):
    try:
        img_cache = getattr(context['SETTINGS'], image)
    except KeyError:
        logger.warning("Cannot get SETTINGS key from context. Something's wrong in settings_image_url.")
        return ''

    try:
        return "/media/" + img_cache.url
    except FileNotFoundError:
        logger.warning("Cannot get %s, this could mean the image was deleted." % image)
        return ''

@register.simple_tag(takes_context=True)
def get_footer(context):
    try:
        settings = context['SETTINGS']
    except KeyError:
        logger.warning("Cannot get SETTINGS key from context. The footer will not be displayed.")
        return ""

    if settings.theme.html_footer == "": return ""

    organization = ""
    if settings.organization_name != "" and settings.organization_website != "":
        organization = "<a href='{}'>{}</a>".format(settings.organization_website, settings.organization_name)
    elif settings.organization_name != "":
        organization = settings.organization_name

    footer = settings.theme.html_footer
    footer = footer.replace("{ORGANIZATION}", organization)
    footer = footer.replace("{YEAR}", str(datetime.datetime.now().year))

    return "<footer>" + \
           footer + \
            "</footer>"
