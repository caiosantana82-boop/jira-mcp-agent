# jira-mcp-agent

**Agente de IA sobre o Jira, exposto via MCP, com autonomia que cresce em 4 estágios.**
O modelo pode propor; quem aprova é uma pessoa. Toda ação, permitida ou negada, vai para a trilha de auditoria.

```
Claude / cliente MCP ──► ferramentas MCP ──► GovernedJira ──► Policy (estágio + regras) ──► Jira
                                                │                     │
                                                └──── auditoria JSONL ◄┘
                          aprovação humana (decide) ── NÃO é ferramenta do modelo
```

## Os 4 estágios de autonomia

| Estágio | O agente pode | Exemplo |
|---|---|---|
| 1 · `READ_ONLY` | buscar e ler issues | "quais itens estão em Code Review?" |
| 2 · `ALERTS` | + gerar alertas, sem escrever | "itens parados há mais de 5 dias" |
| 3 · `HUMAN_APPROVED` | + **propor** escritas; cada uma espera aprovação nominal | mover item, adicionar label |
| 4 · `POLICY_GOVERNED` | + aplicar sozinho **só** o que a política lista como baixo risco | `Code Review → Waiting to Test`, label `stale` |

Guardrails que valem em qualquer estágio:
- **Status protegidos** (ex.: `Done`) nunca são alterados pelo agente.
- **Orçamento de escritas automáticas** por execução; ao estourar, volta para aprovação humana.
- **Sem dado pessoal**: o responsável aparece como ID pseudônimo (`user-01`), nunca nome ou e-mail.
- **A aprovação não é uma ferramenta MCP**: o modelo não consegue se autoaprovar.

## Rodando

```bash
pip install -e ".[dev]"        # testes (sem dependências externas)
pytest -q                      # 8 testes cobrindo cada estágio e guardrail

pip install -e ".[mcp]"        # servidor MCP (SDK 1.x ou 2.x)
AGENT_STAGE=2 python -m jira_agent.server
```

Configuração no cliente MCP (ex.: Claude Desktop):

```json
{
  "mcpServers": {
    "governed-jira": {
      "command": "python",
      "args": ["-m", "jira_agent.server"],
      "env": { "AGENT_STAGE": "3" }
    }
  }
}
```

## Exemplo (estágio 3)

```python
from jira_agent.governed import GovernedJira
from jira_agent.policy import Policy, Stage
from jira_agent.store import sample_jira

agent = GovernedJira(sample_jira(), Policy(stage=Stage.HUMAN_APPROVED))
res = agent.request_transition("DEMO-001", "Waiting to Test", "review concluído")
# {'applied': False, 'proposal_id': 1, 'status': 'pending human approval'}

agent.decide(res["proposal_id"], approver="po-01", approve=True)   # só o humano aplica
print(agent.audit_jsonl())
```

## Estrutura

```
src/jira_agent/
  store.py      # Jira em memória com dados sintéticos (troque por um cliente real com os mesmos métodos)
  policy.py     # estágios, regras, status protegidos, orçamento de escritas
  governed.py   # ferramentas + fila de aprovação + auditoria
  server.py     # servidor MCP
tests/test_governance.py
```

## Para produção

- Trocar `MockJira` por cliente da Jira REST API v3 (`POST /rest/api/3/search/jql`, paginação por `nextPageToken`).
- Persistir a fila de aprovação e a auditoria (ex.: tabela ou lista SharePoint) e notificar o aprovador.
- Política por time em YAML, versionada junto do prompt.

---
Código de referência com **dados 100% sintéticos**; nenhum dado corporativo. Licença MIT.
