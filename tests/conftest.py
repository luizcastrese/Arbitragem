import os

# Os testes usam armazenamento de documentos em memória, sem tocar o disco.
os.environ["DOCUMENT_STORAGE_BACKEND"] = "memory"

# Sem calendário OpenTimestamps por padrão nos testes: carimbar de verdade
# exigiria rede, e cada tentativa bloqueada custa o timeout inteiro. Os testes
# que exercitam o carimbo sobem um calendário local e o apontam explicitamente.
os.environ["OTS_CALENDARS"] = ""
