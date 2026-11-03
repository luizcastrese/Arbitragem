"""Avisos por e-mail dos atos e prazos do procedimento.

A plataforma só funciona se cada parte souber quando é a sua vez: o
contraditório, o prazo de recurso e o prazo de reflexão correm contra quem
não abre o painel. Este pacote liga a trilha de auditoria a uma fila de
e-mails (`rules`), envia a fila com nova tentativa (`outbox`), cobra quem
deixou um prazo ou um material parado (`reminders`) e roda tudo em segundo
plano (`worker`).
"""
