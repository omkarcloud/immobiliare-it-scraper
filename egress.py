"""The one network helper the immobiliare_it module needs: the
Accept-Language its sessions send. Every session announces the list a
desktop browser set to US English sends — on your own connection or on
IMMOBILIARE_IT_PROXY alike; immobiliare.it then serves the language the
`language` param asks for."""

US_ENGLISH = "en-US,en;q=0.9"


def site_accept_language(site=None):
    return US_ENGLISH


def accept_language(proxy=None, country=None):
    return US_ENGLISH


ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def exit_proxy(exit=None):
    return exit if exit and "://" in str(exit) else None


def new_session(exit=None, impersonate="chrome", **kw):
    from curl_cffi import requests as curl
    sess = curl.Session(impersonate=impersonate, **kw)
    proxy = exit_proxy(exit)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess
