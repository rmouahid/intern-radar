"""Install page of the Safari form filler."""

from intern_radar.dashboard.layout import e


def autofill_body(script_url: str) -> str:
    steps = (
        "Installe l'app gratuite <b>Userscripts</b> (App Store, éditeur "
        "Justin Wasack).",
        "Réglages → Apps → Safari → Extensions → <b>Userscripts</b> : active-la et "
        "autorise-la sur <i>greenhouse.io</i>, <i>lever.co</i> et <i>ashbyhq.com</i> "
        "(ou « Tous les sites »).",
        f'Ouvre <a href="{e(script_url)}">ce lien vers le script</a> dans Safari, '
        "touche l'icône « puzzle » de la barre d'adresse → Userscripts → "
        "<b>Installer</b>.",
        "Depuis le kit d'une offre, touche « 📝 Ouvrir le formulaire » : un bouton "
        "<b>📡 Radar</b> apparaît en bas à droite du formulaire. « Remplir le "
        "formulaire », relis, complète les champs en orange, puis envoie toi-même.",
        "Reviens sur l'offre et touche « ✅ J'ai postulé » pour archiver l'envoi.",
    )
    items = "".join(f"<li style='margin-bottom:8px'>{s}</li>" for s in steps)
    return (
        "<h1>Remplissage automatique</h1>"
        "<p class='muted'>Le remplissage se fait dans ton Safari, sur ton iPhone : "
        "les captchas des formulaires se comportent normalement et rien ne part "
        "sans toi. Plateformes : Greenhouse, Lever et Ashby (environ 37 % des "
        "offres pertinentes).</p>"
        f"<section><h2>Installation (une fois)</h2><ol>{items}</ol></section>"
        "<section><h2>Ce que fait le script</h2><ul>"
        "<li>Remplit identité, contact, liens, études, disponibilités et les "
        "questions d'autorisation de travail et de parrainage (texte ou oui/non).</li>"
        "<li>Joint le CV adapté et la lettre quand le formulaire a un emplacement.</li>"
        "<li>Répond aux questions propres à l'entreprise (listes, cases à cocher, "
        "oui/non, textes) grâce à l'IA, à partir de ton profil uniquement ; ses "
        "réponses sont <b>surlignées en jaune</b> pour relecture. Les consentements "
        "et les questions de diversité restent toujours pour toi.</li>"
        "<li>Les listes à recherche de Greenhouse refusent le remplissage par "
        "script : elles sont <b>entourées en bleu</b> et le panneau donne la valeur "
        "à choisir, avec « Aller » qui t'y amène et copie la valeur.</li>"
        "<li>Entoure en orange les champs obligatoires restés vides et liste toutes "
        "tes réponses avec un bouton « Copier ».</li>"
        "<li>Ne clique jamais sur « Submit » et ne touche jamais aux captchas.</li>"
        "</ul><p class='muted'>Si l'extension ne peut pas joindre la web app (iOS "
        "bloque parfois le HTTP simple), le script utilise la copie des réponses "
        "transportée par le lien « Ouvrir le formulaire » ; joins alors les PDF à "
        "la main depuis le kit.</p></section>"
        "<section><h2>Sur ordinateur</h2><p>Le même script fonctionne avec "
        "Tampermonkey (Chrome, Firefox, Safari).</p></section>"
    )
