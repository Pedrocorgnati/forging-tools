# Daily Scan — multi-window

**Data:** 2026-03-16
**Task:** Criar app Python desktop (PySide6 + QtWebEngine) com múltiplos navegadores embarcados para visualizar 2 WhatsApps + 2 páginas auxiliares em tela vertical.

## Contexto Identificado

### Dependências Reutilizáveis (pua-minder)
| Arquivo | O que aproveitar |
|---------|------------------|
| `src/services/webengine_manager.py` | Perfis isolados, anti-detecção Chrome, OAuth popup, sidebar toggle JS, permissões de mídia |
| `src/ui/widgets/collapsible_section.py` | Padrão de widget colapsável (não necessário direto, mas referência) |

### Arquitetura Proposta
- **Profiles compartilhados**: Row1 e Row3-left usam o MESMO `QWebEngineProfile` (sessão compartilhada). Row2 e Row3-right idem.
- **Layout vertical (portrait)**: 3 linhas em `QSplitter(Vertical)`:
  - **Row1**: WebEngineView (WhatsApp 1) — header com botão collapse sidebar
  - **Row2**: WebEngineView (WhatsApp 2) — header com botão collapse sidebar
  - **Row3**: `QSplitter(Horizontal)` com 2 WebEngineViews (sessões compartilhadas com Row1 e Row2)
- **Sidebar collapse**: Botão no header de Row1/Row2 que injeta JS para toggle do `#side` do WhatsApp. Primeiro clique colapsa, segundo descolapsa com 50% do tamanho.
- **Sessões persistentes**: Cookies + localStorage salvos em disco por profile

### Stack
- Python 3.11+
- PySide6 + PySide6-WebEngine (QtWebEngineWidgets)
- Sem banco de dados, sem backend

### Gaps / Decisões
- O pua-minder usa `MessagingAccount` model (SQLAlchemy). Aqui vamos simplificar — sem ORM, profiles hardcoded por slot (1..4).
- Anti-detecção e Chrome header spoof serão copiados integralmente.
- O sidebar toggle do WhatsApp será adaptado para ter 3 estados: expandido → colapsado → 50%.
