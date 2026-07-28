#!/usr/bin/env python3
"""Controleert de workflow-JSON's op fouten die je pas in productie zou merken.

Gebruik:  python3 scripts/valideer-workflows.py

Naast de gebruikelijke JSON- en verwijzingscontroles zitten hier twee regels in die
voortkomen uit fouten die we echt hebben gehad:

* Een Data Table-leesnode zonder 'matchType' valt bij n8n terug op ANY_CONDITION.
  Staat er dan geen enkele voorwaarde, dan matcht 'één van nul voorwaarden' niets en
  krijg je stil nul rijen terug in plaats van alle rijen.
* Een schrijfnode met 'doorgaan bij fout' geeft bij een mislukking een item met een
  'error'-veld door. Controleert de volgende Code-node dat niet, dan meldt de bot
  succes terwijl er niets is opgeslagen.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / 'workflows'
SCHRIJFACTIES = {'insert', 'update', 'upsert', 'deleteRows'}

fouten: list[str] = []
waarschuwingen: list[str] = []


def controleer(pad: pathlib.Path) -> None:
    naam = pad.name
    try:
        wf = json.loads(pad.read_text())
    except json.JSONDecodeError as exc:
        fouten.append(f'{naam}: ongeldige JSON — {exc}')
        return

    nodes = {n['name']: n for n in wf.get('nodes', [])}

    # Verwijzingen in de verbindingen moeten bestaan.
    for bron, verbindingen in wf.get('connections', {}).items():
        if bron not in nodes:
            fouten.append(f'{naam}: verbinding vanaf onbekende node {bron!r}')
        for uitgangen in verbindingen.values():
            for tak in uitgangen:
                for verbinding in tak:
                    if verbinding['node'] not in nodes:
                        fouten.append(f'{naam}: verbinding naar onbekende node {verbinding["node"]!r}')

    # Welke node volgt op welke, zodat we schrijfacties met hun bevestiging kunnen koppelen.
    volgt_op: dict[str, list[str]] = {}
    for bron, verbindingen in wf.get('connections', {}).items():
        for uitgangen in verbindingen.values():
            for tak in uitgangen:
                for verbinding in tak:
                    volgt_op.setdefault(bron, []).append(verbinding['node'])

    for node in wf.get('nodes', []):
        params = node.get('parameters', {})

        # JavaScript in Code-nodes moet in elk geval parseerbaar zijn.
        code = params.get('jsCode')
        if code:
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as tmp:
                tmp.write('(async function(){\n' + code + '\n})')
                tmp_pad = tmp.name
            resultaat = subprocess.run(['node', '--check', tmp_pad], capture_output=True, text=True)
            pathlib.Path(tmp_pad).unlink()
            if resultaat.returncode != 0:
                eerste_regel = resultaat.stderr.strip().splitlines()[-1] if resultaat.stderr.strip() else 'onbekende fout'
                fouten.append(f'{naam} / {node["name"]}: JavaScript-fout — {eerste_regel}')

        if node.get('type') != 'n8n-nodes-base.dataTable':
            continue
        operatie = params.get('operation')

        if operatie == 'get' and 'matchType' not in params:
            fouten.append(
                f'{naam} / {node["name"]}: leesnode zonder matchType. Zonder deze waarde valt '
                'n8n terug op ANY_CONDITION en levert een filter zonder voorwaarden nul rijen op. '
                'Zet matchType op "ALL_CONDITIONS".'
            )

        if operatie in SCHRIJFACTIES and node.get('onError') == 'continueRegularOutput':
            # Ergens ná deze node moet een Code-node de mislukking oppikken. Dat hoeft niet de
            # directe opvolger te zijn: soms meldt pas het eindbericht wat er misging.
            te_bezoeken = list(volgt_op.get(node['name'], []))
            gezien: set[str] = set()
            controleert = False
            while te_bezoeken:
                huidige = te_bezoeken.pop()
                if huidige in gezien:
                    continue
                gezien.add(huidige)
                opvolger_code = nodes.get(huidige, {}).get('parameters', {}).get('jsCode', '')
                if 'error' in opvolger_code or 'mislukt' in opvolger_code:
                    controleert = True
                    break
                te_bezoeken.extend(volgt_op.get(huidige, []))
            if gezien and not controleert:
                waarschuwingen.append(
                    f'{naam} / {node["name"]}: schrijfactie gaat door bij fouten, maar geen enkele '
                    'Code-node erna controleert het resultaat. Zo wordt succes gemeld terwijl er '
                    'niets is opgeslagen.'
                )


for pad in sorted(WORKFLOWS.glob('*.json')):
    controleer(pad)

for regel in waarschuwingen:
    print(f'WAARSCHUWING  {regel}')
for regel in fouten:
    print(f'FOUT          {regel}')

aantal = len(list(WORKFLOWS.glob('*.json')))
if fouten:
    print(f'\n{len(fouten)} fout(en) in {aantal} workflows.')
    sys.exit(1)
print(f'\n{aantal} workflows gecontroleerd, geen fouten' + (f' ({len(waarschuwingen)} waarschuwing(en))' if waarschuwingen else '') + '.')
