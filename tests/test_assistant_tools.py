"""Qui a le droit de chercher, et qui ne l'a jamais.

La distinction est la garantie du compte rendu : un document qui se compose de
ce qui a été dit ne doit pas pouvoir compléter une décision par ce qu'un moteur
de recherche a rendu.
"""

from greffier.adapters.configuration import Config
from greffier.adapters.writer_claude import ClaudeWriter
from greffier.wiring import assistant, writer


def config(**conversation) -> Config:
    reglages = Config()
    for key, value in conversation.items():
        setattr(reglages.conversation, key, value)
    return reglages


class TestLeRedacteurNaJamaisDOutil:
    def test_aucun_outil_par_defaut(self):
        assert ClaudeWriter().tools == ()

    def test_le_redacteur_du_compte_rendu_n_en_recoit_aucun(self):
        engine = writer(config())
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()

    def test_meme_si_la_recherche_est_activee(self):
        """Le réglage de la conversation ne doit pas fuir vers le compte rendu."""
        engine = writer(config(recherche_web=True))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()


class TestLAssistantPeutChercher:
    def test_la_recherche_est_accordee_quand_elle_est_activee(self):
        engine = assistant(config(recherche_web=True))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ClaudeWriter.SEARCH_TOOLS

    def test_elle_s_eteint_depuis_les_reglages(self):
        """Il y a des réunions où même le terme cherché ne doit pas sortir."""
        engine = assistant(config(recherche_web=False))
        assert isinstance(engine, ClaudeWriter)
        assert engine.tools == ()

    def test_l_assistant_ne_recite_pas_le_plan_du_compte_rendu(self):
        """Répondre « qui est Morgane ? » n'appelle pas Décisions / Actions."""
        engine = assistant(config())
        assert isinstance(engine, ClaudeWriter)
        assert engine.consignes_propres
        assert "Décisions" not in engine.consignes_propres

    def test_il_lui_est_interdit_d_envoyer_les_propos_dehors(self):
        engine = assistant(config())
        assert isinstance(engine, ClaudeWriter)
        # Aplati : la consigne tient sur deux lignes dans le texte source.
        aplati = " ".join(engine.consignes_propres.split())
        assert "jamais la phrase de la réunion" in aplati

    def test_il_doit_donner_l_adresse_de_ce_qu_il_trouve(self):
        """Une réponse sans sa source ne se vérifie pas, et en réunion on veut
        pouvoir ouvrir le lien tout de suite."""
        aplati = " ".join(assistant(config()).consignes_propres.split())
        assert "donne l'adresse" in aplati
        assert "URL complète" in aplati

    def test_il_propose_quelque_chose_sans_rien_inventer(self):
        aplati = " ".join(assistant(config()).consignes_propres.split())
        assert "À faire :" in aplati
        assert "N'invente rien pour remplir" in aplati

    def test_il_peut_chercher_de_lui_meme(self):
        """« Qu'il le fasse lui-même pour se donner du contexte » — demandé."""
        aplati = " ".join(assistant(config()).consignes_propres.split())
        assert "de ton propre chef" in aplati
