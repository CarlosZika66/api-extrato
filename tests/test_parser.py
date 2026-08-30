import unittest

from api.index import _extrair_transacoes_layout, extrair_e_organizar_dados


class ExtratoParserTests(unittest.TestCase):
    def test_ignora_resumos_saldos_e_movimentacoes_de_reserva(self):
        texto = """
        EXTRATO DE CONTA
        Saldo inicial: R$ 749,09
        Entradas: R$ 7.837,03
        Saidas: R$ -8.586,12
        DETALHE DOS MOVIMENTOS
        Data Descrição ID da operação Valor Saldo
        01-08-2026
        Dinheiro retirado PARCELA
        MOTO 170671043989 R$ 3,01 R$ 752,10
        01-08-2026 Pagamento Cartão de crédito 171567835286 R$ -750,00 R$ 2,10
        01-08-2026
        Reserva por gastos PARCELA
        MOTO 170671590645 R$ -1,00 R$ 1,10
        04-08-2026
        Dinheiro reservado
        Emergências 171223544083 R$ -12,10 R$ 1.000,00
        Saldo final: R$ 0,00
        """

        transacoes = extrair_e_organizar_dados(texto)

        # Agora ignoramos "Dinheiro retirado" (caixinha), "Reserva por gastos" e "Dinheiro reservado"
        self.assertEqual(len(transacoes), 1)
        self.assertEqual(transacoes[0]["Descrição"], "Pagamento Cartão de crédito")
        self.assertEqual(transacoes[0]["Valor"], "R$ -750,00")

    def test_junta_descricao_quebrada_em_varias_linhas(self):
        texto = """
        DETALHE DOS MOVIMENTOS
        Data Descrição ID da operação Valor Saldo
        12-08-2026
        Pagamento com QR Pix
        DORCAS APARECIDA
        HERNANDEZ VILLAR
        173461291682 R$ -7,99 R$ 22,85
        """

        transacoes = extrair_e_organizar_dados(texto)

        self.assertEqual(len(transacoes), 1)
        self.assertEqual(
            transacoes[0]["Descrição"],
            "Pagamento com QR Pix DORCAS APARECIDA HERNANDEZ VILLAR",
        )

    def test_junta_descricao_quebrada_entre_paginas_sem_repetir_data(self):
        texto = """
        DETALHE DOS MOVIMENTOS
        21-08-2026
        Pagamento Cartão de crédito 174846914666 R$ -260,00 R$ 108,56
        Pagamento com QR Pix
        COMPANHIA DE
        9/13
        Data Descrição ID da operação Valor Saldo
        21-08-2026 SANEAMENTO BASICO DO
        ESTADO DE SAO PAULO
        SABESP
        174033830995 R$ -73,20 R$ 422,48
        """

        transacoes = extrair_e_organizar_dados(texto)

        self.assertEqual(len(transacoes), 2)
        self.assertEqual(
            transacoes[1]["Descrição"],
            "Pagamento com QR Pix COMPANHIA DE SANEAMENTO BASICO DO ESTADO DE SAO PAULO SABESP",
        )
        self.assertNotIn("21-08-2026", transacoes[1]["Descrição"])

    def test_nao_repete_operacoes_com_o_mesmo_id(self):
        texto = """
        DETALHE DOS MOVIMENTOS
        02-08-2026 Pix recebido Thalia 171703915076 R$ 10,00 R$ 11,10
        02-08-2026 Pix recebido Thalia 171703915076 R$ 10,00 R$ 11,10
        """

        transacoes = extrair_e_organizar_dados(texto)

        self.assertEqual(len(transacoes), 1)

    def test_nao_anexa_rodape_a_descricao_da_ultima_pagina(self):
        texto = """
        DETALHE DOS MOVIMENTOS
        28-08-2026 Pagamento Cartão de crédito 175169136617 R$ -150,00 R$ 609,57
        Data de geração: 29-08-2026
        Você tem alguma dúvida? Conte com o nosso Portal de ajuda.
        o nosso SAC, ligue para 0800 637 7246.
        Mercado Pago Instituição de Pagamento Ltda.
        903. Encontre nossos canais de consulta em mercadopago.com.br
        13/13
        Data Descrição ID da operação Valor Saldo
        28-08-2026 Pagamento Cartão de crédito 176116837132 R$ -169,00 R$ 439,57
        """

        transacoes = extrair_e_organizar_dados(texto)

        self.assertEqual(len(transacoes), 2)
        self.assertEqual(transacoes[1]["Descrição"], "Pagamento Cartão de crédito")

    def test_layout_por_colunas_separa_transacoes_e_continuacoes(self):
        texto = """
Data           Descrição                           ID da operação        Valor       Saldo

04-08-2026     Pagamento de parcela                172125543056          R$ -198,36  R$ 13,24
               Empréstimos Mercado Pago

04-08-2026     Reserva por gastos PARCELA          171225406789          R$ -1,00    R$ 12,24
               MOTO

05-08-2026     Pix enviado Laudecy Urenia          172148481592          R$ -177,54  R$ 11,24
               Scarparo
        """

        transacoes = _extrair_transacoes_layout(texto)

        self.assertEqual(len(transacoes), 2)
        self.assertEqual(
            transacoes[0]["Descrição"],
            "Pagamento de parcela Empréstimos Mercado Pago",
        )
        self.assertEqual(
            transacoes[1]["Descrição"], "Pix enviado Laudecy Urenia Scarparo"
        )

    def test_layout_reorganiza_descricao_extraida_depois_dos_valores(self):
        texto = """
Data Descrição ID da operação Valor Saldo
28082026 (1o DE GAS LTDA 175166885765 R$750,00 R$754,56 Pix recebido ENZO
        """

        transacoes = _extrair_transacoes_layout(texto)

        self.assertEqual(len(transacoes), 1)
        self.assertEqual(
            transacoes[0]["Descrição"],
            "Pix recebido ENZO COMERCIO DE GAS LTDA",
        )

    def test_layout_nao_anexa_numero_da_pagina(self):
        texto = """
Data Descrição ID da operação Valor Saldo
28082026 Pagamento Cartão de crédito 175169136617 R$-150,00 R$609,57
12113
<<<QUEBRA_DE_PAGINA>>>
Data Descrição ID da operação Valor Saldo
28082026 Pagamento Cartão de crédito 176116837132 R$-169,00 R$439,57
        """

        transacoes = _extrair_transacoes_layout(texto)

        self.assertEqual(len(transacoes), 2)
        self.assertEqual(transacoes[1]["Descrição"], "Pagamento Cartão de crédito")


if __name__ == "__main__":
    unittest.main()
