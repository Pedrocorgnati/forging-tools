# Daily Plan — multi-window

**Data:** 2026-03-16
**Objetivo:** App PySide6 desktop com 4 browsers embarcados (2 WhatsApp + 2 auxiliares) em layout vertical.

## Arquivos a Criar

| Arquivo | Descrição |
|---------|-----------|
| `main.py` | Entry point + MainWindow com layout completo |
| `browser_engine.py` | WebEngine manager simplificado (profiles, anti-detect, sidebar toggle) |
| `design_tokens.py` | Tokens dark mode (Warm Charcoal Gold do pua-minder) |
| `requirements.txt` | Dependências |
| `README.md` | Instruções de uso |

## Layout (Portrait)

```
┌──────────────────────────────┐
│  ■ Multi-Window              │  ← Title bar (custom)
├──────────────────────────────┤
│  [◧] WhatsApp 1             │  ← Header Row1 (sidebar toggle btn)
│  ┌────────────────────────┐  │
│  │   WebEngineView 1      │  │  ← Profile A
│  │   (WhatsApp)           │  │
│  └────────────────────────┘  │
│  ═══════ grip dots ════════  │  ← Splitter handle
│  [◧] WhatsApp 2             │  ← Header Row2 (sidebar toggle btn)
│  ┌────────────────────────┐  │
│  │   WebEngineView 2      │  │  ← Profile B
│  │   (WhatsApp)           │  │
│  └────────────────────────┘  │
│  ═══════ grip dots ════════  │  ← Splitter handle
│  ┌───────────┬────────────┐  │
│  │  View 3   │  View 4    │  │  ← Row3: Profile A | Profile B
│  │ (mini)    │  (mini)    │  │     (sessões compartilhadas)
│  └───────────┴────────────┘  │
└──────────────────────────────┘
```

**Stretch factors:** Row1=4, Row2=4, Row3=2

## Decisões Técnicas

1. **Profiles compartilhados:** QWebEngineProfile com nome único por slot. Views 1+3 compartilham profile "slot-1", Views 2+4 compartilham profile "slot-2". Cada profile tem storage persistente em `~/.multi-window/profiles/slot-{n}/`.

2. **Sidebar toggle (2 estados):**
   - Default: 50% (sidebar visível com metade da largura original)
   - Toggle: colapsado (sidebar hidden)
   - Ícone: ◧ (50%) ↔ ◨ (colapsado)
   - Implementado via JS injection no WhatsApp Web (#side element)

3. **Anti-detecção:** Chrome header spoof + JS anti-detect (copiado do pua-minder)

4. **Tema:** Dark mode Warm Charcoal Gold — bg=#1C1917, surface=#292524, accent=#D4A574

5. **Title bar:** Custom frameless com drag + botões min/max/close estilizados

## Critérios de Aceite

- [ ] App abre com 4 browsers embarcados
- [ ] WhatsApp Web carrega nos 4 views
- [ ] Login no View1 automaticamente reflete no View3
- [ ] Login no View2 automaticamente reflete no View4
- [ ] Botão de sidebar toggle funciona (2 estados)
- [ ] Layout responde bem em tela vertical
- [ ] Visual dark mode polido com tokens consistentes
- [ ] Splitter handles com grip dots
- [ ] Title bar customizada com nome do app
