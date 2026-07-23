import os

# Os testes usam armazenamento de documentos em memória, sem tocar o disco.
os.environ["DOCUMENT_STORAGE_BACKEND"] = "memory"
