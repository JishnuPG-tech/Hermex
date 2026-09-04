import base64
import os

def patch_file(path):
    if not os.path.exists(path):
        return

    with open(path, 'r') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        parts = line.strip().split('|')
        if len(parts) == 3:
            key = parts[1]
            try:
                decoded = base64.b64decode(parts[2]).decode('utf-8')
                if 'Claude' in decoded:
                    new_val = decoded.replace('Claude', 'Hermes')
                    encoded = base64.b64encode(new_val.encode('utf-8')).decode('utf-8')
                    line = f'{parts[0]}|{parts[1]}|{encoded}\n'
            except:
                pass
        new_lines.append(line if line.endswith('\n') else line + '\n')

    with open(path, 'w') as f:
        f.writelines(new_lines)

paths = [
    'assets/composeResources/claude.agentchat.generated.resources/values/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-de/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-es/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-fr/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-hi/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-it/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-ja/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-ko/strings.commonMain.cvr',
    'assets/composeResources/claude.agentchat.generated.resources/values-pt/strings.commonMain.cvr'
]

for p in paths:
    print(f'Patching {p}...')
    patch_file(p)
