# FCBAgent v1.0 — Federação Columbófila Brasileira

**Sistema de captura de chegadas para leitores eletrônicos eletrônicos**

---

## ⚡ Início Rápido

### Opção A — Executável pronto (recomendado para criadores)
Se você recebeu o arquivo `FCBAgent.exe`:
1. Coloque o `FCBAgent.exe` em qualquer pasta (ex: `C:\FCBAgent\`)
2. Dê duplo clique para abrir
3. Na primeira abertura, preencha seus dados de criador
4. Clique em **SALVAR** e o agente iniciará automaticamente

### Opção B — Gerar o .exe a partir do código fonte
Se você recebeu a pasta completa com o código:
1. Instale **Python 3.10+** em https://python.org *(marque "Add Python to PATH")*
2. Dê duplo clique em **`build-exe.bat`**
3. Aguarde 2–3 minutos
4. O arquivo `FCBAgent.exe` será gerado na pasta raiz

---

## ⚙️ Configuração

Na primeira execução, a janela de configuração abrirá automaticamente:

| Campo | Descrição |
|-------|-----------|
| **Nome completo** | Seu nome completo como criador |
| **ID FCB** | Seu número de registro na FCB (ex: 9999) |
| **ID do Clube** | Número do seu clube na FCB (ex: 1) |
| **Token FCB Agent** | Token gerado no Painel Admin → sua conta |
| **Porta serial** | Deixe "auto" para detectar automaticamente |

---

## 🔌 Conexão do Constatador

1. Conecte o constatador via USB ao computador
2. O FCBAgent detecta automaticamente (drivers CP210x, FTDI, CH340)
3. O indicador na barra de status ficará **verde** quando conectado

**Leitores eletrônicos compatíveis:** Bricon, Unikon, Benzing, Super-V, DEISTER (protocolo Unives 1.7)

---

## 🕊️ Funcionamento

```
Pombo chega → Anilha lida pelo constatador → Serial USB → 
FCBAgent → HTTPS → api.fcbpigeonslive.com.br → 
Painel ao vivo atualizado em tempo real
```

- **Offline automático:** se sem internet, chegadas são salvas localmente
- **Sincronização:** quando a internet voltar, envia automaticamente
- **Bandeja do sistema:** minimiza para o relógio — sempre rodando
- **Autostart:** pode iniciar junto com o Windows

---

## 🐛 Solução de Problemas

**"Constatador não encontrado"**
- Verifique se o cabo USB está conectado
- Instale o driver do constatador (geralmente CP210x ou FTDI)
- Tente selecionar a porta manualmente em Configurações

**"Configuração incompleta"**
- Preencha o ID FCB e o Token em ⚙ Config

**"API indisponível"**
- Verifique a conexão com a internet
- A chegada será salva offline e enviada quando reconectar

**Logs completos:** arquivo `fcbagent.log` na mesma pasta do .exe

---

## 📞 Suporte

- **Site:** https://fcbpigeonslive.com.br
- **E-mail:** contato@fcb.org.br
- **Painel Admin:** https://fcbpigeonslive.com.br/painel-admin

---

*FCBAgent v1.0 · © 2026 Federação Columbófila Brasileira · Todos os direitos reservados*
