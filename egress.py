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
