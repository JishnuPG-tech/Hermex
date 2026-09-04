import base64
import os

path = 'assets/composeResources/claude.agentchat.generated.resources/values/strings.commonMain.cvr'
if os.path.exists(path):
    with open(path, 'r') as f:
        content = f.read()
    lines = content.split('\n')
    for line in lines:
        parts = line.split('|')
        if len(parts) == 3:
            try:
                decoded = base64.b64decode(parts[2]).decode('utf-8')
                print(f'{parts[1]}: {decoded}')
            except:
                pass
else:
    print(f'File not found: {path}')
